package com.example.fastcam

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import androidx.media3.common.MediaItem
import androidx.media3.common.util.Size
import androidx.media3.effect.BitmapOverlay
import androidx.media3.effect.OverlayEffect
import androidx.media3.effect.TextureOverlay
import androidx.media3.transformer.Composition
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.VideoEncoderSettings
import com.google.common.collect.ImmutableList
import java.io.File
import java.util.UUID
import java.util.concurrent.CancellationException
import java.util.concurrent.Executors
import java.util.concurrent.Future
import kotlin.math.abs
import kotlin.math.min

/**
 * Optional second pass after capture: track each saved frame, then burn its ring
 * into a separate MP4. The original recording and its sensor metadata are retained.
 * Transformer lifecycle calls run on the main looper; decoding/Python/copying use IO.
 */
@androidx.annotation.OptIn(markerClass = [androidx.media3.common.util.UnstableApi::class])
class TrackedVideoExporter(
    context: Context,
    private val onStatus: (String) -> Unit,
    private val onFinished: (Uri?, String?) -> Unit
) {
    private val context = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor { r -> Thread(r, "puck-mp4-export") }
    private var current: Job? = null
    private var transformer: Transformer? = null
    private var work: Future<*>? = null
    private var closed = false
    val isRunning: Boolean get() = current != null

    private class Job(val source: Uri, val name: String, val fps: Int, val file: File) {
        @Volatile var cancelled = false
        @Volatile var pendingUri: Uri? = null
    }

    private data class VideoInfo(val width: Int, val height: Int, val rotation: Int, val mime: String)

    /** Called on the UI thread once the source MediaRecorder output is finalized. */
    fun start(source: Uri, name: String, fps: Int) {
        check(Looper.myLooper() == Looper.getMainLooper())
        check(!closed && current == null) { "Another MP4 export is already running" }
        val job = Job(source, name, fps, File(context.cacheDir, "puck-${UUID.randomUUID()}.mp4"))
        current = job
        onStatus("MP4 overlay: analysing saved frames… 0%")
        work = io.submit {
            try {
                val info = readVideoInfo(job.source)
                val frames = RecordedPuckScanner.scan(context, job.source) { percent ->
                    main.post { if (current === job) onStatus("MP4 overlay: analysing saved frames… $percent%") }
                }
                check(frames.isNotEmpty()) { "No decoded video frames" }
                checkNotCancelled(job)
                main.post {
                    if (current === job && !job.cancelled) {
                        try { encode(job, info, frames) } catch (e: Exception) { fail(job, e) }
                    }
                }
            } catch (e: Exception) {
                fail(job, e)
            } catch (e: LinkageError) {
                fail(job, e)
            }
        }
    }

    private fun encode(job: Job, info: VideoInfo, frames: List<RecordedPuckFrame>) {
        val overlay = PuckVideoOverlay(RecordedPuckTimeline(frames), info.rotation)
        val bitrate = (info.width.toLong() * info.height * job.fps * 0.15)
            .toLong().coerceIn(20_000_000L, 200_000_000L).toInt()
        val encoderFactory = DefaultEncoderFactory.Builder(context)
            // An export must fail explicitly rather than quietly lower the recording resolution.
            .setEnableFallback(false)
            .setRequestedVideoEncoderSettings(VideoEncoderSettings.Builder().setBitrate(bitrate).build())
            .build()
        val edited = EditedMediaItem.Builder(MediaItem.fromUri(job.source))
            .setRemoveAudio(true)
            // Keep source timestamps. setFrameRate is a cap and can discard high-speed frames.
            .setEffects(Effects(emptyList(), listOf(OverlayEffect(ImmutableList.of<TextureOverlay>(overlay)))))
            .build()
        val encoder = Transformer.Builder(context)
            .setVideoMimeType(info.mime)
            .setEncoderFactory(encoderFactory)
            .addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                    if (current !== job) return
                    transformer = null
                    onStatus("MP4 overlay: checking frames and saving…")
                    work = io.submit {
                        try {
                            validateOutput(job, info, frames)
                            val uri = publish(job)
                            main.post {
                                if (current === job && !job.cancelled) {
                                    current = null
                                    job.pendingUri = null // finalized file now belongs to MediaStore
                                    job.file.delete()
                                    onStatus("Saved ${job.name}_tracked.mp4")
                                    onFinished(uri, null)
                                } else cleanup(job)
                            }
                        } catch (e: Exception) { fail(job, e) }
                    }
                }

                override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) {
                    fail(job, exportException)
                }
            }).build()
        transformer = encoder
        encoder.start(edited, job.file.absolutePath)
        val holder = ProgressHolder()
        val poll = object : Runnable {
            override fun run() {
                if (current !== job || transformer !== encoder) return
                if (encoder.getProgress(holder) == Transformer.PROGRESS_STATE_AVAILABLE) {
                    onStatus("MP4 overlay: encoding green circle… ${holder.progress}%")
                } else onStatus("MP4 overlay: encoding green circle…")
                main.postDelayed(this, 500)
            }
        }
        main.post(poll)
    }

    private fun readVideoInfo(uri: Uri): VideoInfo {
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(context, uri, null)
            val index = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true
            } ?: error("Recording has no video track")
            val format = extractor.getTrackFormat(index)
            return VideoInfo(format.getInteger(MediaFormat.KEY_WIDTH), format.getInteger(MediaFormat.KEY_HEIGHT),
                if (format.containsKey(MediaFormat.KEY_ROTATION)) format.getInteger(MediaFormat.KEY_ROTATION) else 0,
                format.getString(MediaFormat.KEY_MIME) ?: error("Video MIME type missing"))
        } finally { extractor.release() }
    }

    /** Validate geometry, every frame, and its time before publishing the annotated video. */
    private fun validateOutput(job: Job, source: VideoInfo, frames: List<RecordedPuckFrame>) {
        checkNotCancelled(job)
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(job.file.absolutePath)
            val index = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true
            } ?: error("Annotated export has no video track")
            val format = extractor.getTrackFormat(index)
            val rotation = if (format.containsKey(MediaFormat.KEY_ROTATION)) format.getInteger(MediaFormat.KEY_ROTATION) else 0
            val outputSize = PreviewCoordinates.displaySize(format.getInteger(MediaFormat.KEY_WIDTH),
                format.getInteger(MediaFormat.KEY_HEIGHT), rotation)
            check(outputSize == PreviewCoordinates.displaySize(source.width, source.height, source.rotation)) {
                "Encoder changed the video resolution"
            }
            extractor.selectTrack(index)
            val times = ArrayList<Long>(frames.size)
            while (extractor.sampleTime >= 0) {
                checkNotCancelled(job)
                times.add(extractor.sampleTime)
                if (!extractor.advance()) break
            }
            times.sort() // MP4 sample order can differ from presentation order when B-frames are used.
            check(times.size == frames.size) { "Encoder changed frame count (${frames.size} to ${times.size})" }
            val origin = times.first()
            check(times.indices.all { abs(times[it] - origin - frames[it].timeUs) <= 1_000 }) {
                "Encoder changed frame timing"
            }
        } finally { extractor.release() }
    }

    private fun publish(job: Job): Uri {
        checkNotCancelled(job)
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, "${job.name}_tracked.mp4")
            put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
            put(MediaStore.MediaColumns.RELATIVE_PATH, "Movies/FastCam")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = context.contentResolver.insert(MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
            ?: error("Could not create annotated MP4")
        job.pendingUri = uri
        job.file.inputStream().use { input ->
            val output = context.contentResolver.openOutputStream(uri, "w") ?: error("Could not open annotated MP4")
            output.use {
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    checkNotCancelled(job)
                    val count = input.read(buffer)
                    if (count < 0) break
                    it.write(buffer, 0, count)
                }
            }
        }
        checkNotCancelled(job)
        check(context.contentResolver.update(uri,
            ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null) == 1) {
            "Could not finalize annotated MP4"
        }
        return uri
    }

    private fun checkNotCancelled(job: Job) {
        if (job.cancelled || Thread.currentThread().isInterrupted) throw CancellationException("MP4 export cancelled")
    }

    private fun fail(job: Job, error: Throwable) {
        main.post {
            if (current === job) {
                current = null
                job.cancelled = true
                transformer?.cancel()
                transformer = null
                io.execute { cleanup(job) }
                onStatus("MP4 overlay failed: ${error.message}. Original recording saved.")
                onFinished(null, error.message ?: error.javaClass.simpleName)
            }
        }
    }

    private fun cleanup(job: Job) {
        job.pendingUri?.let { uri ->
            try { context.contentResolver.delete(uri, null, null) } catch (_: Exception) {}
        }
        job.pendingUri = null
        job.file.delete()
    }

    /** Cancellation discards only the incomplete derivative; the source recording stays intact. */
    fun cancel() {
        val job = current ?: return
        current = null
        job.cancelled = true
        work?.cancel(true)
        transformer?.cancel()
        transformer = null
        io.execute { cleanup(job) }
        if (!closed) {
            onStatus("MP4 overlay cancelled. Original recording saved.")
            onFinished(null, "Cancelled")
        }
    }

    fun close() {
        closed = true
        cancel()
        io.shutdown() // lets queued cleanup finish after a cancelled decoder/copy exits
    }
}

