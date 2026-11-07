#!/usr/bin/env python3
"""Measure camera delivery rate and timestamp frames for an optical latency test."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event

import cv2
import numpy as np


LOG_DIR = Path(__file__).resolve().parent / "logs"
PREVIEW_WINDOW = "Camera latency | frame received"
CLOCK_WINDOW = "Source clock | point camera here"
NS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True)
class ReceivedFrame:
    number: int
    image: np.ndarray
    unix_ns: int
    fps: float


def clock_text(unix_ns: int) -> str:
    seconds, nanoseconds = divmod(unix_ns, NS_PER_SECOND)
    return f"{datetime.fromtimestamp(seconds):%H:%M:%S}.{nanoseconds // 1_000_000:03d}"


def frame_rate(count: int, elapsed_ns: int) -> float:
    return (count - 1) * NS_PER_SECOND / elapsed_ns if elapsed_ns > 0 else 0.0


def capture_frames(camera, log_path, latest, stop, seconds, recording, frame_queue):
    count = 0
    first_ns = previous_ns = 0
    recent = deque()

    with log_path.open("x", newline="", encoding="utf-8") as log:
        writer = csv.writer(log)
        writer.writerow(("frame", "receive_unix_ns", "receive_monotonic_ns", "interval_ms"))

        while not stop.is_set():
            ok, image = camera.read()
            received_ns = time.monotonic_ns()
            unix_ns = time.time_ns()
            save_frame = recording.is_set()
            if not ok:
                if stop.is_set():
                    break
                raise RuntimeError("Camera stopped delivering frames. Check the connection and camera permissions.")

            if count == 0:
                first_ns = received_ns
                height, width = image.shape[:2]
                print(f"Delivered resolution: {width}x{height}", flush=True)

            count += 1
            interval_ms = (received_ns - previous_ns) / 1_000_000 if previous_ns else ""
            writer.writerow((count, unix_ns, received_ns, interval_ms))
            previous_ns = received_ns

            recent.append(received_ns)
            while recent[0] < received_ns - NS_PER_SECOND:
                recent.popleft()
            frame = ReceivedFrame(count, image, unix_ns, frame_rate(len(recent), received_ns - recent[0]))
            if save_frame:
                try:
                    frame_queue.put_nowait(frame)
                except Full:
                    raise RuntimeError(
                        f"Image saving fell behind at frame {count}. Earlier queued frames will be saved."
                    ) from None
            latest.append(frame)

            if seconds and received_ns - first_ns >= seconds * NS_PER_SECOND:
                break

    return count, frame_rate(count, previous_ns - first_ns)


def save_frames(frame_queue, capture, folder: Path) -> int:
    saved = 0
    while not capture.done() or not frame_queue.empty():
        try:
            frame = frame_queue.get(timeout=0.1)
        except Empty:
            continue
        if saved == 0:
            folder.mkdir()
        path = folder / f"frame_{frame.number:08d}.jpg"
        if not cv2.imwrite(str(path), frame.image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            raise OSError(f"Could not save {path}")
        saved += 1
    return saved


def draw_frame(frame: ReceivedFrame, recording: bool) -> np.ndarray:
    # Draw on a copy so the preview never modifies the capture thread's image.
    image = frame.image.copy()
    lines = (f"Received {clock_text(frame.unix_ns)}", f"Frame {frame.number} | {frame.fps:.1f} FPS")
    scale = max(0.35, min(1.2, image.shape[1] / 750))
    for row, line in enumerate(lines):
        point = (12, 24 + row * 30)
        cv2.putText(image, line, point, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(image, line, point, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
    if recording:
        cv2.putText(image, "REC", (12, 84), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 255), 2, cv2.LINE_AA)
    return image


def show_preview(worker, frame_writer, latest, recording, frames_dir):
    cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(PREVIEW_WINDOW, 768, 432)
    cv2.namedWindow(CLOCK_WINDOW, cv2.WINDOW_AUTOSIZE)
    clock = np.zeros((105, 535, 3), dtype=np.uint8)
    last_frame = 0
    next_clock_update = 0

    while not worker.done() and not frame_writer.done():
        now = time.monotonic_ns()
        if now >= next_clock_update:
            clock.fill(0)
            cv2.putText(clock, clock_text(time.time_ns()), (15, 73), cv2.FONT_HERSHEY_SIMPLEX,
                        2.2, (255, 255, 255), 3, cv2.LINE_AA)
            cv2.imshow(CLOCK_WINDOW, clock)
            next_clock_update = now + NS_PER_SECOND // 120

        frame = latest[-1] if latest else None
        if frame is not None and frame.number != last_frame:
            cv2.imshow(PREVIEW_WINDOW, draw_frame(frame, recording.is_set()))
            last_frame = frame.number

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q"), 27):
            break
        if key in (ord("r"), ord("R")):
            if recording.is_set():
                recording.clear()
                print("Recording stopped. Finishing queued images.", flush=True)
            else:
                recording.set()
                print(f"Recording images to {frames_dir}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=1, help="camera index (default: 1)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=60, help="requested FPS, or 0 for camera default")
    parser.add_argument("--seconds", type=float, default=0, help="stop after this many capture seconds (0: manual)")
    parser.add_argument("--no-preview", action="store_true", help="measure delivery FPS without rendering windows")
    args = parser.parse_args()
    if min(args.camera, args.fps, args.seconds) < 0 or min(args.width, args.height) <= 0:
        parser.error("camera, FPS and duration must be nonnegative, and resolution must be positive")

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        camera.release()
        print(f"Could not open camera {args.camera}. Try --camera 0 or --camera 2.", file=sys.stderr)
        return 1

    try:
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        if args.fps:
            camera.set(cv2.CAP_PROP_FPS, args.fps)
        reported_fps = camera.get(cv2.CAP_PROP_FPS)
        print(f"Requested {args.width}x{args.height} at {args.fps or 'camera default'} FPS. "
              f"Camera reports {reported_fps:.1f} FPS.", flush=True)

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"frames_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
        frames_dir = log_path.with_suffix("")
        print(f"Timestamp log: {log_path}", flush=True)
        controls = "Press Ctrl+C to stop." if args.no_preview else "Press R to record frames, Q or Escape to quit."
        print(controls, flush=True)

        # Single producer, single reader. Replacing the slot prevents preview backlog.
        latest = deque(maxlen=1)
        stop = Event()
        recording = Event()
        frame_queue = Queue(maxsize=24)
        with ThreadPoolExecutor(max_workers=2) as executor:
            worker = executor.submit(capture_frames, camera, log_path, latest, stop, args.seconds, recording, frame_queue)
            frame_writer = executor.submit(save_frames, frame_queue, worker, frames_dir)
            try:
                if args.no_preview:
                    while not worker.done():
                        stop.wait(0.05)
                else:
                    show_preview(worker, frame_writer, latest, recording, frames_dir)
            except KeyboardInterrupt:
                pass
            finally:
                stop.set()
            saved = frame_writer.result()
            count, fps = worker.result()

        print(f"Logged {count} frames at {fps:.1f} average delivery FPS.")
        if saved:
            print(f"Saved {saved} JPEGs to {frames_dir}")
    except (OSError, RuntimeError, cv2.error) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        camera.release()
        if not args.no_preview:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
