#!/usr/bin/env python3
"""Live webcam prototype for tracking a yellow air-hockey puck."""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path

import cv2

from tracker import MaskSettings, crop_frame, detect_puck


SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = SCRIPT_DIR / "settings.json"
RECORDINGS_DIR = SCRIPT_DIR / "recordings"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0, help="camera index (default: 0)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=60)
    return parser.parse_args()


def load_settings() -> MaskSettings:
    if not SETTINGS_PATH.exists():
        return MaskSettings()
    try:
        return MaskSettings(**json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Ignoring invalid {SETTINGS_PATH.name}: {exc}")
        return MaskSettings()


def nothing(_: int) -> None:
    pass


def create_controls(settings: MaskSettings, frame_width: int, frame_height: int) -> None:
    cv2.namedWindow("Controls", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Controls", 520, 560)
    right_x = settings.crop_right_x or frame_width
    bottom_y = settings.crop_bottom_y or frame_height
    controls = {
        "Lower H": (settings.lower_h, 179),
        "Lower S": (settings.lower_s, 255),
        "Lower V": (settings.lower_v, 255),
        "Upper H": (settings.upper_h, 179),
        "Upper S": (settings.upper_s, 255),
        "Upper V": (settings.upper_v, 255),
        "Min area": (int(settings.min_area), 20_000),
        "Max area / 10": (int(settings.max_area / 10), 20_000),
        "Circularity %": (int(settings.min_circularity * 100), 100),
        "Kernel": (settings.kernel_size, 21),
        "Crop left X": (min(settings.crop_left_x, frame_width - 1), frame_width - 1),
        "Crop top Y": (min(settings.crop_top_y, frame_height - 1), frame_height - 1),
        "Crop right X": (min(right_x, frame_width), frame_width),
        "Crop bottom Y": (min(bottom_y, frame_height), frame_height),
    }
    for name, (value, maximum) in controls.items():
        cv2.createTrackbar(name, "Controls", value, maximum, nothing)


def read_controls() -> MaskSettings:
    lower_h = cv2.getTrackbarPos("Lower H", "Controls")
    upper_h = max(lower_h, cv2.getTrackbarPos("Upper H", "Controls"))
    lower_s = cv2.getTrackbarPos("Lower S", "Controls")
    upper_s = max(lower_s, cv2.getTrackbarPos("Upper S", "Controls"))
    lower_v = cv2.getTrackbarPos("Lower V", "Controls")
    upper_v = max(lower_v, cv2.getTrackbarPos("Upper V", "Controls"))
    min_area = float(max(1, cv2.getTrackbarPos("Min area", "Controls")))
    max_area = float(max(min_area, cv2.getTrackbarPos("Max area / 10", "Controls") * 10))
    circularity = cv2.getTrackbarPos("Circularity %", "Controls") / 100.0
    kernel = max(1, cv2.getTrackbarPos("Kernel", "Controls"))
    return MaskSettings(
        lower_h=lower_h,
        lower_s=lower_s,
        lower_v=lower_v,
        upper_h=upper_h,
        upper_s=upper_s,
        upper_v=upper_v,
        min_area=min_area,
        max_area=max_area,
        min_circularity=circularity,
        kernel_size=kernel,
        crop_left_x=cv2.getTrackbarPos("Crop left X", "Controls"),
        crop_top_y=cv2.getTrackbarPos("Crop top Y", "Controls"),
        crop_right_x=cv2.getTrackbarPos("Crop right X", "Controls"),
        crop_bottom_y=cv2.getTrackbarPos("Crop bottom Y", "Controls"),
    )


def open_camera(args: argparse.Namespace) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(args.camera)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    if not capture.isOpened():
        raise RuntimeError(
            f"Could not open camera {args.camera}. Try --camera 1 and allow camera access."
        )
    return capture


def new_recording_folder() -> Path:
    """Create a unique timestamped folder for synchronized RGB and mask frames."""
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    recording_dir = RECORDINGS_DIR / timestamp
    suffix = 2
    while recording_dir.exists():
        recording_dir = RECORDINGS_DIR / f"{timestamp}_{suffix}"
        suffix += 1
    (recording_dir / "rgb").mkdir(parents=True)
    (recording_dir / "mask").mkdir()
    return recording_dir


def save_recording_frame(
    recording_dir: Path, frame_number: int, rgb_frame, mask
) -> None:
    """Save one pair using the same frame number in both subfolders."""
    filename = f"frame_{frame_number:06d}"
    rgb_ok = cv2.imwrite(str(recording_dir / "rgb" / f"{filename}.jpg"), rgb_frame)
    mask_ok = cv2.imwrite(str(recording_dir / "mask" / f"{filename}.png"), mask)
    if not rgb_ok or not mask_ok:
        raise OSError(f"Could not save recording frame {frame_number}")


def main() -> int:
    args = parse_args()
    settings = load_settings()

    try:
        capture = open_camera(args)
    except RuntimeError as exc:
        print(exc)
        cv2.destroyAllWindows()
        return 1

    ok, probe_frame = capture.read()
    if not ok:
        print("Camera opened, but the first frame could not be read.")
        capture.release()
        return 1
    frame_height, frame_width = probe_frame.shape[:2]
    create_controls(settings, frame_width, frame_height)

    trail: deque[tuple[int, int]] = deque(maxlen=30)
    previous_center: tuple[float, float] | None = None
    previous_crop: tuple[int, int, int, int] | None = None
    last_time = time.perf_counter()
    smoothed_fps = 0.0
    recording_dir: Path | None = None
    recording_frame_count = 0

    print("Controls: q/ESC quit, s save settings, c clear track, r start/stop recording")
    try:
        while True:
            frame = probe_frame
            probe_frame = None

            settings = read_controls()
            cropped_frame, crop_bounds = crop_frame(frame, settings)
            clean_rgb_frame = cropped_frame.copy()
            if crop_bounds != previous_crop:
                previous_center = None
                trail.clear()
                previous_crop = crop_bounds

            detection, mask = detect_puck(cropped_frame, settings, previous_center)

            if detection is not None:
                previous_center = detection.center
                trail.appendleft(detection.center)
                cv2.drawContours(cropped_frame, [detection.contour], -1, (0, 255, 0), 2)
                cv2.circle(cropped_frame, detection.center, max(2, int(detection.radius)), (0, 255, 0), 2)
                cv2.circle(cropped_frame, detection.center, 4, (0, 0, 255), -1)
                cv2.putText(
                    cropped_frame,
                    f"puck {detection.center} area={detection.area:.0f} circ={detection.circularity:.2f}",
                    (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
            else:
                cv2.putText(
                    cropped_frame,
                    "puck not detected",
                    (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )

            for index in range(1, len(trail)):
                thickness = max(1, int(4 * (1 - index / len(trail))))
                cv2.line(cropped_frame, trail[index - 1], trail[index], (255, 255, 0), thickness)

            now = time.perf_counter()
            instant_fps = 1.0 / max(now - last_time, 1e-6)
            smoothed_fps = instant_fps if smoothed_fps == 0 else 0.9 * smoothed_fps + 0.1 * instant_fps
            last_time = now
            cv2.putText(
                cropped_frame,
                f"{smoothed_fps:.1f} FPS",
                (15, cropped_frame.shape[0] - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            left, top, right, bottom = crop_bounds
            cv2.putText(
                cropped_frame,
                f"crop ({left},{top})-({right},{bottom})",
                (15, 62),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            if recording_dir is not None:
                recording_frame_count += 1
                try:
                    save_recording_frame(
                        recording_dir, recording_frame_count, clean_rgb_frame, mask
                    )
                except OSError as exc:
                    print(exc)
                    print(f"Recording stopped after {recording_frame_count - 1} frames.")
                    recording_dir = None
                else:
                    cv2.circle(cropped_frame, (cropped_frame.shape[1] - 22, 22), 8, (0, 0, 255), -1)
                    cv2.putText(
                        cropped_frame,
                        f"REC {recording_frame_count}",
                        (cropped_frame.shape[1] - 145, 29),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 0, 255),
                        2,
                        cv2.LINE_AA,
                    )

            cv2.imshow("Puck tracker", cropped_frame)
            cv2.imshow("Yellow mask", mask)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                previous_center = None
                trail.clear()
            if key == ord("s"):
                SETTINGS_PATH.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
                print(f"Saved settings to {SETTINGS_PATH}")
            if key == ord("r"):
                if recording_dir is None:
                    recording_dir = new_recording_folder()
                    recording_frame_count = 0
                    print(f"Recording started: {recording_dir}")
                else:
                    print(
                        f"Recording saved: {recording_dir} "
                        f"({recording_frame_count} RGB/mask pairs)"
                    )
                    recording_dir = None

            ok, next_frame = capture.read()
            if not ok:
                print("Camera frame capture failed.")
                break
            probe_frame = next_frame
    finally:
        if recording_dir is not None:
            print(
                f"Recording saved: {recording_dir} "
                f"({recording_frame_count} RGB/mask pairs)"
            )
        capture.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
