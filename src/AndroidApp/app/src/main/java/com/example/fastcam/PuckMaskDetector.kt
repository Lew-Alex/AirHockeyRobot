package com.example.fastcam

import java.nio.ByteBuffer
import kotlin.math.PI
import kotlin.math.hypot
import kotlin.math.sqrt

/** Experimental connected-component detector for the GPU's binary yellow mask.
 * No Android or Python dependency. Input rows are GL bottom-up; results are top-left.
 * This is a separate detector, not a claim of equivalence to the Python reference.
 */
class PuckMaskDetector(private val width: Int, private val height: Int) {
    data class Hit(val x: Double, val y: Double, val radius: Double, val circularity: Double)
    private val visited = BooleanArray(width * height)
    private val queue = IntArray(width * height)
    private var previous: Hit? = null
    private var previousNs = 0L
    private var lastFrameNs = 0L
    private var vx = 0.0
    private var vy = 0.0

    init { require(width > 0 && height > 0) }

    fun detect(rgba: ByteBuffer, timestampNs: Long): Hit? {
        require(rgba.capacity() >= width * height * 4)
        if (timestampNs <= lastFrameNs) return null
        lastFrameNs = timestampNs
        visited.fill(false)
        val elapsed = (timestampNs - previousNs) / 1e9
        val old = previous?.takeIf { elapsed in 0.0..0.15 }
        val predictedX = (old?.x ?: 0.0) + vx * elapsed
        val predictedY = (old?.y ?: 0.0) + vy * elapsed
        // At least 12% of the image diagonal: permit bounces and rapid direction changes.
        val gate = hypot(width.toDouble(), height.toDouble()) * minOf(1.0, 0.12 + 5.0 * elapsed)
        var best: Hit? = null
        var bestScore = Double.NEGATIVE_INFINITY
        fun yellow(index: Int) = rgba.get(index * 4).toInt() != 0
        for (seed in visited.indices) {
            if (visited[seed] || !yellow(seed)) continue
            var head = 0
            var tail = 1
            queue[0] = seed
            visited[seed] = true
            var sumX = 0.0
            var sumY = 0.0
            var perimeter = 0
            while (head < tail) {
                val index = queue[head++]
                val x = index % width
                val y = index / width
                sumX += x
                sumY += height - 1 - y
                fun visit(neighbor: Int, valid: Boolean) {
                    if (!valid || !yellow(neighbor)) { perimeter++; return }
                    if (!visited[neighbor]) {
                        visited[neighbor] = true
                        queue[tail++] = neighbor
                    }
                }
                visit(index - 1, x > 0)
                visit(index + 1, x + 1 < width)
                visit(index - width, y > 0)
                visit(index + width, y + 1 < height)
            }
            if (tail < 3 || tail > width * height * 0.025 || perimeter == 0) continue
            val circularity = 4.0 * PI * tail / (perimeter.toDouble() * perimeter)
            if (circularity < 0.22) continue
            val hit = Hit(sumX / tail, sumY / tail, sqrt(tail / PI), circularity)
            val distance = hypot(hit.x - predictedX, hit.y - predictedY)
            if (old != null && distance > gate) continue
            val score = if (old == null) tail * circularity else -distance
            if (score > bestScore) { best = hit; bestScore = score }
        }
        if (best != null) {
            if (old != null && elapsed > 0.0) {
                // Used for candidate selection only: published positions are always measured.
                vx = (best.x - old.x) / elapsed
                vy = (best.y - old.y) / elapsed
            } else { vx = 0.0; vy = 0.0 }
            previous = best
            previousNs = timestampNs
        }
        return best
    }
}
