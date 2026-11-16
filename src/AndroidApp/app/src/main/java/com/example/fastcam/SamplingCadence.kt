package com.example.fastcam

/**
 * Claims preview samples at a bounded cadence while keeping the schedule anchored to
 * the first accepted timestamp. Small early jitter is tolerated without accumulating
 * drift; after a stall, missed slots are skipped instead of replayed.
 */
class SamplingCadence(
    private val intervalNs: Long = 33_333_333L,
    private val toleranceNs: Long = 1_000_000L
) {
    private var nextDeadlineNs: Long? = null
    private var lastObservedNs: Long? = null

    init {
        require(intervalNs > 0L) { "intervalNs must be positive" }
        require(toleranceNs >= 0L && toleranceNs < intervalNs) {
            "toleranceNs must be nonnegative and shorter than intervalNs"
        }
    }

    /** Returns true once for an eligible timestamp. A clock regression reanchors cadence. */
    fun tryClaim(nowNs: Long): Boolean {
        val previous = lastObservedNs
        if (previous != null && nowNs < previous) {
            // Monotonic clocks should not regress, but a reset must not strand sampling
            // behind an old deadline. The regressed callback becomes the new anchor.
            lastObservedNs = nowNs
            nextDeadlineNs = nowNs + intervalNs
            return true
        }
        lastObservedNs = nowNs

        val deadline = nextDeadlineNs
        if (deadline == null) {
            nextDeadlineNs = nowNs + intervalNs
            return true
        }
        if (nowNs < deadline - toleranceNs) return false

        // Advance by whole intervals from the anchored deadline. One arithmetic jump
        // skips missed slots after a stall, without a catch-up loop.
        val periods = if (nowNs >= deadline) (nowNs - deadline) / intervalNs + 1L else 1L
        nextDeadlineNs = deadline + periods * intervalNs
        return true
    }

    fun reset() {
        nextDeadlineNs = null
        lastObservedNs = null
    }
}
