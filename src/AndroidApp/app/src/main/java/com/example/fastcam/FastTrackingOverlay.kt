package com.example.fastcam

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.SystemClock
import android.util.AttributeSet
import android.view.View

/** Small native-axis position monitor, independent of camera preview refresh. */
class FastTrackingOverlay(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var sample: FastPuckPipeline.Sample? = null
    private var receivedAt = 0L
    private val expire = Runnable { sample = null; invalidate() }
    fun show(value: FastPuckPipeline.Sample) {
        sample = value
        receivedAt = SystemClock.uptimeMillis()
        removeCallbacks(expire)
        postDelayed(expire, 250)
        invalidate()
    }
    fun clear() { sample = null; removeCallbacks(expire); invalidate() }
    override fun onDraw(canvas: Canvas) {
        val d = resources.displayMetrics.density
        paint.style = Paint.Style.FILL
        paint.color = 0xEE17354A.toInt()
        canvas.drawRoundRect(0f, 0f, width.toFloat(), height.toFloat(), 8*d, 8*d, paint)
        val s = sample?.takeIf { SystemClock.uptimeMillis() - receivedAt < 250 }
        paint.color = Color.WHITE
        paint.textSize = 11*d
        canvas.drawText(if (s?.previewEnabled == false) "Puck position · camera paused" else "Live puck position", 8*d, 16*d, paint)
        canvas.drawText(s?.let { "%.1f updates/s on phone".format(it.analysisFps) } ?: "Waiting for fresh frames", 8*d, 33*d, paint)
        canvas.drawText(s?.let { "%.1f ms processing".format(it.processingMs) } ?: "", 8*d, 49*d, paint)
        val left = 8*d
        val top = 59*d
        val right = width - 8*d
        val bottom = height - 23*d
        paint.style = Paint.Style.STROKE
        paint.color = Color.LTGRAY
        canvas.drawRect(left, top, right, bottom, paint)
        paint.style = Paint.Style.FILL
        if (s?.x != null && s.y != null) {
            paint.color = Color.GREEN
            canvas.drawCircle(left + (s.xNormalized!! * (right-left)).toFloat(), top + (s.yNormalized!! * (bottom-top)).toFloat(), 4*d, paint)
        }
        paint.color = Color.WHITE
        val label = if (s?.x != null && s.y != null) "X %.1f  Y %.1f px".format(s.x, s.y) else "Puck lost / stale"
        canvas.drawText(label, 8*d, height - 7*d, paint)
    }
}
