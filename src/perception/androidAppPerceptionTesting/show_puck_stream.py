"""Print the phone's live puck coordinates in the terminal, one short line per sample.

    python3 show_puck_stream.py          # runs `adb forward` for you, then prints
    python3 show_puck_stream.py --raw    # print the full JSON lines instead

Needs the phone connected by USB (USB debugging on) with the app open and
"Track yellow puck" switched on. If the app is not streaming yet, it keeps retrying.
Press Ctrl-C to stop.
"""

import argparse
import json
import socket
import subprocess
import sys
import time


def forward_port(port):
    """Point the Mac's localhost port at the same port on the phone."""
    try:
        result = subprocess.run(["adb", "forward", f"tcp:{port}", f"tcp:{port}"],
                                capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        sys.exit("adb not found. Install it with: brew install android-platform-tools")
    if result.returncode != 0:
        sys.exit(f"adb forward failed: {result.stderr.strip() or result.stdout.strip()}"
                 "\nIs the phone plugged in with USB debugging on? Check with: adb devices")


def format_sample(sample):
    if not sample.get("detected"):
        return f"frame {sample.get('frame_id', '?'):>6}   no puck"
    return (f"frame {sample.get('frame_id', '?'):>6}   x={sample['x']:8.1f}  y={sample['y']:8.1f}"
            f"   ({sample.get('processing_ms', 0):.1f} ms)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--raw", action="store_true", help="print each full JSON line")
    parser.add_argument("--no-adb", action="store_true", help="skip `adb forward` (port is already forwarded)")
    args = parser.parse_args()

    if not args.no_adb:
        forward_port(args.port)

    waiting = False
    try:
        while True:
            try:
                connection = socket.create_connection((args.host, args.port), timeout=5)
            except OSError:
                if not waiting:
                    print("waiting for the phone's stream (app open and Track yellow puck on?)...", flush=True)
                    waiting = True
                time.sleep(1)
                continue

            # adb accepts the connection on the Mac even when nothing is listening on the phone,
            # then drops it straight away, so only count it as connected once data arrives
            connection.settimeout(None)
            got_data = False
            with connection, connection.makefile("r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    if not got_data:
                        got_data = True
                        waiting = False
                        print("receiving data", flush=True)
                    if args.raw:
                        print(line, flush=True)
                        continue
                    try:
                        print(format_sample(json.loads(line)), flush=True)
                    except (ValueError, KeyError):
                        print(line, flush=True)
            if got_data:
                print("stream closed (tracking turned off or app paused), reconnecting...", flush=True)
            elif not waiting:
                print("adb is forwarding, but the app is not streaming: open the app and switch on "
                      "Track yellow puck (keep it in the foreground). Retrying...", flush=True)
                waiting = True
            time.sleep(1)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
