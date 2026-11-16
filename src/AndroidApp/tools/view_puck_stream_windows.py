"""Windows USB launcher for view_puck_stream.py; Python standard library only.

Save both scripts in one folder, enable the phone's GPU tracking test, then run:
    py view_puck_stream_windows.py
    py view_puck_stream_windows.py --headless --duration 120

Finds ADB, selects an authorized USB device, establishes TCP forwarding and starts
the shared viewer. Never installs packages, modifies PATH, builds or installs an APK.
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys


PHONE_PORT = 8765


def find_adb(explicit=None):
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise RuntimeError("ADB executable not found: {}".format(path))
        return str(path.resolve())
    for executable in ("adb.exe", "adb"):
        found = shutil.which(executable)
        if found:
            return found
    candidates = []
    for name in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(name):
            candidates.append(Path(os.environ[name]) / "platform-tools" / "adb.exe")
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    candidates.extend((Path(__file__).resolve().parent / "platform-tools" / "adb.exe",
                       Path.home() / "Downloads" / "platform-tools" / "adb.exe"))
    for path in candidates:
        if path.is_file():
            return str(path.resolve())
    raise RuntimeError(
        "ADB was not found. Install Android SDK Platform Tools for Windows, or pass "
        '--adb "C:\\path\\to\\platform-tools\\adb.exe". '
        "Android Studio's default SDK and Downloads/platform-tools are checked automatically.")


def adb_run(adb, *arguments):
    try:
        result = subprocess.run([adb, *arguments], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Could not run ADB: {}".format(error)) from error
    if result.returncode:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError("ADB {} failed: {}".format(" ".join(arguments), details))
    return result.stdout.strip()


def select_device(adb, requested_serial=None):
    # -d explicitly selects a USB transport rather than an emulator or Wi-Fi ADB.
    selection = ["-s", requested_serial] if requested_serial else ["-d"]
    try:
        if adb_run(adb, *selection, "get-state") != "device":
            raise RuntimeError("The selected phone is not ready")
        serial = adb_run(adb, *selection, "get-serialno")
        if not serial or serial == "unknown":
            raise RuntimeError("ADB did not identify the phone")
        return serial
    except RuntimeError as error:
        try:
            devices = adb_run(adb, "devices", "-l")
        except RuntimeError:
            devices = "Device listing unavailable"
        raise RuntimeError(
            "{}\n{}\nConnect a USB data cable, unlock the phone, enable USB debugging and "
            "approve its authorization prompt. For several USB devices, pass --serial SERIAL. "
            "If a Pixel is missing in Windows, check the Google USB Driver.".format(error, devices)) from error


def forwarding_exists(adb, serial, local_port):
    """Reuse an identical mapping; refuse to overwrite another device/service."""
    local = "tcp:{}".format(local_port)
    remote = "tcp:{}".format(PHONE_PORT)
    for line in adb_run(adb, "forward", "--list").splitlines():
        columns = line.split()
        if len(columns) >= 3 and columns[1] == local:
            if columns[0] == serial and columns[2] == remote:
                return True
            raise RuntimeError("{} already forwards another connection. Choose --port 8766 (or another free port).".format(local))
    return False


def run_viewer(adb, serial, local_port, command):
    created = False
    try:
        if not forwarding_exists(adb, serial, local_port):
            adb_run(adb, "-s", serial, "forward", "--no-rebind",
                    "tcp:{}".format(local_port), "tcp:{}".format(PHONE_PORT))
            created = True
        # Argument arrays preserve executable/report paths containing spaces. No shell.
        return subprocess.run(command).returncode
    finally:
        if created:
            try:
                if forwarding_exists(adb, serial, local_port):
                    adb_run(adb, "-s", serial, "forward", "--remove", "tcp:{}".format(local_port))
            except RuntimeError as error:
                print("Forward cleanup: {}".format(error), file=sys.stderr)


def positive_duration(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("duration must be a finite positive number")
    return number


def port_number(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duration", type=positive_duration, default=60, help="benchmark seconds (default: 60)")
    parser.add_argument("--report", type=Path, help="report path (default: timestamped JSON in ./puck-reports)")
    parser.add_argument("--headless", action="store_true", help="collect results without a Tk window")
    parser.add_argument("--live", action="store_true", help="print actual received rates once per second")
    parser.add_argument("--latency", action="store_true", help="estimate end-to-end latency with clock synchronization")
    parser.add_argument("--serial", help="ADB serial when several phones are connected")
    parser.add_argument("--adb", help="explicit path to adb.exe")
    parser.add_argument("--port", type=port_number, default=PHONE_PORT, help="PC TCP port (phone always uses 8765)")
    parser.add_argument("--self-test", action="store_true", help="test shared viewer statistics; no phone/ADB needed")
    args = parser.parse_args(argv)
    viewer = Path(__file__).resolve().with_name("view_puck_stream.py")
    if not viewer.is_file():
        print("Keep view_puck_stream.py in the same folder as this launcher.", file=sys.stderr)
        return 2
    if sys.version_info < (3, 8):
        print("Python 3.8 or newer is required.", file=sys.stderr)
        return 2
    if args.self_test:
        return subprocess.run([sys.executable, str(viewer), "--self-test"]).returncode
    try:
        if not args.headless:
            try:
                import tkinter  # noqa: F401 -- availability check; viewer creates the window
            except ImportError as error:
                raise RuntimeError("Tk is unavailable. Use --headless or install Python with Tcl/Tk support.") from error
        adb = find_adb(args.adb)
        serial = select_device(adb, args.serial)
        report = (args.report or (Path.cwd() / "puck-reports" /
                  "puck-{}.json".format(datetime.now().strftime("%Y%m%d-%H%M%S-%f")))).expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        print("USB phone: {}\nReport: {}".format(serial, report), flush=True)
        print("Keep 'USB tracking: On' selected and the app in the foreground.", flush=True)
        command = [sys.executable, str(viewer), "--host", "127.0.0.1", "--port", str(args.port),
                   "--duration", str(args.duration), "--report", str(report)]
        if args.headless:
            command.append("--headless")
        if args.live:
            command.append("--live")
        if args.latency:
            command.append("--latency")
        return run_viewer(adb, serial, args.port, command)
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
