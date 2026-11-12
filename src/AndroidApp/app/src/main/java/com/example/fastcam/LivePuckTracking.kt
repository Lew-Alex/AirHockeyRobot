package com.example.fastcam

import android.content.Context
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.TextureView
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.roundToInt

/**
 * Reads only the existing preview: constrained high-speed sessions cannot accept a
 * third (ImageReader) output. One frame in flight; busy frames are dropped.
 * All entry points except the executor body run on the main thread.
 */
class LivePuckTracking(
    context: Context,
    private val preview: TextureView,
    private val overlay: PuckOverlayView,
    private val onFailure: () -> Unit,
    private val status: (String) -> Unit
) {
    companion object {
        const val MAX_ANALYSIS_EDGE = 1280
        const val SAMPLE_INTERVAL_NS = 33_333_333L // at most 30 preview samples/s
    }

    private val appContext = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { r -> Thread(r, "puck-python") }
    private val busy = AtomicBoolean(false)
    @Volatile private var generation = 0
    @Volatile private var active = false
    private var enabled = false
    private var resumed = false
    private var cameraReady = false
    private var closed = false
    private var sensorWidth = 1280
    private var sensorHeight = 720
    private var rotation = 90
    private var bitmap: Bitmap? = null
    private var pixels = IntArray(0)
    private var lastSampleNs = 0L
    private var sampleId = 0L
    // Accessed exclusively by the Python worker.
    private var tracker: PyObject? = null
    private var trackerGeneration = -1
    private var outputError: String? = null
    private val output = PuckCoordinateServer(onError = { error ->
        val epoch = generation
        main.post {
            if (active && epoch == generation) {
                outputError = error
                status("XY output error: $error")
            }
        }
    })

    fun configure(width: Int, height: Int, clockwiseRotation: Int) {
        sensorWidth = width
        sensorHeight = height
        rotation = clockwiseRotation
        invalidateRun()
    }

    fun setEnabled(value: Boolean) {
        enabled = value
        refresh()
    }

    fun setResumed(value: Boolean) {
        resumed = value
        refresh()
    }

    fun setCameraReady(value: Boolean) {
        if (cameraReady != value) {
            cameraReady = value
            invalidateRun()
        }
    }

    /** Invalidate a result captured before a mode/surface/lifecycle change. */
    fun invalidateRun() {
        generation++
        lastSampleNs = 0
        overlay.clear()
    }

    private fun refresh() {
        val next = enabled && resumed && !closed
        if (next != active) {
            active = next
            invalidateRun()
            if (next) {
                outputError = null
                output.start()
            } else output.stop()
        }
        status(if (active) "Starting Python tracker | TCP ${PuckCoordinateServer.DEFAULT_PORT}"
               else "Tracking off | XY output: TCP ${PuckCoordinateServer.DEFAULT_PORT}")
    }

    /** Called when a new TextureView frame arrives on the UI thread. */
    fun onPreviewFrame() {
        if (!active || !cameraReady || !preview.isAvailable || preview.width == 0 || preview.height == 0) return
        val now = SystemClock.elapsedRealtimeNanos()
        if (now - lastSampleNs < SAMPLE_INTERVAL_NS || !busy.compareAndSet(false, true)) return
        lastSampleNs = now
        val epoch = generation
        val frameId = ++sampleId
        val width = sensorWidth
        val height = sensorHeight
        val angle = rotation
        val (displayW, displayH) = PreviewCoordinates.displaySize(width, height, angle)
        val scale = minOf(1.0, MAX_ANALYSIS_EDGE.toDouble() / maxOf(displayW, displayH))
        val analysisW = (displayW * scale).roundToInt().coerceAtLeast(1)
        val analysisH = (displayH * scale).roundToInt().coerceAtLeast(1)
        try {
            // getBitmap includes TextureView's rotation transform. Reuse memory;
            // the busy gate guarantees the worker has finished reading the pixels.
            if (bitmap?.width != analysisW || bitmap?.height != analysisH) {
                bitmap?.recycle()
                bitmap = Bitmap.createBitmap(analysisW, analysisH, Bitmap.Config.ARGB_8888)
                pixels = IntArray(analysisW * analysisH)
            }
            val snapshot = preview.getBitmap(bitmap!!) ?: run { busy.set(false); return }
            val previewTimestamp = preview.surfaceTexture?.timestamp ?: 0L
            snapshot.getPixels(pixels, 0, analysisW, 0, 0, analysisW, analysisH)
            val framePixels = pixels
            worker.execute {
                try {
                    if (!active || epoch != generation) return@execute
                    // Activity recreation can briefly leave an older worker initializing.
                    synchronized(Python::class.java) {
                        if (!Python.isStarted()) Python.start(AndroidPlatform(appContext))
                    }
                    val pythonTracker = tracker ?: Python.getInstance().getModule("android_bridge")
                        .callAttr("AndroidTracker").also { tracker = it }
                    if (trackerGeneration != epoch) {
                        pythonTracker.callAttr("reset")
                        trackerGeneration = epoch
                    }
                    val started = SystemClock.elapsedRealtimeNanos()
                    val result = pythonTracker.callAttr("process_argb", framePixels, analysisW, analysisH, now).asList()
                    val processingMs = (SystemClock.elapsedRealtimeNanos() - started) / 1e6
                    val detected = result.isNotEmpty()
                    val u = if (detected) (result[0].toDouble() + 0.5) / analysisW else 0.0
                    val v = if (detected) (result[1].toDouble() + 0.5) / analysisH else 0.0
                    val r = if (detected) result[2].toDouble() else 0.0
                    val (sx, sy) = PreviewCoordinates.toSensor(u, v, angle)
                    val json = JSONObject().apply {
                        put("type", "puck")
                        put("version", 1)
                        put("frame_id", frameId)
                        put("timestamp_ns", now) // monotonic readback time, NOT sensor exposure time
                        put("preview_timestamp_ns", previewTimestamp)
                        put("detected", detected)
                        put("coordinate_space", "sensor_pixels")
                        put("image_width", width)
                        put("image_height", height)
                        put("rotation_degrees", angle)
                        put("x", if (detected) sx * width - 0.5 else JSONObject.NULL)
                        put("y", if (detected) sy * height - 0.5 else JSONObject.NULL)
                        put("x_normalized", if (detected) sx else JSONObject.NULL)
                        put("y_normalized", if (detected) sy else JSONObject.NULL)
                        put("analysis_width", analysisW)
                        put("analysis_height", analysisH)
                        put("processing_ms", processingMs)
                    }.toString()
                    main.post {
                        if (active && epoch == generation) {
                            // Do not draw a delayed measurement over a much newer preview.
                            if (SystemClock.elapsedRealtimeNanos() - now < 250_000_000L && detected) {
                                overlay.show(u, v, r / analysisW, r / analysisH)
                            } else overlay.clear()
                            output.publish(json)
                            val text = if (detected) String.format(Locale.US, "Puck: X %.1f  Y %.1f | %.0f ms", sx * width - 0.5, sy * height - 0.5, processingMs)
                                       else "Puck lost"
                            status("$text | " + (outputError?.let { "XY unavailable: $it" }
                                ?: "TCP ${PuckCoordinateServer.DEFAULT_PORT}"))
                        }
                    }
                } catch (e: Exception) {
                    fail(epoch, e.message)
                } catch (e: LinkageError) {
                    fail(epoch, e.message)
                } finally {
                    busy.set(false)
                }
            }
        } catch (e: Exception) {
            busy.set(false)
            overlay.clear()
            status("Preview sampling error: ${e.message}")
        }
    }

    private fun fail(epoch: Int, message: String?) {
        main.post {
            if (active && epoch == generation) {
                // A Python/import error must not stop the independent recorder.
                enabled = false
                refresh()
                onFailure()
                status("Tracking error: $message. Enable tracking to retry.")
            }
        }
    }

    fun close() {
        closed = true
        refresh()
        worker.shutdownNow()
        bitmap?.recycle()
        bitmap = null
    }
}
