"""View and benchmark the Android puck NDJSON stream (after ``adb forward tcp:8765 tcp:8765``).

Run with ``python3 view_puck_stream.py`` on macOS. Use ``--headless`` when Python has
no Tk support, or ``--self-test`` to run the standard-library-only statistics checks.
"""

import argparse
import json
import math
import socket
import statistics
import sys
import threading
import time
from collections import deque


class StreamStats:
    """Bounded rolling samples and run-wide counters measured with the Mac clock."""

    def __init__(self, window_seconds=10.0):
        self.started = time.monotonic()
        self.window_seconds = window_seconds
        self.arrivals = deque()
        self.processing_ms = deque(maxlen=10000)
        self.reported_rates = {key: deque(maxlen=10000) for key in
                               ("capture_fps", "analysis_fps", "detected_fps", "source_fps")}
        self.frame_age_ms = deque(maxlen=10000)
        self.received = 0
        self.detected = 0
        self.invalid = 0
        self.frame_gaps = 0
        self.last_frame_id = None
        self.unique_texture_frames = 0
        self.last_texture_timestamp = None
        self.last_timestamp_source = "unknown"
        self.latest = None
        self.latest_arrival = None
        self.lock = threading.Lock()

    @staticmethod
    def _number(value):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _integer(value):
        # Keep nanosecond/frame counters as integers; converting these through float
        # would lose low bits once timestamps pass 2**53.
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    def add(self, sample, arrival=None):
        arrival = time.monotonic() if arrival is None else arrival
        if not isinstance(sample, dict):
            self.invalid += 1
            return False
        detected = bool(sample.get("detected", sample.get("x") is not None and sample.get("y") is not None))
        x = self._number(sample.get("x")) if detected else None
        y = self._number(sample.get("y")) if detected else None
        if detected and (x is None or y is None):
            detected = False
        with self.lock:
            self.received += 1
            if detected:
                self.detected += 1
            self.arrivals.append((arrival, detected))
            while self.arrivals and arrival - self.arrivals[0][0] > self.window_seconds:
                self.arrivals.popleft()
            processing = self._number(sample.get("processing_ms"))
            if processing is not None and processing >= 0:
                self.processing_ms.append(processing)
            for key, values in self.reported_rates.items():
                rate = self._number(sample.get(key))
                if rate is not None and rate >= 0:
                    values.append(rate)
            # frame_age_ms is supplied by the phone only when it can safely compare
            # clock domains. Never derive it by subtracting phone and Mac timestamps.
            self.last_timestamp_source = str(sample.get("timestamp_source", "unknown"))
            if self.last_timestamp_source.upper() == "REALTIME":
                age = self._number(sample.get("frame_age_ms"))
                if age is not None and age >= 0:
                    self.frame_age_ms.append(age)
            frame_id = self._integer(sample.get("frame_id"))
            if frame_id is not None:
                if self.last_frame_id is not None and frame_id < self.last_frame_id:
                    # Tracking can restart its sequence after app/mode changes.
                    self.last_frame_id = frame_id
                else:
                    if self.last_frame_id is not None and frame_id > self.last_frame_id + 1:
                        self.frame_gaps += frame_id - self.last_frame_id - 1
                    if self.last_frame_id is None or frame_id > self.last_frame_id:
                        self.last_frame_id = frame_id
            texture = self._integer(sample.get("capture_timestamp_ns"))
            if texture is None:
                texture = self._integer(sample.get("preview_timestamp_ns"))
            if texture is not None and texture > 0 and texture != self.last_texture_timestamp:
                self.unique_texture_frames += 1
                self.last_texture_timestamp = texture
            enriched = dict(sample)
            enriched["_detected"] = detected
            enriched["_x"] = x
            enriched["_y"] = y
            self.latest = enriched
            self.latest_arrival = arrival
        return True

    def display_state(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            return self.latest, None if self.latest_arrival is None else max(0.0, now - self.latest_arrival)

    @staticmethod
    def _summary(values):
        if not values:
            return {"mean": None, "p95": None}
        ordered = sorted(values)
        return {"mean": round(statistics.fmean(values), 3),
                "p95": round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 3)}

    @staticmethod
    def _rate(count, elapsed):
        return round(count / elapsed, 3) if elapsed > 0 else None

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            while self.arrivals and now - self.arrivals[0][0] > self.window_seconds:
                self.arrivals.popleft()
            duration = max(0.0, now - self.started)
            oldest = self.arrivals[0][0] if self.arrivals else now
            span = max(0.0, now - oldest)
            if len(self.arrivals) > 1:
                span = max(span, self.arrivals[-1][0] - self.arrivals[0][0])
            count = len(self.arrivals)
            detected_count = sum(1 for _, is_detected in self.arrivals if is_detected)
            gaps = [self.arrivals[i][0] - self.arrivals[i - 1][0]
                    for i in range(1, len(self.arrivals))]
            frame_age = list(self.frame_age_ms)
            return {
                "duration_seconds": round(duration, 3),
                "received_messages": self.received,
                "detected_messages": self.detected,
                "invalid_messages": self.invalid,
                "detection_ratio": round(self.detected / self.received, 4) if self.received else None,
                "received_rate_hz": self._rate(self.received, duration),
                "detected_received_rate_hz": self._rate(self.detected, duration),
                "rolling_received_rate_hz": self._rate(count, span),
                "rolling_detected_received_rate_hz": self._rate(detected_count, span),
                "arrival_gap_ms": self._summary([gap * 1000 for gap in gaps]),
                "estimated_missing_frame_ids": self.frame_gaps,
                "observed_unique_texture_rate_hz": self._rate(self.unique_texture_frames, duration),
                "processing_ms": self._summary(list(self.processing_ms)),
                "reported_phone_rates_fps": {key: self._summary(list(values))
                                              for key, values in self.reported_rates.items()},
                "frame_age_ms_from_phone_when_realtime": self._summary(frame_age),
                "timestamp_source": self.last_timestamp_source,
                "measurement_notes": [
                    "Whole-run received rates use Mac wall elapsed time since viewer start, including connection startup.",
                    "Phone-reported camera rates come from message metadata; message arrivals are not camera capture speed.",
                    "Observed unique texture rate counts distinct phone texture timestamps seen by this receiver.",
                    "Detection ratio describes received samples and does not measure detection accuracy.",
                ],
            }


