"""One-shot latency test: how long from the puck changing to the Mac seeing the change.

The Mac shows a yellow disc and the phone camera looks at the Mac screen. Press Space and the disc
disappears (the flash test), or press J and it jumps once to a new spot (the jump test). The script
notes the Mac's clock at that moment, then waits for the first stream sample that says "no tracking"
(the puck vanished, or the tracker rejected the far jump). It prints the time difference. That covers the camera, the readback, the
phone's Python tracker and the USB link. It also INCLUDES the Mac screen's own delay (the clock is
read when the draw call returns, but the light changes a refresh or two later, roughly 10 to 35 ms
on a 60 Hz screen), so the phone's real latency is a little lower than the number printed. It is
only as precise as the gap between samples (about 46 ms right now).
A random tracking dropout right after the jump would also count, so repeat it a few times.

    python3 latency_jump_test.py

1. Point the phone at the Mac screen, with the app open and "Track yellow puck" on. Turn the
   screen brightness up.
2. Press Up/Down to resize the disc until the window says the phone sees the puck.
3. Press Space. The disc disappears and the result is printed. Press Space again to bring it back,
   wait for the phone to see it, then Space to measure again. J does the same with a jump instead
   (needs the disc showing). Esc quits.

If the jump test says the tracker never lost the puck, make --jump bigger so the tracker rejects it.
"""

import argparse
import json
import queue
import socket
import sys
import threading
import time
from collections import deque

from show_puck_stream import forward_port

YELLOW = "#BEB647"


class JumpTest:
    """The timing logic, with no window in it so it can be tested on its own.

    move(index) puts the disc at spot 0 or 1 and returns once it is drawn.
    history is a deque of (arrival_time, detected, x, y) from the stream, newest last.
    """

    def __init__(self, move, history, hide=None, timeout=3.0, clock=time.perf_counter):
        self.move, self.hide, self.history = move, hide, history
        self.timeout, self.clock = timeout, clock
        self.spot = 0
        self.waiting = None      # time of the jump or the flash
        self.kind = "jump"
        self.result = None       # set when finished: a dict, or {"error": text}

    def arm(self, kind="jump"):
        """Jump the disc ("jump") or hide it ("flash") and start timing.
        Returns None, or a reason it could not start."""
        # The phone must be tracking the disc now, otherwise "no tracking" would mean nothing
        if not any(s[1] for s in list(self.history) if self.clock() - s[0] < 0.6):
            return "the phone has not seen the disc in the last 0.6 s"
        self.result, self.kind = None, kind
        if kind == "flash":
            self.hide()
        else:
            self.spot = 1 - self.spot
            self.move(self.spot)
        self.waiting = self.clock()   # timestamp after the draw call returns
        return None

    def tick(self):
        """Call often (every few ms)."""
        if self.waiting is None:
            return
        jumped_at = self.waiting
        for arrival, detected, _x, _y in list(self.history):
            if arrival > jumped_at and not detected:
                # The tracker lost the puck (its continuity gate rejects a far jump)
                self.result = {"latency_ms": (arrival - jumped_at) * 1000}
                self.waiting = None
                return
        if self.clock() - jumped_at > self.timeout:
            hint = ("Make --jump bigger so the tracker rejects the new spot." if self.kind == "jump"
                    else "The tracker may be holding on to the old position, or the stream stalled.")
            self.result = {"error": "the phone never reported no tracking within %.0f s. %s" % (self.timeout, hint)}
            self.waiting = None

    @staticmethod
    def describe(result):
        if "error" in result:
            return result["error"]
        return "latency %.0f ms   (until the phone reported no tracking)   Space: show the disc again" % result["latency_ms"]


