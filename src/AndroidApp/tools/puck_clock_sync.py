"""Estimate phone-to-receiver monotonic clock offset over the puck TCP connection.

The probe request is ASCII ``CLOCK_SYNC <id>\n``. A compatible server replies with
one JSON line containing ``type``, ``id``, ``clock``, ``phone_receive_ns`` and
``phone_send_ns``. Only ``clock == "elapsed_realtime"`` is comparable with Android
elapsed-realtime frame timestamps.
"""

import json
import uuid
from collections import OrderedDict, deque


class ClockSync:
    """Bounded four-timestamp clock sync using minimum-RTT samples.

    ``offset_ns`` is phone clock minus receiver clock. The reported offset
    uncertainty is half the corrected path round trip and assumes a symmetric path.
    """

    MAX_PROBES = 32
    MAX_PENDING = 8
    PROBE_TTL_NS = 10_000_000_000
    SAMPLE_TTL_NS = 30_000_000_000

    def __init__(self):
        self._pending = OrderedDict()
        self._samples = deque(maxlen=self.MAX_PROBES)
        self._last_probe_now_ns = None
        self._last_receive_ns = None

    @staticmethod
    def _integer(value):
        # JSON integer timestamps retain nanosecond precision. Reject bool, float,
        # strings, NaN and infinity rather than silently rounding clock values.
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def _expire(self, now_ns):
        for probe_id, sent_ns in list(self._pending.items()):
            if now_ns >= sent_ns and now_ns - sent_ns > self.PROBE_TTL_NS:
                del self._pending[probe_id]

    def _reset_for_clock_regression(self, now_ns, event):
        attribute = "_last_probe_now_ns" if event == "probe" else "_last_receive_ns"
        previous = getattr(self, attribute)
        regressed = previous is not None and now_ns < previous
        if regressed:
            # A monotonic clock reset invalidates both pending probes and the old
            # offset baseline. Do not combine samples from unrelated clock epochs.
            self._pending.clear()
            self._samples.clear()
        setattr(self, attribute, now_ns)
        return regressed

    def start_probe(self, now_ns):
        """Return ``(id, request_bytes)`` for a probe sent at receiver time ``now_ns``."""
        now_ns = self._integer(now_ns)
        if now_ns is None:
            raise ValueError("now_ns must be a nonnegative integer")
        self._reset_for_clock_regression(now_ns, "probe")
        self._expire(now_ns)
        while len(self._pending) >= self.MAX_PENDING:
            self._pending.popitem(last=False)
        probe_id = uuid.uuid4().hex
        self._pending[probe_id] = now_ns
        return probe_id, ("CLOCK_SYNC {}\n".format(probe_id)).encode("ascii")

    @staticmethod
    def _decode(packet):
        if isinstance(packet, dict):
            return packet
        if isinstance(packet, bytes):
            try:
                packet = packet.decode("utf-8")
            except UnicodeError:
                return None
        if not isinstance(packet, str):
            return None
        try:
            decoded = json.loads(packet)
        except (json.JSONDecodeError, UnicodeError):
            return None
        return decoded if isinstance(decoded, dict) else None

    def accept_reply(self, packet, receive_ns):
        """Accept one matching reply, returning false for stale or invalid packets."""
        receive_ns = self._integer(receive_ns)
        if receive_ns is None:
            return False
        reply = self._decode(packet)
        if reply is None or reply.get("type") != "clock_sync":
            return False
        probe_id = reply.get("id")
        if not isinstance(probe_id, str) or probe_id not in self._pending:
            return False

        sent_ns = self._pending.pop(probe_id)
        if self._reset_for_clock_regression(receive_ns, "receive"):
            return False
        self._expire(receive_ns)
        if receive_ns < sent_ns or receive_ns - sent_ns > self.PROBE_TTL_NS:
            return False
        # Android elapsed realtime is required because frame timestamps are from
        # that clock. The pure JVM server uses a different clock and is diagnostic only.
        if reply.get("clock") != "elapsed_realtime":
            return False

        phone_receive_ns = self._integer(reply.get("phone_receive_ns"))
        phone_send_ns = self._integer(reply.get("phone_send_ns"))
        if phone_receive_ns is None or phone_send_ns is None:
            return False
        if phone_send_ns < phone_receive_ns:
            return False

        phone_work_ns = phone_send_ns - phone_receive_ns
        raw_rtt_ns = receive_ns - sent_ns
        if raw_rtt_ns < phone_work_ns:
            return False
        path_rtt_ns = raw_rtt_ns - phone_work_ns
        # Store twice the offset to preserve half-nanosecond estimates without
        # converting large monotonic timestamps through floating point.
        offset_twice_ns = (phone_receive_ns - sent_ns) + (phone_send_ns - receive_ns)
        self._samples.append({"offset_twice_ns": offset_twice_ns,
                              "path_rtt_ns": path_rtt_ns,
                              "received_ns": receive_ns})
        return True

    def _fresh_samples(self, now_ns=None):
        if now_ns is None:
            return list(self._samples)
        now_ns = self._integer(now_ns)
        if now_ns is None:
            return []
        return [sample for sample in self._samples
                if sample["received_ns"] <= now_ns
                and now_ns - sample["received_ns"] <= self.SAMPLE_TTL_NS]

    def _best(self, now_ns=None):
        samples = self._fresh_samples(now_ns)
        return min(samples, key=lambda sample: sample["path_rtt_ns"]) if samples else None

    def summary(self, now_ns=None):
        """Return the best sample; ``now_ns`` filters stale and future samples."""
        samples = self._fresh_samples(now_ns)
        best = min(samples, key=lambda sample: sample["path_rtt_ns"]) if samples else None
        if best is None:
            return {
                "synchronized": False,
                "clock": "elapsed_realtime",
                "offset_ns": None,
                "round_trip_ms": None,
                "offset_uncertainty_ms": None,
                "sample_count": len(samples),
                "assumption": "symmetric network path; uncertainty is corrected RTT/2",
            }
        rtt_ns = best["path_rtt_ns"]
        return {
            "synchronized": True,
            "clock": "elapsed_realtime",
            "offset_ns": best["offset_twice_ns"] / 2.0,
            "round_trip_ms": rtt_ns / 1_000_000.0,
            "offset_uncertainty_ms": rtt_ns / 2_000_000.0,
            "sample_count": len(samples),
            "assumption": "symmetric network path; uncertainty is corrected RTT/2",
        }

    def age_ms(self, phone_timestamp_ns, receiver_now_ns):
        """Convert a phone elapsed-realtime timestamp to receiver age in milliseconds.

        Returns ``None`` until synchronized, for invalid inputs, or for negative age.
        A negative estimate within offset uncertainty cannot be distinguished from
        clock error, so it is omitted rather than clamped to zero.
        """
        phone_timestamp_ns = self._integer(phone_timestamp_ns)
        receiver_now_ns = self._integer(receiver_now_ns)
        best = self._best(receiver_now_ns)
        if phone_timestamp_ns is None or receiver_now_ns is None or best is None:
            return None
        # Twice-nanosecond math keeps the offset exact until the final ms conversion.
        age_twice_ns = 2 * receiver_now_ns - (2 * phone_timestamp_ns - best["offset_twice_ns"])
        if age_twice_ns < 0:
            return None
        return age_twice_ns / 2_000_000.0
