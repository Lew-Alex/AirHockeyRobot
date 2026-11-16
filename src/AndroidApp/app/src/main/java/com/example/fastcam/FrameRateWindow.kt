package com.example.fastcam

/** Bounded sliding one-second window, measured against monotonic *arrival* time.
 * Unlike 1 / capture-timestamp delta, this reveals skipped frames and stalls.
 */
class FrameRateWindow {
    private val arrivals = ArrayDeque<Long>()
    fun clear() { arrivals.clear() }
    fun add(nowNs: Long) { arrivals.addLast(nowNs); trim(nowNs) }
    private fun trim(nowNs: Long) {
        while (arrivals.isNotEmpty() && nowNs - arrivals.first() > 1_000_000_000L) arrivals.removeFirst()
        while (arrivals.size > 4096) arrivals.removeFirst()
    }
    fun rate(nowNs: Long): Double {
        trim(nowNs)
        if (arrivals.size < 2) return 0.0
        val duration = nowNs - arrivals.first()
        return if (duration > 0) (arrivals.size - 1) * 1e9 / duration else 0.0
    }
}
