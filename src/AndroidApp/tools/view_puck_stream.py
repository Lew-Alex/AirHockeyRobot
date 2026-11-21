"""View and benchmark the Android puck NDJSON stream (after ``adb forward tcp:8765 tcp:8765``).

Run with ``python3 view_puck_stream.py`` on macOS or ``py view_puck_stream.py`` on
Windows. Use ``--headless`` when Python has no Tk support, or ``--self-test`` to run
the standard-library-only statistics checks. Windows USB setup can also be automated
with the companion ``view_puck_stream_windows.py`` launcher.
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

try:
    from puck_clock_sync import ClockSync
except ImportError:
    ClockSync = None  # existing single-file viewer remains usable without --latency


class StreamStats:
    """Bounded rolling samples and run-wide counters measured with the receiver clock."""

    def __init__(self, window_seconds=10.0):
        self.started = time.monotonic()
        self.window_seconds = window_seconds
        self.arrivals = deque()
        self.processing_ms = deque(maxlen=10000)
        self.reported_rates = {key: deque(maxlen=10000) for key in
                               ("capture_fps", "analysis_fps", "detected_fps", "source_fps")}
        self.frame_age_ms = deque(maxlen=10000)
        self.latency_ms = {key: deque(maxlen=10000) for key in (
            "sensor_to_receiver_ms", "sample_to_receiver_ms", "publish_to_receiver_ms")}
        self.clock_summary = {"synchronized": False}
        self.latest_latency = {}
        self.stage_ms = {key: deque(maxlen=10000) for key in (
            "acquire_ms", "mask_readback_ms", "detection_ms", "previous_publish_ms",
            "previous_preview_ms", "previous_frame_work_ms")}
        self.received = 0
        self.detected = 0
        self.invalid = 0
        self.frame_gaps = 0
        self.last_frame_id = None
        self.frame_id_advances = 0
        self.frame_sequence_restarts = 0
        self.first_arrival = None
        self.last_arrival = None
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

    def add(self, sample, arrival=None, latency=None):
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
            if latency:
                self.latest_latency = latency
                for key, values in self.latency_ms.items():
                    value = self._number(latency.get(key))
                    if value is not None and value >= 0:
                        values.append(value)
            if self.first_arrival is None:
                self.first_arrival = arrival
            self.last_arrival = arrival
            if detected:
                self.detected += 1
            self.arrivals.append((arrival, detected))
            while self.arrivals and arrival - self.arrivals[0][0] > self.window_seconds:
                self.arrivals.popleft()
            processing = self._number(sample.get("processing_ms"))
            if processing is not None and processing >= 0:
                self.processing_ms.append(processing)
            for key, values in self.stage_ms.items():
                value = self._number(sample.get(key))
                if value is not None and value >= 0:
                    values.append(value)
            for key, values in self.reported_rates.items():
                rate = self._number(sample.get(key))
                if rate is not None and rate >= 0:
                    values.append(rate)
            # frame_age_ms is supplied by the phone only when it can safely compare
            # clock domains. Never derive it by subtracting phone and receiver timestamps.
            self.last_timestamp_source = str(sample.get("timestamp_source", "unknown"))
            if self.last_timestamp_source.upper() == "REALTIME":
                age = self._number(sample.get("frame_age_ms"))
                if age is not None and age >= 0:
                    self.frame_age_ms.append(age)
            frame_id = self._integer(sample.get("frame_id"))
            if frame_id is not None:
                if self.last_frame_id is not None and frame_id < self.last_frame_id:
                    # Tracking can restart its sequence after app/mode changes.
                    self.frame_sequence_restarts += 1
                    self.last_frame_id = frame_id
                else:
                    if self.last_frame_id is not None:
                        self.frame_id_advances += frame_id - self.last_frame_id
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

    def live_received_rate(self, now=None):
        """Cheap GUI path: avoid sorting full benchmark histories while receiving."""
        return self.live_rates(now)["messages_hz"]

    def live_rates(self, now=None):
        """All JSON samples and valid positions are distinct measured quantities."""
        now = time.monotonic() if now is None else now
        with self.lock:
            while self.arrivals and now - self.arrivals[0][0] > self.window_seconds:
                self.arrivals.popleft()
            if len(self.arrivals) < 2:
                messages, positions = 0.0, 0.0
            else:
                span = now - self.arrivals[0][0]
                messages = self._rate(len(self.arrivals) - 1, span) or 0.0
                position_count = sum(int(detected) for _, detected in self.arrivals) - int(self.arrivals[0][1])
                positions = self._rate(position_count, span) or 0.0
            latest = self.latest or {}
            return {"messages_hz": messages, "positions_hz": positions,
                    "frame_id_gaps": self.frame_gaps, "tracker": latest.get("tracker", "unspecified"),
                    "phone_analysis_hz": self._number(latest.get("analysis_fps")),
                    "phone_capture_hz": self._number(latest.get("capture_fps")),
                    "socket_written": latest.get("socket_written_messages"),
                    "socket_replaced": latest.get("socket_replaced_messages"),
                    "backend": latest.get("detector_backend"),
                    "sample_age_ms": self.latest_latency.get("sample_to_receiver_ms"),
                    "publish_age_ms": self.latest_latency.get("publish_to_receiver_ms")}

    def set_clock_summary(self, summary):
        with self.lock:
            self.clock_summary = summary

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
            observed_span = None if self.first_arrival is None else self.last_arrival - self.first_arrival
            return {
                "duration_seconds": round(duration, 3),
                "received_messages": self.received,
                "detected_messages": self.detected,
                "invalid_messages": self.invalid,
                "detection_ratio": round(self.detected / self.received, 4) if self.received else None,
                "received_rate_hz": self._rate(self.received, duration),
                "detected_received_rate_hz": self._rate(self.detected, duration),
                "rolling_received_rate_hz": self._rate(max(0,count-1), span) if count > 1 else 0.0,
                "rolling_detected_received_rate_hz": self._rate(detected_count-int(self.arrivals[0][1]), span) if count > 1 else 0.0,
                "received_cadence_hz": self._rate(self.received-1, observed_span) if observed_span else None,
                "frame_id_advance_rate_hz": self._rate(self.frame_id_advances, observed_span) if observed_span else None,
                "frame_sequence_restarts": self.frame_sequence_restarts,
                "arrival_gap_ms": self._summary([gap * 1000 for gap in gaps]),
                "estimated_missing_frame_ids": self.frame_gaps,
                "observed_unique_texture_rate_hz": self._rate(self.unique_texture_frames, duration),
                "processing_ms": self._summary(list(self.processing_ms)),
                "pipeline_stage_ms": {key: self._summary(list(values)) for key, values in self.stage_ms.items()},
                "latest_pipeline": {key: (self.latest or {}).get(key) for key in (
                    "tracker", "pipeline_revision", "requested_fps", "preview_enabled", "readback_bytes",
                    "analysis_width", "analysis_height", "sampling_limit_fps", "stream_revision", "detector_backend", "preview_target_fps")},
                "clock_sync": dict(self.clock_summary),
                "estimated_latency_ms": {key: self._summary(list(values)) for key, values in self.latency_ms.items()},
                "latest_phone_transport": {key: (self.latest or {}).get(key) for key in (
                    "socket_clients", "socket_offered_messages", "socket_written_messages",
                    "socket_replaced_messages", "socket_last_write_ms", "socket_max_write_ms")},
                "reported_phone_rates_fps": {key: self._summary(list(values))
                                              for key, values in self.reported_rates.items()},
                "frame_age_ms_from_phone_when_realtime": self._summary(frame_age),
                "timestamp_source": self.last_timestamp_source,
                "measurement_notes": [
                    "Whole-run received rates use receiver elapsed time since viewer start, including connection startup.",
                    "Phone-reported camera rates come from message metadata; message arrivals are not camera capture speed.",
                    "Phone rate summaries average per-message rolling estimates; they are not total captures divided by test duration.",
                    "received_cadence_hz excludes connection startup and the tail after the last sample.",
                    "frame_id_advance_rate_hz measures observed sender counter advances over receiver arrival time, not raw camera FPS.",
                    "Phone socket counters aggregate all clients and precede the sample carrying them; compare deltas with one connected reader.",
                    "Observed unique texture rate counts distinct phone texture timestamps seen by this receiver.",
                    "Detection ratio describes received samples and does not measure detection accuracy.",
                    "previous_* timings describe the prior processed frame; processing_ms excludes display and publishing.",
                    "Estimated end-to-end ages require clock sync and include clock offset uncertainty (see clock_sync).",
                    "sample_to_receiver starts at phone readback; sensor_to_receiver uses first-row sensor time only with REALTIME timestamps.",
                    "publish_to_receiver includes result formatting, socket queuing, USB/ADB and host reception; it is not pure cable delay.",
                ],
            }


def receive(host, port, stats, stop, errors, latency=False):
    if latency and ClockSync is None:
        errors.append("--latency requires puck_clock_sync.py in the same folder as the viewer.")
        stop.set()
        return
    clock = ClockSync() if latency else None
    try:
        with socket.create_connection((host, port), timeout=5) as connection:
            connection.settimeout(0.1 if clock else 0.5)
            pending = bytearray()
            next_probe_ns = 0
            probes_sent = 0
            while not stop.is_set():
                now_ns = time.monotonic_ns()
                if clock and now_ns >= next_probe_ns:
                    _, request = clock.start_probe(now_ns)
                    connection.sendall(request)
                    probes_sent += 1
                    next_probe_ns = now_ns + (100_000_000 if probes_sent < 8 else 10_000_000_000)
                try:
                    chunk = connection.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    errors.append("Puck stream closed (tracking disabled or app paused).")
                    stop.set()
                    return
                received_ns = time.monotonic_ns()
                received_at = received_ns / 1e9
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
                        # One timestamp per recv batch, before JSON/statistics work.
                        # Coalesced messages share a reception time; phone clocks
                        # are never subtracted from this receiver clock.
                        sample = json.loads(line.decode("utf-8"))
                        if isinstance(sample, dict) and sample.get("type") == "clock_sync":
                            if clock:
                                clock.accept_reply(sample,received_ns)
                                stats.set_clock_summary(clock.summary(received_ns))
                            continue  # diagnostic replies never count as coordinate updates
                        ages = None
                        if clock and isinstance(sample, dict):
                            ages = {"sample_to_receiver_ms": clock.age_ms(sample.get("timestamp_ns"),received_ns),
                                    "publish_to_receiver_ms": clock.age_ms(sample.get("phone_publish_timestamp_ns"),received_ns)}
                            if sample.get("timestamp_source") == "REALTIME":
                                ages["sensor_to_receiver_ms"] = clock.age_ms(sample.get("capture_timestamp_ns"),received_ns)
                        stats.add(sample, arrival=received_at, latency=ages)
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


def print_live_rates(stats):
    rates = stats.live_rates()
    def number(value):
        return "-" if value is None else "{:.1f}".format(value)
    print("Received {messages:.1f} messages/s | valid positions {positions:.1f}/s | "
          "phone analysis {analysis}/s | camera metadata {camera}/s | "
          "frame-ID gaps {gaps} | tracker {tracker}/{backend} | "
          "sample age {sample_age} ms | publish-to-receive {publish_age} ms".format(
              messages=rates["messages_hz"], positions=rates["positions_hz"],
              analysis=number(rates["phone_analysis_hz"]), camera=number(rates["phone_capture_hz"]),
              gaps=rates["frame_id_gaps"], tracker=rates["tracker"], backend=rates["backend"] or "unspecified",
              sample_age=number(rates["sample_age_ms"]), publish_age=number(rates["publish_age_ms"])), file=sys.stderr, flush=True)


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
    assert rolled["rolling_received_rate_hz"] == 0.0  # one point cannot establish an interarrival interval
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


def _gui(stats, stop, duration, errors, report_path, live=False):
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
    last_live = 0.0

    def close():
        nonlocal finished
        if not finished:
            finished = True
            stop.set()
            report(stats, report_path)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    def draw():
        nonlocal finished, last_live
        if stop.is_set() or (duration is not None and time.monotonic() - started >= duration):
            close()
            return
        canvas.delete("all")
        if live and time.monotonic()-last_live >= 1.0:
            last_live = time.monotonic()
            print_live_rates(stats)
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
        phone_source = StreamStats._number((sample or {}).get("source_fps"))
        fps = "source {}/s".format("-" if phone_source is None or age is None or age > 0.25 else "{:.1f}".format(phone_source))
        canvas.create_text(115, 157, fill="#aab5c0", font=("Helvetica", 9),
                           text="{} | received {:.1f}/s".format(fps, stats.live_received_rate()))
        root.after(50, draw)

    draw()
    root.mainloop()
    if not finished:
        close()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Run 'adb forward tcp:8765 tcp:8765', then 'python3 view_puck_stream.py' "
               "(macOS) or 'py view_puck_stream.py' (Windows). "
               "Add --headless for terminal-only use.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--headless", action="store_true", help="collect and report without opening a window")
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    parser.add_argument("--report", metavar="PATH", help="also save the final benchmark JSON to PATH")
    parser.add_argument("--self-test", action="store_true", help="run local statistics checks and exit")
    parser.add_argument("--live", action="store_true", help="print actual received message/position rates once per second")
    parser.add_argument("--latency", action="store_true", help="estimate capture/sample-to-receiver latency using clock-sync probes (updated app required)")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be greater than zero")
    if args.latency and ClockSync is None:
        parser.error("--latency needs puck_clock_sync.py next to view_puck_stream.py")
    stats, stop, errors = StreamStats(), threading.Event(), []
    receiver = threading.Thread(target=receive, args=(args.host, args.port, stats, stop, errors, args.latency), daemon=True)
    receiver.start()
    try:
        if args.headless:
            end = None if args.duration is None else time.monotonic() + args.duration
            last_live = 0.0
            while not stop.is_set() and (end is None or time.monotonic() < end):
                if args.live and time.monotonic()-last_live >= 1.0:
                    last_live = time.monotonic()
                    print_live_rates(stats)
                time.sleep(0.1)
            stop.set()
            receiver.join(timeout=1)
            report(stats, args.report)
        else:
            _gui(stats, stop, args.duration, errors, args.report, args.live)
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
