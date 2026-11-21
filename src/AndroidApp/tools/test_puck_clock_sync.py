"""Standard-library checks for the receiver/phone clock synchronizer."""

import json
import unittest

from puck_clock_sync import ClockSync


class ClockSyncTests(unittest.TestCase):
    def reply(self, probe_id, **updates):
        packet = {
            "type": "clock_sync",
            "id": probe_id,
            "clock": "elapsed_realtime",
            "phone_receive_ns": 1_125_000_000,
            "phone_send_ns": 1_130_000_000,
        }
        packet.update(updates)
        return packet

    def test_four_timestamp_offset_rtt_and_age(self):
        clock = ClockSync()
        probe_id, request = clock.start_probe(1_000_000_000)
        self.assertEqual(request, ("CLOCK_SYNC {}\n".format(probe_id)).encode("ascii"))
        self.assertTrue(clock.accept_reply(self.reply(probe_id), 1_055_000_000))
        summary = clock.summary()
        self.assertTrue(summary["synchronized"])
        self.assertEqual(summary["offset_ns"], 100_000_000)
        self.assertEqual(summary["round_trip_ms"], 50.0)
        self.assertEqual(summary["offset_uncertainty_ms"], 25.0)
        # Phone timestamp 1.2s is receiver timestamp 1.1s; receiver now is 1.14s.
        self.assertAlmostEqual(clock.age_ms(1_200_000_000, 1_140_000_000), 40.0)
        self.assertIsNone(clock.age_ms(1_200_000_000, 1_050_000_000))

    def test_minimum_corrected_rtt_is_retained(self):
        clock = ClockSync()
        first, _ = clock.start_probe(1_000_000_000)
        second, _ = clock.start_probe(1_100_000_000)
        self.assertTrue(clock.accept_reply(self.reply(first), 1_080_000_000))
        low_rtt = self.reply(second, phone_receive_ns=1_225_000_000,
                             phone_send_ns=1_230_000_000)
        self.assertTrue(clock.accept_reply(low_rtt, 1_155_000_000))
        summary = clock.summary()
        self.assertEqual(summary["round_trip_ms"], 50.0)
        self.assertEqual(summary["offset_ns"], 100_000_000)
        self.assertEqual(summary["sample_count"], 2)

    def test_invalid_clock_timestamp_and_duplicate_replies_are_rejected(self):
        invalid_values = (True, -1, 1.5, float("nan"), float("inf"), "100")
        for field, value in (("phone_receive_ns", item) for item in invalid_values):
            with self.subTest(value=value):
                clock = ClockSync()
                probe_id, _ = clock.start_probe(1_000_000_000)
                self.assertFalse(clock.accept_reply(self.reply(probe_id, **{field: value}), 1_055_000_000))
                self.assertFalse(clock.summary()["synchronized"])

        clock = ClockSync()
        probe_id, _ = clock.start_probe(1_000_000_000)
        self.assertFalse(clock.accept_reply(self.reply(probe_id, phone_send_ns=1_124_999_999), 1_055_000_000))
        self.assertFalse(clock.accept_reply(self.reply(probe_id), 1_055_000_000))
        self.assertFalse(clock.accept_reply(self.reply("unknown"), 1_055_000_000))

    def test_default_server_clock_is_not_used_for_android_age(self):
        clock = ClockSync()
        probe_id, _ = clock.start_probe(1_000_000_000)
        reply = self.reply(probe_id, clock="monotonic")
        self.assertFalse(clock.accept_reply(json.dumps(reply).encode("utf-8"), 1_055_000_000))
        self.assertIsNone(clock.age_ms(1_200_000_000, 1_300_000_000))

    def test_expiry_pending_bound_and_clock_reset(self):
        clock = ClockSync()
        stale, _ = clock.start_probe(1_000_000_000)
        self.assertFalse(clock.accept_reply(self.reply(stale), 11_000_000_001))

        pending_ids = [clock.start_probe(20_000_000_000 + i)[0] for i in range(ClockSync.MAX_PENDING + 1)]
        self.assertFalse(clock.accept_reply(self.reply(pending_ids[0]), 20_000_000_010))
        self.assertTrue(clock.accept_reply(self.reply(pending_ids[-1]), 20_055_000_000))

        # A receiver monotonic-clock regression clears estimates from the old epoch.
        clock.start_probe(5)
        self.assertFalse(clock.summary()["synchronized"])

    def test_unmatched_and_malformed_packets_are_ignored(self):
        clock = ClockSync()
        probe_id, _ = clock.start_probe(1_000_000_000)
        self.assertFalse(clock.accept_reply(b"not json", 1_055_000_000))
        self.assertFalse(clock.accept_reply({"type": "puck", "id": probe_id}, 1_055_000_000))
        self.assertTrue(clock.accept_reply(json.dumps(self.reply(probe_id)), 1_055_000_000))

    def test_age_and_timed_summary_use_only_fresh_nonfuture_offsets(self):
        clock = ClockSync()
        old_probe, _ = clock.start_probe(1_000_000_000)
        old_reply = self.reply(old_probe, phone_receive_ns=1_110_000_000,
                               phone_send_ns=1_115_000_000)
        self.assertTrue(clock.accept_reply(old_reply, 1_025_000_000))

        recent_probe, _ = clock.start_probe(40_000_000_000)
        recent_reply = self.reply(recent_probe, phone_receive_ns=40_225_000_000,
                                  phone_send_ns=40_230_000_000)
        self.assertTrue(clock.accept_reply(recent_reply, 40_055_000_000))

        # The old lower-RTT sample has expired; both summary and age use the newer offset.
        timed = clock.summary(now_ns=41_000_000_000)
        self.assertEqual(timed["sample_count"], 1)
        self.assertEqual(timed["offset_ns"], 200_000_000)
        self.assertAlmostEqual(clock.age_ms(40_400_000_000, 40_250_000_000), 50.0)

        # A sample from the receiver's future must not be used for age or timed summary.
        self.assertIsNone(clock.age_ms(40_400_000_000, 40_054_000_000))
        self.assertFalse(clock.summary(now_ns=40_054_000_000)["synchronized"])
        # No-argument summaries retain their original unfiltered behavior.
        self.assertEqual(clock.summary()["sample_count"], 2)

    def test_nanosecond_arithmetic_remains_exact_above_float_integer_limit(self):
        clock = ClockSync()
        t0 = 9_007_199_254_741_000  # greater than 2**53
        probe_id, _ = clock.start_probe(t0)
        packet = {
            "type": "clock_sync",
            "id": probe_id,
            "clock": "elapsed_realtime",
            "phone_receive_ns": t0 + 126,
            "phone_send_ns": t0 + 131,
        }
        self.assertTrue(clock.accept_reply(packet, t0 + 55))
        summary = clock.summary(now_ns=t0 + 1_000_000)
        self.assertEqual(summary["offset_ns"], 101.0)
        self.assertEqual(summary["round_trip_ms"], 0.00005)
        self.assertEqual(clock.age_ms(t0 + 101 + 400_000, t0 + 1_000_000), 0.6)


if __name__ == "__main__":
    unittest.main()