def receive(host, port, stats, stop, errors):
    try:
        with socket.create_connection((host, port), timeout=5) as connection:
            connection.settimeout(0.5)
            pending = bytearray()
            while not stop.is_set():
                try:
                    chunk = connection.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    errors.append("Puck stream closed (tracking disabled or app paused).")
                    stop.set()
                    return
                pending.extend(chunk)
                while True:
                    newline = pending.find(b"\n")
                    if newline < 0:
                        if len(pending) > 65536:
                            stats.invalid += 1
                            pending.clear()
                        break
                    line = bytes(pending[:newline]).strip()
                    del pending[:newline + 1]
                    if not line:
                        continue
                    if len(line) > 65536:
                        stats.invalid += 1
                        continue
                    try:
                        stats.add(json.loads(line.decode("utf-8")))
                    except (json.JSONDecodeError, UnicodeError):
                        stats.invalid += 1
    except OSError as exc:
        errors.append("Could not read puck stream: {}".format(exc))
        stop.set()


def report(stats, path=None):
    result = stats.snapshot()
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if path:
        with open(path, "w", encoding="utf-8") as output:
            output.write(encoded + "\n")
    print(encoded)
    return result


def run_self_test():
    stats = StreamStats(window_seconds=20)
    stats.started = 10
    stats.add({"detected": True, "x": 12, "y": 24, "frame_id": 1,
               "processing_ms": 4, "source_fps": 59.9,
               "timestamp_ns": 999999999999, "frame_age_ms": 9999,
               "timestamp_source": "UNKNOWN"}, arrival=10)
    stats.add({"detected": False, "x": None, "y": None, "frame_id": 3,
               "processing_ms": 6, "source_fps": 60,
               "timestamp_source": "REALTIME", "frame_age_ms": 8}, arrival=11)
    snap = stats.snapshot(now=12)
    assert snap["received_messages"] == 2
    assert snap["detected_messages"] == 1
    assert snap["detection_ratio"] == 0.5
    assert snap["received_rate_hz"] == 1.0
    assert snap["estimated_missing_frame_ids"] == 1
    assert snap["processing_ms"] == {"mean": 5.0, "p95": 6.0}
    assert snap["reported_phone_rates_fps"]["source_fps"]["mean"] == 59.95
    assert snap["frame_age_ms_from_phone_when_realtime"]["mean"] == 8.0
    assert StreamStats._summary([]) == {"mean": None, "p95": None}

    rollover = StreamStats(window_seconds=1)
    rollover.started = 0
    rollover.add({"detected": False}, arrival=0)
    rollover.add({"detected": False}, arrival=2.1)
    rolled = rollover.snapshot(now=2.2)
    assert rolled["rolling_received_rate_hz"] == 10.0
    assert rolled["arrival_gap_ms"] == {"mean": None, "p95": None}

    reset = StreamStats()
    reset.add({"frame_id": 10, "preview_timestamp_ns": 9007199254740993}, arrival=1)
    reset.add({"frame_id": 12, "preview_timestamp_ns": 9007199254740993}, arrival=2)
    reset.add({"frame_id": 1, "preview_timestamp_ns": 9007199254740994}, arrival=3)
    reset.add({"frame_id": 3, "preview_timestamp_ns": 9007199254740994}, arrival=4)
    reset.add([], arrival=5)
    reset_snap = reset.snapshot(now=6)
    assert reset_snap["estimated_missing_frame_ids"] == 2
    assert reset.unique_texture_frames == 2
    assert reset_snap["invalid_messages"] == 1
    assert reset.last_texture_timestamp == 9007199254740994
    print("Self-test passed.")


