package com.example.fastcam

import kotlin.math.abs

/** Native image coordinates normalized to [0,1]; radius is relative to the shorter image edge. */
data class RecordedPuckFrame(val timeUs: Long, val x: Double?, val y: Double?, val radius: Double?)

/** Match actual decoded-frame timestamps; never hold a previous ring over a lost/new frame. */
class RecordedPuckTimeline(private val frames: List<RecordedPuckFrame>) {
    init {
        require(frames.zipWithNext().all { (a, b) -> a.timeUs <= b.timeUs }) { "Frames must be ordered" }
    }

    fun at(timeUs: Long, toleranceUs: Long = 1_000): RecordedPuckFrame? {
        require(toleranceUs >= 0)
        if (frames.isEmpty() || timeUs < 0) return null
        var low = 0
        var high = frames.size
        while (low < high) {
            val mid = (low + high) ushr 1
            if (frames[mid].timeUs < timeUs) low = mid + 1 else high = mid
        }
        val next = frames.getOrNull(low)
        val previous = frames.getOrNull(low - 1)
        val nearest = when {
            next == null -> previous
            previous == null -> next
            abs(next.timeUs - timeUs) < abs(previous.timeUs - timeUs) -> next
            else -> previous
        } ?: return null
        if (abs(nearest.timeUs - timeUs) > toleranceUs) return null
        return nearest.takeIf { it.x != null && it.y != null && it.radius != null }
    }
}
