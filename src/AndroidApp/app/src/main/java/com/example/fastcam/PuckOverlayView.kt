package com.example.fastcam

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.SystemClock
import android.util.AttributeSet
import android.view.View

/** Coordinates belong to the already rotated preview, not the camera sensor. */
class PuckOverlayView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.GREEN
        style = Paint.Style.STROKE
        strokeWidth = 3f * resources.displayMetrics.density
    }
    private var circle: FloatArray? = null
    private var updatedAt = 0L
    private val expire = Runnable { clear() }

    fun show(x: Double, y: Double, radiusX: Double, radiusY: Double) {
        circle = floatArrayOf(x.toFloat(), y.toFloat(), radiusX.toFloat(), radiusY.toFloat())
        updatedAt = SystemClock.uptimeMillis()
        removeCallbacks(expire)
        postDelayed(expire, 250)
        invalidate()
    }

    fun clear() {
        circle = null
        removeCallbacks(expire)
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val c = circle ?: return
        if (SystemClock.uptimeMillis() - updatedAt > 250) return
        val x = c[0] * width
        val y = c[1] * height
        val radius = maxOf(c[2] * width, c[3] * height) + 5f * resources.displayMetrics.density
        canvas.drawCircle(x, y, radius, paint)
        canvas.drawLine(x - 6, y, x + 6, y, paint)
        canvas.drawLine(x, y - 6, x, y + 6, paint)
    }
}
