"""Print the phone's live NDJSON puck stream after adb forward tcp:8765 tcp:8765."""

import argparse
import json
import socket
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    try:
        with socket.create_connection((args.host, args.port), timeout=5) as connection:
            connection.settimeout(None)
            with connection.makefile("r", encoding="utf-8") as stream:
                for line in stream:
                    sample = json.loads(line)
                    print(json.dumps(sample), flush=True)
        print("Puck stream closed (tracking disabled or app paused).", file=sys.stderr)
    except (OSError, ValueError) as error:
        print(f"Could not read puck stream: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