def _gui(stats, stop, duration, errors, report_path):
    try:
        import tkinter as tk
    except ImportError as exc:
        raise RuntimeError("Tkinter is unavailable; rerun with --headless") from exc
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError("No Tk display is available; rerun with --headless") from exc
    root.title("Puck stream")
    root.geometry("230x180+30+30")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.configure(bg="#15191f")
    canvas = tk.Canvas(root, width=230, height=180, bg="#15191f", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    started = time.monotonic()
    finished = False

    def close():
        nonlocal finished
        if not finished:
            finished = True
            stop.set()
            report(stats, report_path)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    def draw():
        nonlocal finished
        if stop.is_set() or (duration is not None and time.monotonic() - started >= duration):
            close()
            return
        canvas.delete("all")
        canvas.create_text(12, 10, anchor="nw", fill="#e8edf2", font=("Helvetica", 11, "bold"),
                           text="PUCK STREAM")
        sample, age = stats.display_state()
        canvas.create_rectangle(25, 28, 205, 114, outline="#52616f", width=1)
        if sample is None or age > 0.25:
            canvas.create_text(115, 72, fill="#ff7777", font=("Helvetica", 15, "bold"), text="LOST")
        elif not sample["_detected"]:
            canvas.create_text(115, 72, fill="#f3b65f", font=("Helvetica", 15, "bold"), text="PUCK LOST")
        else:
            width = max(1, StreamStats._number(sample.get("image_width")) or 1)
            height = max(1, StreamStats._number(sample.get("image_height")) or 1)
            x = min(203, max(27, 27 + 176 * sample["_x"] / width))
            y = min(112, max(30, 30 + 82 * sample["_y"] / height))
            canvas.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#59d68c", outline="white", width=2)
            canvas.create_text(115, 123, fill="#e8edf2", font=("Helvetica", 10),
                               text="x {:.1f}  y {:.1f} px".format(sample["_x"], sample["_y"]))
        snap = stats.snapshot()
        phone_source = snap["reported_phone_rates_fps"]["source_fps"]["mean"]
        fps = "source {} fps".format("—" if phone_source is None else "{:.1f}".format(phone_source))
        canvas.create_text(115, 157, fill="#aab5c0", font=("Helvetica", 9),
                           text="{}  |  detections {:.0%}".format(fps, snap["detection_ratio"] or 0))
        root.after(50, draw)

    draw()
    root.mainloop()
    if not finished:
        close()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="macOS: run 'adb forward tcp:8765 tcp:8765', then "
               "'python3 view_puck_stream.py'. Add --headless for terminal-only use.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--headless", action="store_true", help="collect and report without opening a window")
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    parser.add_argument("--report", metavar="PATH", help="also save the final benchmark JSON to PATH")
    parser.add_argument("--self-test", action="store_true", help="run local statistics checks and exit")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be greater than zero")
    stats, stop, errors = StreamStats(), threading.Event(), []
    receiver = threading.Thread(target=receive, args=(args.host, args.port, stats, stop, errors), daemon=True)
    receiver.start()
    try:
        if args.headless:
            end = None if args.duration is None else time.monotonic() + args.duration
            while not stop.is_set() and (end is None or time.monotonic() < end):
                time.sleep(0.1)
            stop.set()
            report(stats, args.report)
        else:
            _gui(stats, stop, args.duration, errors, args.report)
    except RuntimeError as exc:
        stop.set()
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        stop.set()
        report(stats, args.report)
    finally:
        stop.set()
        receiver.join(timeout=1)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors and stats.received == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
