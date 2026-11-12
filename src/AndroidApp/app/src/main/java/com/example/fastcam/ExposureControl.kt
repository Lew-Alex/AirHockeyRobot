package com.example.fastcam

import kotlin.math.ln
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/** Pure mapping between a manual-shutter slider and Camera2 exposure time in nanoseconds. */
object ExposureControl {
    const val AUTO_PROGRESS = 0
    const val MANUAL_PROGRESS_MIN = 1
    const val MANUAL_PROGRESS_MAX = 1000
    private const val NANOS_PER_SECOND = 1_000_000_000L

    /**
     * Progress 0 selects auto exposure. Progress 1 is the longest legal exposure and
     * progress 1000 is the shortest. Manual values are spaced logarithmically (by stops).
     * Returns null when the sensor/frame-duration constraints have no valid intersection.
     */
    fun exposureForProgress(
        progress: Int,
        minNs: Long,
        maxNs: Long,
        frameDurationNs: Long
    ): Long? {
        if (progress <= AUTO_PROGRESS) return null
        val range = legalRange(minNs, maxNs, frameDurationNs) ?: return null
        val p = progress.coerceIn(MANUAL_PROGRESS_MIN, MANUAL_PROGRESS_MAX)
        if (range.first == range.second) return range.first

        val fraction = (p - MANUAL_PROGRESS_MIN).toDouble() /
            (MANUAL_PROGRESS_MAX - MANUAL_PROGRESS_MIN).toDouble()
        val exposure = range.second.toDouble() *
            (range.first.toDouble() / range.second.toDouble()).pow(fraction)
        return exposure.roundToLong().coerceIn(range.first, range.second)
    }

    /** Returns slider progress for an exposure; null exposure represents auto (position 0). */
    fun progressForExposure(
        exposureNs: Long?,
        minNs: Long,
        maxNs: Long,
        frameDurationNs: Long
    ): Int? {
        if (exposureNs == null) return AUTO_PROGRESS
        val range = legalRange(minNs, maxNs, frameDurationNs) ?: return null
        if (range.first == range.second) return MANUAL_PROGRESS_MIN
        val exposure = exposureNs.coerceIn(range.first, range.second).toDouble()
        val fraction = ln(exposure / range.second.toDouble()) /
            ln(range.first.toDouble() / range.second.toDouble())
        return (MANUAL_PROGRESS_MIN + fraction *
            (MANUAL_PROGRESS_MAX - MANUAL_PROGRESS_MIN)).roundToInt()
            .coerceIn(MANUAL_PROGRESS_MIN, MANUAL_PROGRESS_MAX)
    }

    /** Labels nanoseconds directly and includes the familiar reciprocal shutter speed. */
    fun labelForExposureNs(exposureNs: Long?): String = when {
        exposureNs == null -> "Auto"
        exposureNs <= 0L -> "Unavailable"
        else -> {
            val reciprocal = NANOS_PER_SECOND.toDouble() / exposureNs.toDouble()
            val shutter = if (reciprocal >= 1.0) "1/${reciprocal.roundToInt()} s" else "${exposureNs} ns"
            "$exposureNs ns ($shutter)"
        }
    }

    private fun legalRange(minNs: Long, maxNs: Long, frameDurationNs: Long): Pair<Long, Long>? {
        if (minNs <= 0L || maxNs < minNs || frameDurationNs <= 0L) return null
        val cappedMax = minOf(maxNs, frameDurationNs)
        if (cappedMax < minNs) return null
        return minNs to cappedMax
    }

    private fun Double.pow(power: Double): Double = Math.pow(this, power)
}
