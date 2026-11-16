"""Receiver diagnostics checks; no camera, socket, GUI or Android build required."""

import unittest
from unittest.mock import patch

from view_puck_stream import StreamStats


class StreamDiagnosticsTests(unittest.TestCase):
    def test_camera_processing_and_receiver_rates_remain_distinct(self):
        stats = StreamStats()
        stats.started = 10.0
        for frame in range(22):
            stats.add({"frame_id": frame, "detected": False, "capture_fps": 60.0,
                       "source_fps": 21.0, "analysis_fps": 21.0,
                       "tracker": "gpu_mask_experimental", "pipeline_revision": 2,
                       "acquire_ms": 1.0, "mask_readback_ms": 8.0, "detection_ms": 2.0,
                       "previous_preview_ms": 35.0, "previous_frame_work_ms": 48.0,
                       "preview_enabled": True}, arrival=10.0+frame/21.0)
        report = stats.snapshot(now=11.0)
        self.assertEqual(report["reported_phone_rates_fps"]["capture_fps"]["mean"], 60.0)
        self.assertEqual(report["reported_phone_rates_fps"]["analysis_fps"]["mean"], 21.0)
        self.assertEqual(report["pipeline_stage_ms"]["previous_preview_ms"]["p95"], 35.0)
        self.assertEqual(report["latest_pipeline"]["pipeline_revision"], 2)
        self.assertEqual(stats.live_received_rate(now=11.0), 21.0)

    def test_live_gui_rate_does_not_compute_full_report_and_expires(self):
        stats = StreamStats(window_seconds=1.0)
        stats.add({"detected": False}, arrival=20.0)
        stats.add({"detected": False}, arrival=20.5)
        with patch.object(stats, "snapshot", side_effect=AssertionError("expensive full report")):
            self.assertEqual(stats.live_received_rate(now=20.5), 2.0)
            self.assertEqual(stats.live_received_rate(now=22.0), 0.0)

    def test_old_packets_and_nonfinite_stage_values(self):
        stats = StreamStats()
        stats.add({"detected": False, "acquire_ms": float("nan"), "detection_ms": -1})
        report = stats.snapshot()
        self.assertIsNone(report["latest_pipeline"]["pipeline_revision"])
        self.assertEqual(report["pipeline_stage_ms"]["acquire_ms"], {"mean": None, "p95": None})
        self.assertEqual(report["pipeline_stage_ms"]["detection_ms"], {"mean": None, "p95": None})


if __name__ == "__main__":
    unittest.main()