def read_stream(host, port, history, last):
    """Background thread: keeps the stream's (arrival time, detected, x, y) in history."""
    while True:
        try:
            connection = socket.create_connection((host, port), timeout=5)
        except OSError:
            time.sleep(1)
            continue
        connection.settimeout(None)
        with connection, connection.makefile("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    sample = json.loads(line)
                    detected = bool(sample.get("detected"))
                    x, y = (float(sample["x"]), float(sample["y"])) if detected else (0.0, 0.0)
                except (ValueError, KeyError, TypeError):
                    continue
                arrival = time.perf_counter()
                history.append((arrival, detected, x, y))
                last.update(arrival=arrival, detected=detected, x=x, y=y)
        time.sleep(1)


def main():
    import tkinter as tk

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--jump", type=int, default=200, help="how far the disc jumps on the Mac screen (screen px)")
    parser.add_argument("--no-adb", action="store_true")
    args = parser.parse_args()

    if not args.no_adb:
        forward_port(args.port)

    history = deque(maxlen=2000)
    last = {"arrival": 0.0, "detected": False, "x": 0.0, "y": 0.0}
    threading.Thread(target=read_stream, args=(args.host, args.port, history, last), daemon=True).start()

    root = tk.Tk()
    root.title("Latency jump test")
    root.configure(bg="black")
    canvas = tk.Canvas(root, width=900, height=700, bg="black", highlightthickness=0)
    canvas.pack()
    root.lift()
    root.focus_force()
    # Keys only reach this window when IT has focus (click on the black window, not the terminal).
    # Any other key prints here, so you can tell the window is receiving keys.
    root.bind("<Key>", lambda e: print("window received key %r (Space = flash, J = jump)" % e.keysym, flush=True))
    size = {"d": 120}
    spots = [(450 - args.jump // 2, 330), (450 + args.jump // 2, 330)]
    disc = canvas.create_oval(0, 0, 0, 0, fill=YELLOW, outline="")
    status = canvas.create_text(450, 670, fill="#999999", font=("Helvetica", 14))
    report = canvas.create_text(450, 60, fill="#cccccc", font=("Helvetica", 16), width=800, justify="center")

    def place(index):
        cx, cy = spots[index]
        half = size["d"] / 2
        canvas.coords(disc, cx - half, cy - half, cx + half, cy + half)
        root.update_idletasks()
        root.update()

    def hide():
        canvas.itemconfigure(disc, state="hidden")
        root.update_idletasks()
        root.update()

    test = JumpTest(place, history, hide=hide)
    test.spot = 0
    place(0)

    def resize(delta):
        if test.waiting is None:
            size["d"] = max(20, size["d"] + delta)
            place(test.spot)

    start = time.perf_counter()

    def stamp(t=None):
        return "t=%8.3f s" % ((time.perf_counter() if t is None else t) - start)

    def go(kind):
        key = "SPACE" if kind == "flash" else "J"
        if test.waiting is not None:
            print("%s  %s pressed, ignored (still waiting for the last test)" % (stamp(), key), flush=True)
            return
        if canvas.itemcget(disc, "state") == "hidden":
            if kind == "flash":              # Space again brings the disc back, no timing
                canvas.itemconfigure(disc, state="normal")
                canvas.itemconfigure(report, text="")
                print("%s  SPACE pressed: disc shown again (no timing)" % stamp(), flush=True)
            else:
                print("%s  J pressed, ignored (disc is hidden, press Space to show it)" % stamp(), flush=True)
            return
        canvas.itemconfigure(report, text="")
        problem = test.arm(kind)
        if problem:
            canvas.itemconfigure(report, text="Not started: " + problem)
            print("%s  %s pressed: NOT STARTED, %s" % (stamp(), key, problem), flush=True)
        else:
            what = "disc hidden" if kind == "flash" else "disc jumped"
            print("%s  >>> %s PRESSED, %s, timing starts now <<<" % (stamp(test.waiting), key, what), flush=True)

    root.bind("<Up>", lambda e: resize(10))
    root.bind("<Down>", lambda e: resize(-10))
    root.bind("<space>", lambda e: go("flash"))
    root.bind("<j>", lambda e: go("jump"))
    root.bind("<Escape>", lambda e: root.destroy())

    # Also start a test from the TERMINAL: press Enter there (flash) or type j and Enter (jump).
    # This works even when the black window does not have keyboard focus.
    commands = queue.Queue()

    def read_terminal():
        for line in sys.stdin:
            commands.put("jump" if line.strip().lower() == "j" else "flash")

    threading.Thread(target=read_terminal, daemon=True).start()
    print("Ready. Press Enter here in the terminal to flash the disc (or j then Enter to jump it).", flush=True)

    shown = {"t": time.perf_counter()}

    def print_samples():
        # Own thread: printing ~60 lines/s to a slow terminal must never block the window or the
        # reader thread (that would delay key presses and the arrival timestamps)
        while True:
            for arrival, detected, x, y in list(history):
                if arrival <= shown["t"]:
                    continue
                shown["t"] = arrival
                waiting = test.waiting
                since = "+%5.0f ms after press" % ((arrival - waiting) * 1000) if waiting is not None else ""
                print("%s  %s  %s" % (stamp(arrival), "tracked  x=%7.1f y=%7.1f" % (x, y) if detected else "NO TRACKING",
                                      since), flush=True)
            time.sleep(0.005)

    threading.Thread(target=print_samples, daemon=True).start()

    def loop():
        while not commands.empty():
            go(commands.get())
        test.tick()
        age = time.perf_counter() - last["arrival"]
        if age > 1.0:
            sees = "no data from the phone (app open, Track yellow puck on?)"
        elif last["detected"]:
            sees = "phone sees the puck at x=%.0f y=%.0f" % (last["x"], last["y"])
        else:
            sees = "phone does NOT see the puck (resize the disc / aim the camera)"
        if test.waiting is not None:
            canvas.itemconfigure(status, text="waiting for no tracking...   |   " + sees)
        else:
            canvas.itemconfigure(status, text=f"{sees}   |   disc {size['d']} px (Up/Down)   |   Space: flash (again: show)   J: jump   Esc: quit")
        if test.result is not None:
            text = JumpTest.describe(test.result)
            canvas.itemconfigure(report, text=text)
            print("%s  %s" % (stamp(), text), flush=True)
            test.result = None
        root.after(5, loop)

    loop()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
