"""Receiver diagnostics checks; no camera, socket, GUI or Android build required."""

import unittest
import json
import threading
from unittest.mock import patch

from view_puck_stream import StreamStats
import view_puck_stream as viewer


class StreamDiagnosticsTests(unittest.TestCase):
    def test_clock_reply_is_excluded_and_end_to_end_ages_use_synced_clocks(self):
        class Connection:
            def __init__(self): self.packet = b""
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def settimeout(self,*args): pass
            def sendall(self,data):
                probe_id = data.decode().split()[1]
                reply = {"type":"clock_sync", "id":probe_id, "clock":"elapsed_realtime",
                         "phone_receive_ns":1125000000, "phone_send_ns":1130000000}
                puck = {"type":"puck", "detected":True, "x":1, "y":2, "timestamp_ns":1140000000,
                        "phone_publish_timestamp_ns":1150000000, "capture_timestamp_ns":1130000000,
                        "timestamp_source":"REALTIME"}
                self.packet = (json.dumps(reply)+"\n"+json.dumps(puck)+"\n").encode()
            def recv(self,*args):
                data,self.packet = self.packet,b""
                return data
        stats, stop, errors = StreamStats(),threading.Event(),[]
        stats.started = 1.0
        with patch.object(viewer.socket,"create_connection",return_value=Connection()), \
                patch.object(viewer.time,"monotonic_ns",side_effect=[1000000000,1055000000,1060000000]):
            viewer.receive("localhost",8765,stats,stop,errors,latency=True)
        result = stats.snapshot(now=1.06)
        self.assertEqual(result["received_messages"],1)
        self.assertEqual(result["detected_messages"],1)
        self.assertEqual(result["estimated_latency_ms"]["sensor_to_receiver_ms"]["mean"],25.0)
        self.assertEqual(result["estimated_latency_ms"]["sample_to_receiver_ms"]["mean"],15.0)
        self.assertEqual(result["estimated_latency_ms"]["publish_to_receiver_ms"]["mean"],5.0)
        self.assertEqual(result["clock_sync"]["offset_uncertainty_ms"],25.0)

    def test_counter_advance_can_exceed_received_message_rate(self):
        stats = StreamStats()
        stats.started = 10.0
        for frame in range(22):
            stats.add({"frame_id":frame*3,"detected":False},arrival=10+frame/21)
        report = stats.snapshot(now=11.0)
        self.assertEqual(report["received_cadence_hz"],21.0)
        self.assertEqual(report["frame_id_advance_rate_hz"],63.0)
        self.assertEqual(report["estimated_missing_frame_ids"],42)

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