/** Two reused bitmaps ensure BitmapOverlay uploads changed pixels for each new timestamp. */
@androidx.annotation.OptIn(markerClass = [androidx.media3.common.util.UnstableApi::class])
private class PuckVideoOverlay(private val timeline: RecordedPuckTimeline, private val rotation: Int) : BitmapOverlay() {
    private var bitmaps = emptyArray<Bitmap>()
    private var index = 0
    private var lastTimeUs = Long.MIN_VALUE
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.GREEN; style = Paint.Style.STROKE }

    override fun configure(videoSize: Size) {
        super.configure(videoSize)
        bitmaps.forEach { it.recycle() }
        val scale = min(1.0, 1280.0 / maxOf(videoSize.width, videoSize.height))
        val width = (videoSize.width * scale).toInt().coerceAtLeast(1)
        val height = (videoSize.height * scale).toInt().coerceAtLeast(1)
        bitmaps = Array(2) { Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888) }
        lastTimeUs = Long.MIN_VALUE
    }

    override fun getBitmap(presentationTimeUs: Long): Bitmap {
        check(bitmaps.isNotEmpty()) { "Video overlay not configured" }
        if (presentationTimeUs == lastTimeUs) return bitmaps[index]
        lastTimeUs = presentationTimeUs
        index = 1 - index
        val bitmap = bitmaps[index]
        bitmap.eraseColor(Color.TRANSPARENT)
        val frame = timeline.at(presentationTimeUs) ?: return bitmap
        val (u, v) = PreviewCoordinates.toPreview(frame.x!!, frame.y!!, rotation)
        val canvas = Canvas(bitmap)
        val shorter = min(bitmap.width, bitmap.height).toFloat()
        val x = (u * bitmap.width).toFloat()
        val y = (v * bitmap.height).toFloat()
        val padding = maxOf(3f, shorter / 180f)
        paint.strokeWidth = maxOf(2f, shorter / 240f)
        canvas.drawCircle(x, y, (frame.radius!! * shorter).toFloat() + padding, paint)
        canvas.drawLine(x - padding, y, x + padding, y, paint)
        canvas.drawLine(x, y - padding, x, y + padding, paint)
        return bitmap
    }

    override fun release() {
        try { super.release() } finally {
            bitmaps.forEach { it.recycle() }
            bitmaps = emptyArray()
        }
    }
}
