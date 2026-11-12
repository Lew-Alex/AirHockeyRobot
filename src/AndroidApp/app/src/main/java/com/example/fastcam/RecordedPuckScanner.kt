package com.example.fastcam

import android.content.Context
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.nio.ByteBuffer

/**
 * Sequentially decodes and tracks every frame in a saved video.
 *
 * Decoding runs without a Surface so the source's native orientation and the
 * exact decoder presentation timestamps are retained for later overlay work.
 */
object RecordedPuckScanner {
    private const val DEQUEUE_TIMEOUT_US = 10_000L
    private const val STALL_TIMEOUT_MS = 15_000L

    fun scan(context: Context, uri: Uri, onProgress: (Int) -> Unit = {}): List<RecordedPuckFrame> {
        val appContext = context.applicationContext
        checkInterrupted()
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        var selectedTrack = -1
        var totalUs = 0L
        try {
            extractor.setDataSource(appContext, uri, null)
            for (index in 0 until extractor.trackCount) {
                val format = extractor.getTrackFormat(index)
                val mime = format.getString(MediaFormat.KEY_MIME) ?: continue
                if (mime.startsWith("video/")) {
                    selectedTrack = index
                    totalUs = format.getLongOr(MediaFormat.KEY_DURATION, 0L).coerceAtLeast(0L)
                    break
                }
            }
            require(selectedTrack >= 0) { "No video track in $uri" }

            val inputFormat = extractor.getTrackFormat(selectedTrack)
            val mime = inputFormat.getString(MediaFormat.KEY_MIME)
                ?: error("Video track has no MIME type")
            extractor.selectTrack(selectedTrack)
            val decoderFormat = inputFormat
            decoderFormat.setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible
            )
            // Rotation metadata belongs to presentation. Decode the stored buffer as-is.
            decoderFormat.setInteger(MediaFormat.KEY_ROTATION, 0)
            codec = MediaCodec.createDecoderByType(mime)
            codec.configure(decoderFormat, null, null, 0)
            codec.start()

            val pythonTracker = createPythonTracker(appContext)
            val frames = ArrayList<RecordedPuckFrame>()
            val info = MediaCodec.BufferInfo()
            var inputEos = false
            var outputEos = false
            var firstPresentationUs: Long? = null
            var lastProgress = -1
            var lastProgressAtMs = System.nanoTime() / 1_000_000L

            while (!outputEos) {
                checkInterrupted()
                var madeProgress = false
                if (!inputEos) {
                    val inputIndex = codec.dequeueInputBuffer(DEQUEUE_TIMEOUT_US)
                    if (inputIndex >= 0) {
                        val input = codec.getInputBuffer(inputIndex)
                            ?: error("Decoder returned no input buffer")
                        input.clear()
                        val size = extractor.readSampleData(input, 0)
                        if (size < 0) {
                            codec.queueInputBuffer(inputIndex, 0, 0, 0L, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputEos = true
                        } else {
                            codec.queueInputBuffer(inputIndex, 0, size, extractor.sampleTime, 0)
                            extractor.advance()
                        }
                        madeProgress = true
                        lastProgressAtMs = System.nanoTime() / 1_000_000L
                    }
                }

                val outputIndex = codec.dequeueOutputBuffer(info, DEQUEUE_TIMEOUT_US)
                when {
                    outputIndex >= 0 -> {
                        try {
                            if (info.size > 0) {
                                val image = codec.getOutputImage(outputIndex)
                                    ?: error("Decoder did not expose a YUV output image")
                                try {
                                    val sourceTimeUs = info.presentationTimeUs
                                    if (firstPresentationUs == null) firstPresentationUs = sourceTimeUs
                                    val detection = analyzeImage(pythonTracker, image, sourceTimeUs)
                                    frames += detection
                                    if (totalUs > 0L) {
                                        val progressUs = (sourceTimeUs - (firstPresentationUs ?: sourceTimeUs)).coerceAtLeast(0L)
                                        val percent = ((progressUs * 100L) / totalUs).toInt().coerceIn(0, 99)
                                        if (percent != lastProgress) {
                                            onProgress(percent)
                                            lastProgress = percent
                                        }
                                    }
                                    lastProgressAtMs = System.nanoTime() / 1_000_000L
                                } finally {
                                    image.close()
                                }
                            }
                            outputEos = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                        } finally {
                            codec.releaseOutputBuffer(outputIndex, false)
                        }
                        madeProgress = true
                    }
                    outputIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        // Some decoders only settle their output format after the first sample.
                        madeProgress = true
                    }
                }

                if (!madeProgress) {
                    val now = System.nanoTime() / 1_000_000L
                    if (now - lastProgressAtMs > STALL_TIMEOUT_MS) {
                        error("Video decoder stalled before end of stream")
                    }
                }
            }
            onProgress(100)
            val firstPtsUs = frames.minOfOrNull { it.timeUs } ?: 0L
            return frames.sortedBy { it.timeUs }.map { it.copy(timeUs = it.timeUs - firstPtsUs) }
        } finally {
            try {
                codec?.stop()
            } catch (_: Exception) {
                // A codec which failed during setup may not have reached started state.
            }
            try { codec?.release() } finally { extractor.release() }
        }
    }

    private fun analyzeImage(tracker: PyObject, image: android.media.Image, timeUs: Long): RecordedPuckFrame {
        checkInterrupted()
        val crop = image.cropRect
        val planes = image.planes
        require(planes.size >= 3) { "Expected three YUV420 planes" }
        val y = copyPlane(planes[0].buffer)
        val u = copyPlane(planes[1].buffer)
        val v = copyPlane(planes[2].buffer)
        val timestampNs = timeUs * 1_000L
        val result = tracker.callAttr(
            "process_yuv420",
            y, u, v,
            image.width, image.height,
            planes[0].rowStride, planes[0].pixelStride,
            planes[1].rowStride, planes[1].pixelStride,
            planes[2].rowStride, planes[2].pixelStride,
            crop.left, crop.top, crop.width(), crop.height(), timestampNs
        ).asList()
        if (result.isEmpty()) return RecordedPuckFrame(timeUs, null, null, null)
        val x = result[0].toDouble()
        val yy = result[1].toDouble()
        val radius = result[2].toDouble()
        val nativeX = (x + 0.5) / crop.width()
        val nativeY = (yy + 0.5) / crop.height()
        return RecordedPuckFrame(timeUs, nativeX, nativeY, radius / minOf(crop.width(), crop.height()))
    }

    private fun createPythonTracker(context: Context): PyObject {
        synchronized(Python::class.java) {
            if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        }
        return Python.getInstance().getModule("android_bridge").callAttr("AndroidTracker")
    }

    private fun copyPlane(source: ByteBuffer): ByteArray {
        val view = source.duplicate()
        val bytes = ByteArray(view.remaining())
        view.get(bytes)
        return bytes
    }

    private fun checkInterrupted() {
        if (Thread.currentThread().isInterrupted) throw InterruptedException("Recorded scan cancelled")
    }

    private fun MediaFormat.getLongOr(key: String, default: Long): Long =
        if (containsKey(key)) getLong(key) else default

}
