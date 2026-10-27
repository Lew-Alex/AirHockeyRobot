import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from puck_tracker import save_recording_frame
from tracker import MaskSettings, crop_frame, detect_puck


class TrackerTests(unittest.TestCase):
    def test_crops_using_top_left_and_bottom_right(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        settings = MaskSettings(
            crop_left_x=20,
            crop_top_y=10,
            crop_right_x=170,
            crop_bottom_y=80,
        )

        cropped, bounds = crop_frame(frame, settings)

        self.assertEqual(bounds, (20, 10, 170, 80))
        self.assertEqual(cropped.shape[:2], (70, 150))

    def test_zero_right_and_bottom_use_full_frame(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)

        cropped, bounds = crop_frame(frame, MaskSettings())

        self.assertEqual(bounds, (0, 0, 200, 100))
        self.assertEqual(cropped.shape[:2], (100, 200))

    def test_detects_yellow_circle(self) -> None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.circle(frame, (320, 240), 35, (0, 255, 255), -1)

        detection, mask = detect_puck(frame, MaskSettings())

        self.assertIsNotNone(detection)
        assert detection is not None
        self.assertLessEqual(abs(detection.center[0] - 320), 2)
        self.assertLessEqual(abs(detection.center[1] - 240), 2)
        self.assertGreater(cv2.countNonZero(mask), 0)

    def test_rejects_red_circle(self) -> None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.circle(frame, (320, 240), 35, (0, 0, 255), -1)

        detection, _ = detect_puck(frame, MaskSettings())

        self.assertIsNone(detection)

    def test_saves_matching_rgb_and_mask_frames(self) -> None:
        frame = np.zeros((40, 60, 3), dtype=np.uint8)
        mask = np.zeros((40, 60), dtype=np.uint8)
        with TemporaryDirectory() as temporary_directory:
            recording_dir = Path(temporary_directory)
            (recording_dir / "rgb").mkdir()
            (recording_dir / "mask").mkdir()

            save_recording_frame(recording_dir, 7, frame, mask)

            self.assertTrue((recording_dir / "rgb" / "frame_000007.jpg").is_file())
            self.assertTrue((recording_dir / "mask" / "frame_000007.png").is_file())


if __name__ == "__main__":
    unittest.main()
