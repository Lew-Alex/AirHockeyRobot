package com.example.fastcam

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.ContentValues
import android.content.pm.PackageManager
import android.graphics.SurfaceTexture
import android.graphics.Matrix
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraConstrainedHighSpeedCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.MediaCodec
import android.media.MediaRecorder
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.provider.MediaStore
import android.util.Range
import android.util.Size
import android.view.Gravity
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.FrameLayout
import android.widget.Spinner
import android.widget.TextView
import android.widget.Switch
import android.widget.Toast
import java.io.File
import java.io.FileDescriptor
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executor
import kotlin.math.roundToInt

/**
 * FastCam: records high frame rate video (120/240fps "high-speed" modes, or 60fps standard modes)
 * with the camera's fastest sensor readout, and logs per-frame metadata (timestamps, exposure,
 * rolling shutter skew) to a CSV next to the video for later processing.
 *
 * Rolling shutter note: Android does not let apps set the sensor readout speed directly. The
 * readout time is fixed by the sensor mode the camera picks for a given resolution + frame rate.
 * High-speed (120/240fps) modes must read the whole frame in under 8.3ms / 4.2ms, so they are
 * usually the fastest readout available. The app shows the camera-reported skew live so you can
 * compare modes and pick the lowest.
 */
class MainActivity : Activity() {

    /** One recording configuration the camera supports. */
    data class Mode(val size: Size, val fps: Int, val fpsRange: Range<Int>, val highSpeed: Boolean) {
        val label: String
            get() = "${size.width}x${size.height} @ ${fps}fps" + if (highSpeed) "  (high-speed)" else "  (standard)"
    }

    companion object {
        private const val REQ_CAMERA = 1
        private const val REC_TAG = "record"
        // Shutter options for standard (60fps) modes. null = auto exposure.
        private val SHUTTER_OPTIONS: List<Long?> = listOf(
            null, 1_000_000_000L / 250, 1_000_000_000L / 500, 1_000_000_000L / 1000,
            1_000_000_000L / 2000, 1_000_000_000L / 4000
        )
    }

    // UI
    private lateinit var textureView: TextureView
    private lateinit var modeSpinner: Spinner
    private lateinit var recordButton: Button
    private lateinit var shutterButton: Button
    private lateinit var infoText: TextView
    private lateinit var tracking: LivePuckTracking
    private lateinit var puckOverlay: PuckOverlayView
    private lateinit var embedTrackingSwitch: Switch
    private lateinit var exportStatus: TextView
    private lateinit var cancelExportButton: Button
    private lateinit var videoExporter: TrackedVideoExporter
    private var activityResumed = false
    @Volatile private var embedTrackingInMp4 = false
    private var embedThisRecording = false
    private var recordedFps = 30

    // Camera setup
    private lateinit var cameraManager: CameraManager
    private var cameraId = ""
    private lateinit var characteristics: CameraCharacteristics
    private var sensorOrientation = 90
    private var manualSensorSupported = false
    private var modes: List<Mode> = emptyList()
    @Volatile private var currentMode: Mode? = null
    @Volatile private var shutterIndex = 0

    // Camera runtime (touched only on the camera thread, except where noted)
    private var cameraThread: HandlerThread? = null
    private var cameraHandler: Handler? = null
    private var cameraExecutor: Executor? = null
    private var camera: CameraDevice? = null
    private var opening = false
    private var session: CameraCaptureSession? = null
    private var previewSurface: Surface? = null
    private var recorderSurface: Surface? = null
    private var sessionGeneration = 0
    @Volatile private var useHevc = true

    // Recording
    @Volatile private var recording = false
    private var recorder: MediaRecorder? = null
    private var videoUri: Uri? = null
    private var videoPfd: ParcelFileDescriptor? = null
    private var baseName = ""
    private var csv: StringBuilder? = null
    private var framesLogged = 0
    private var recordStartMs = 0L

    // Live stats (written on camera thread, read for display)
    @Volatile private var lastSkewNs = 0L
    @Volatile private var lastExposureNs = 0L
    @Volatile private var lastIso = 0
    @Volatile private var fpsEma = 0.0
    private var lastTimestamp = 0L
    private var lastUiUpdateMs = 0L
    // Remembered auto-exposure values, used to pick an ISO when switching to a fast manual shutter.
    @Volatile private var autoExposureNs = 10_000_000L
    @Volatile private var autoIso = 100

    // ---------------------------------------------------------------- lifecycle

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        textureView = findViewById(R.id.preview)
        modeSpinner = findViewById(R.id.modeSpinner)
        recordButton = findViewById(R.id.recordButton)
        recordButton.isEnabled = false // wait for a configured camera session
        shutterButton = findViewById(R.id.shutterButton)
        infoText = findViewById(R.id.info)
        puckOverlay = findViewById(R.id.puckOverlay)
        val trackingStatus = findViewById<TextView>(R.id.trackingStatus)
        val trackingSwitch = findViewById<Switch>(R.id.trackingSwitch)
        tracking = LivePuckTracking(this, textureView, puckOverlay, { trackingSwitch.isChecked = false }) {
            trackingStatus.text = it
        }
        trackingSwitch.setOnCheckedChangeListener { _, checked ->
            tracking.setEnabled(checked)
        }
        embedTrackingSwitch = findViewById(R.id.embedTrackingSwitch)
        exportStatus = findViewById(R.id.exportStatus)
        cancelExportButton = findViewById(R.id.cancelExportButton)
        videoExporter = TrackedVideoExporter(this,
            onStatus = { exportStatus.text = it },
            onFinished = { uri, error ->
                setExportUi(false)
                if (uri != null) toast("Saved MP4 with green circle in Movies/FastCam")
                else if (error != "Cancelled") toast("MP4 overlay failed: $error. Original recording kept.")
            })
        embedTrackingSwitch.setOnCheckedChangeListener { _, checked ->
            embedTrackingInMp4 = checked
            exportStatus.text = if (checked) "After Stop: save an additional MP4 with the tracked circle"
                                else "MP4 overlay off"
        }
        cancelExportButton.setOnClickListener { videoExporter.cancel() }

        cameraManager = getSystemService(CameraManager::class.java)
        if (!pickCamera()) {
            infoText.text = "No back camera found."
            recordButton.isEnabled = false
            return
        }
        modes = buildModes()
        if (modes.isEmpty()) {
            infoText.text = "This camera reports no 60fps+ video modes."
            recordButton.isEnabled = false
            return
        }

        modeSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, modes.map { it.label })
        val default = modes.indexOfFirst { it.highSpeed && it.fps == 120 && it.size.width == 1920 }
            .takeIf { it >= 0 } ?: 0
        modeSpinner.setSelection(default)
        currentMode = modes[default]
        modeSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val m = modes[position]
                if (m == currentMode) return
                recordButton.isEnabled = false
                tracking.setCameraReady(false)
                currentMode = m
                updatePreviewLayout()
                updateShutterButton()
                cameraHandler?.post { startSession() }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        recordButton.setOnClickListener {
            recordButton.isEnabled = false // re-enabled once start/stop finishes
            embedTrackingSwitch.isEnabled = false
            cameraHandler?.post { if (recording) stopRecording() else startRecording() }
        }
        shutterButton.setOnClickListener {
            shutterIndex = (shutterIndex + 1) % SHUTTER_OPTIONS.size
            updateShutterButton()
            cameraHandler?.post { startRepeating(recording) }
        }
        updateShutterButton()

        textureView.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(st: SurfaceTexture, w: Int, h: Int) {
                updatePreviewLayout()
                tryOpenCamera()
            }
            override fun onSurfaceTextureSizeChanged(st: SurfaceTexture, w: Int, h: Int) {
                updatePreviewLayout()
            }
            override fun onSurfaceTextureDestroyed(st: SurfaceTexture): Boolean {
                tracking.setCameraReady(false)
                return true
            }
            override fun onSurfaceTextureUpdated(st: SurfaceTexture) { tracking.onPreviewFrame() }
        }
        findViewById<View>(R.id.previewContainer).addOnLayoutChangeListener { _, l, t, r, b, ol, ot, or, ob ->
            if (r - l != or - ol || b - t != ob - ot) updatePreviewLayout()
        }
        textureView.post { updatePreviewLayout() }

        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA)
        }
    }

    override fun onResume() {
        super.onResume()
        activityResumed = true
        if (modes.isEmpty()) return
        val t = HandlerThread("camera").also { it.start() }
        cameraThread = t
        val h = Handler(t.looper)
        cameraHandler = h
        cameraExecutor = Executor { h.post(it) }
        tracking.setResumed(!videoExporter.isRunning)
        tryOpenCamera()
    }

    override fun onPause() {
        activityResumed = false
        tracking.setResumed(false)
        val h = cameraHandler
        val t = cameraThread
        if (h != null && t != null) {
            h.post {
                if (recording) stopRecording()
                closeCamera()
            }
            t.quitSafely()
            try { t.join(3000) } catch (_: InterruptedException) {}
        }
        cameraHandler = null
        cameraThread = null
        cameraExecutor = null
        super.onPause()
    }

    override fun onDestroy() {
        videoExporter.close()
        tracking.close()
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_CAMERA) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) tryOpenCamera()
            else infoText.text = "Camera permission is required."
        }
    }

    // ---------------------------------------------------------------- camera discovery

    /** Picks the back camera, preferring one that supports high-speed (120fps+) video. */
    private fun pickCamera(): Boolean {
        var fallback: String? = null
        for (id in cameraManager.cameraIdList) {
            val ch = cameraManager.getCameraCharacteristics(id)
            if (ch.get(CameraCharacteristics.LENS_FACING) != CameraCharacteristics.LENS_FACING_BACK) continue
            val caps = ch.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
            if (caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO)) {
                useCamera(id, ch)
                return true
            }
            if (fallback == null) fallback = id
        }
        fallback ?: return false
        useCamera(fallback, cameraManager.getCameraCharacteristics(fallback))
        return true
    }

    private fun useCamera(id: String, ch: CameraCharacteristics) {
        cameraId = id
        characteristics = ch
        sensorOrientation = ch.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 90
        val caps = ch.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
        manualSensorSupported = caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR)
    }

    private fun buildModes(): List<Mode> {
        val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return emptyList()
        val caps = characteristics.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
        val out = mutableListOf<Mode>()

        // High-speed modes (120fps, 240fps, ...). Recording requires a fixed range like [120,120].
        if (caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO)) {
            for (size in map.highSpeedVideoSizes) {
                for (r in map.getHighSpeedVideoFpsRangesFor(size)) {
                    if (r.lower == r.upper && r.upper >= 120) out += Mode(size, r.upper, r, true)
                }
            }
        }

        // Standard 60fps modes (these allow manual fast shutter).
        val aeRanges = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES) ?: emptyArray()
        val range60 = aeRanges.firstOrNull { it.lower == 60 && it.upper == 60 }
            ?: aeRanges.filter { it.upper == 60 }.maxByOrNull { it.lower }
        if (range60 != null) {
            val recSizes = map.getOutputSizes(MediaRecorder::class.java)?.toSet() ?: emptySet()
            for (size in listOf(Size(3840, 2160), Size(1920, 1080), Size(1280, 720))) {
                if (size !in recSizes) continue
                val minFrame = map.getOutputMinFrameDuration(MediaRecorder::class.java, size)
                if (minFrame in 1..16_700_000L) out += Mode(size, 60, range60, false)
            }
        }

        // Fallback (e.g. emulator or a camera without fast modes): offer 30fps so the app still works.
        if (out.isEmpty()) {
            val range30 = aeRanges.firstOrNull { it.lower == 30 && it.upper == 30 }
                ?: aeRanges.filter { it.upper == 30 }.maxByOrNull { it.lower }
                ?: Range(30, 30)
            val recSizes = map.getOutputSizes(MediaRecorder::class.java)?.toList() ?: emptyList()
            val preferred = listOf(Size(1920, 1080), Size(1280, 720), Size(640, 480)).filter { it in recSizes }
            val sizes = preferred.ifEmpty { recSizes.sortedByDescending { it.width * it.height }.take(1) }
            for (size in sizes) out += Mode(size, 30, range30, false)
        }

        return out.distinct().sortedWith(
            compareByDescending<Mode> { it.highSpeed }.thenByDescending { it.fps }.thenByDescending { it.size.width }
        )
    }

    // ---------------------------------------------------------------- open / session

    @SuppressLint("MissingPermission")
    private fun tryOpenCamera() {
        if (videoExporter.isRunning) return
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return
        if (!textureView.isAvailable) return
        val h = cameraHandler ?: return
        h.post {
            if (camera != null || opening) return@post
            opening = true
            try {
                cameraManager.openCamera(cameraId, object : CameraDevice.StateCallback() {
                    override fun onOpened(c: CameraDevice) {
                        opening = false
                        camera = c
                        startSession()
                    }
                    override fun onDisconnected(c: CameraDevice) {
                        runOnUiThread { tracking.setCameraReady(false) }
                        opening = false
                        c.close()
                        if (camera == c) camera = null
                    }
                    override fun onError(c: CameraDevice, error: Int) {
                        runOnUiThread { tracking.setCameraReady(false) }
                        opening = false
                        c.close()
                        if (camera == c) camera = null
                        toast("Camera error $error")
                    }
                }, h)
            } catch (e: Exception) {
                opening = false
                toast("Could not open camera: ${e.message}")
            }
        }
    }

    /** (Re)creates the capture session for the current mode. Camera thread only. */
    private fun startSession() {
        val cam = camera ?: return
        val mode = currentMode ?: return
        val st = textureView.surfaceTexture ?: return
        val executor = cameraExecutor ?: return
        if (recording) return

        runOnUiThread { tracking.setCameraReady(false) }

        session?.close()
        session = null
        previewSurface?.release()
        recorderSurface?.release()
        val generation = ++sessionGeneration

        // Preview buffers must match the video size in high-speed sessions.
        st.setDefaultBufferSize(mode.size.width, mode.size.height)
        val preview = Surface(st)
        previewSurface = preview

        // A persistent surface lets us start/stop MediaRecorder without rebuilding the session.
        // It must be configured once by a prepared recorder so the camera knows its size.
        val recSurface = MediaCodec.createPersistentInputSurface()
        val dummy = File(cacheDir, "warmup.mp4")
        try {
            useHevc = true
            try {
                createRecorder(recSurface, mode, null, dummy).apply { prepare(); release() }
            } catch (e: Exception) {
                useHevc = false // HEVC encoder refused this size/fps: fall back to H.264
                createRecorder(recSurface, mode, null, dummy).apply { prepare(); release() }
            }
        } catch (e: Exception) {
            toast("Encoder can't do ${mode.label}: ${e.message}")
            recSurface.release()
            return
        } finally {
            dummy.delete()
        }
        recorderSurface = recSurface

        val sessionType = if (mode.highSpeed) SessionConfiguration.SESSION_HIGH_SPEED else SessionConfiguration.SESSION_REGULAR
        val config = SessionConfiguration(
            sessionType,
            listOf(OutputConfiguration(preview), OutputConfiguration(recSurface)),
            executor,
            object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(s: CameraCaptureSession) {
                    if (generation != sessionGeneration) { s.close(); return }
                    session = s
                    lastTimestamp = 0
                    fpsEma = 0.0
                    startRepeating(false)
                    runOnUiThread {
                        recordButton.isEnabled = !videoExporter.isRunning
                        tracking.setCameraReady(true)
                    }
                }
                override fun onConfigureFailed(s: CameraCaptureSession) {
                    toast("Camera refused ${mode.label}. Pick another mode.")
                }
            }
        )
        try {
            cam.createCaptureSession(config)
        } catch (e: Exception) {
            toast("Session error: ${e.message}")
        }
    }

    /** Starts the repeating preview (or preview+record) request. Camera thread only. */
    private fun startRepeating(record: Boolean) {
        val s = session ?: return
        val cam = camera ?: return
        val mode = currentMode ?: return
        val preview = previewSurface ?: return
        val rec = recorderSurface ?: return
        try {
            val b = cam.createCaptureRequest(if (record) CameraDevice.TEMPLATE_RECORD else CameraDevice.TEMPLATE_PREVIEW)
            b.addTarget(preview)
            if (record) {
                b.addTarget(rec)
                b.setTag(REC_TAG)
            }
            b.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
            b.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, mode.fpsRange)
            b.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO)

            if (!mode.highSpeed) {
                // Electronic stabilization warps/crops frames, which would corrupt later processing.
                b.set(CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE, CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE_OFF)
                val exposure = SHUTTER_OPTIONS[shutterIndex]
                if (exposure != null && manualSensorSupported) {
                    val expRange = characteristics.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
                    val exp = expRange?.clamp(exposure) ?: exposure
                    b.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF)
                    b.set(CaptureRequest.SENSOR_EXPOSURE_TIME, exp)
                    b.set(CaptureRequest.SENSOR_SENSITIVITY, isoFor(exp))
                    b.set(CaptureRequest.SENSOR_FRAME_DURATION, 1_000_000_000L / mode.fps)
                }
            }

            val request = b.build()
            if (s is CameraConstrainedHighSpeedCaptureSession) {
                s.setRepeatingBurst(s.createHighSpeedRequestList(request), captureCallback, cameraHandler)
            } else {
                s.setRepeatingRequest(request, captureCallback, cameraHandler)
            }
        } catch (e: Exception) {
            toast("Request error: ${e.message}")
        }
    }

    /** Keeps brightness roughly the same as auto exposure when using a faster shutter. */
    private fun isoFor(exposureNs: Long): Int {
        val target = autoIso.toDouble() * autoExposureNs / exposureNs
        val range = characteristics.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
        val iso = target.toInt().coerceAtLeast(1)
        return range?.clamp(iso) ?: iso
    }

    private fun closeCamera() {
        runOnUiThread { tracking.setCameraReady(false) }
        sessionGeneration++
        try { session?.close() } catch (_: Exception) {}
        session = null
        camera?.close()
        camera = null
        opening = false
        previewSurface?.release()
        previewSurface = null
        recorderSurface?.release()
        recorderSurface = null
    }

    // ---------------------------------------------------------------- per-frame metadata

    private val captureCallback = object : CameraCaptureSession.CaptureCallback() {
        override fun onCaptureCompleted(s: CameraCaptureSession, request: CaptureRequest, result: TotalCaptureResult) {
            val ts = result.get(CaptureResult.SENSOR_TIMESTAMP) ?: return
            val skew = result.get(CaptureResult.SENSOR_ROLLING_SHUTTER_SKEW) ?: 0L
            val exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME) ?: 0L
            val iso = result.get(CaptureResult.SENSOR_SENSITIVITY) ?: 0
            val frameDuration = result.get(CaptureResult.SENSOR_FRAME_DURATION) ?: 0L

            if (result.get(CaptureResult.CONTROL_AE_MODE) != CaptureResult.CONTROL_AE_MODE_OFF && exposure > 0 && iso > 0) {
                autoExposureNs = exposure
                autoIso = iso
            }
            lastSkewNs = skew
            lastExposureNs = exposure
            lastIso = iso
            if (lastTimestamp != 0L && ts > lastTimestamp) {
                val inst = 1e9 / (ts - lastTimestamp)
                fpsEma = if (fpsEma == 0.0) inst else fpsEma * 0.95 + inst * 0.05
            }
            lastTimestamp = ts

            if (recording && request.tag == REC_TAG) {
                csv?.append("${result.frameNumber},$ts,$exposure,$skew,$frameDuration,$iso\n")
                framesLogged++
            }

            val now = SystemClock.uptimeMillis()
            if (now - lastUiUpdateMs > 250) {
                lastUiUpdateMs = now
                runOnUiThread { updateInfo() }
            }
        }
    }

    // ---------------------------------------------------------------- recording

    private fun createRecorder(surface: Surface, mode: Mode, fd: FileDescriptor?, file: File?): MediaRecorder {
        val pixelsPerSec = mode.size.width.toLong() * mode.size.height * mode.fps
        val bitrate = (pixelsPerSec * 0.15).toLong().coerceIn(20_000_000L, 200_000_000L).toInt()
        return MediaRecorder(this).apply {
            setVideoSource(MediaRecorder.VideoSource.SURFACE)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            if (fd != null) setOutputFile(fd) else setOutputFile(file)
            setVideoEncoder(if (useHevc) MediaRecorder.VideoEncoder.HEVC else MediaRecorder.VideoEncoder.H264)
            setVideoEncodingBitRate(bitrate)
            setVideoFrameRate(mode.fps)
            setVideoSize(mode.size.width, mode.size.height)
            setOrientationHint(previewRotation())
            setInputSurface(surface)
        }
    }

    /** Camera thread only. */
    private fun startRecording() {
        val mode = currentMode
        val surface = recorderSurface
        if (recording || session == null || mode == null || surface == null) {
            runOnUiThread {
                recordButton.isEnabled = session != null
                embedTrackingSwitch.isEnabled = !recording
            }
            return
        }
        try {
            embedThisRecording = embedTrackingInMp4
            recordedFps = mode.fps
            baseName = "FASTCAM_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date()) +
                "_${mode.size.width}x${mode.size.height}_${mode.fps}fps"
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, "$baseName.mp4")
                put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
                put(MediaStore.MediaColumns.RELATIVE_PATH, "Movies/FastCam")
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = contentResolver.insert(MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
                ?: throw IllegalStateException("Could not create video file")
            videoUri = uri
            val pfd = contentResolver.openFileDescriptor(uri, "w") ?: throw IllegalStateException("Could not open video file")
            videoPfd = pfd

            val r = createRecorder(surface, mode, pfd.fileDescriptor, null)
            r.prepare()
            r.start()
            recorder = r

            csv = StringBuilder().apply {
                append("# FastCam per-frame metadata\n")
                append("# video=$baseName.mp4 mode=${mode.label} camera=$cameraId sensor_orientation=$sensorOrientation\n")
                append("# timestamps are CLOCK_BOOTTIME-style ns (SENSOR_TIMESTAMP = start of exposure of the first row)\n")
                append("# row r of the frame starts exposing at sensor_timestamp_ns + skew_ns * r / (rows - 1)\n")
                append("frame_number,sensor_timestamp_ns,exposure_ns,rolling_shutter_skew_ns,frame_duration_ns,iso\n")
            }
            framesLogged = 0
            recordStartMs = SystemClock.uptimeMillis()
            recording = true
            startRepeating(true)
            runOnUiThread {
                recordButton.text = "■ STOP"
                recordButton.isEnabled = true
                modeSpinner.isEnabled = false
            }
        } catch (e: Exception) {
            recording = false
            recorder?.release()
            recorder = null
            videoPfd?.close()
            videoPfd = null
            videoUri?.let { contentResolver.delete(it, null, null) }
            videoUri = null
            toast("Could not start recording: ${e.message}")
            runOnUiThread {
                recordButton.isEnabled = true
                embedTrackingSwitch.isEnabled = true
            }
        }
    }

    /** Camera thread only. */
    private fun stopRecording() {
        if (!recording) return
        recording = false
        startRepeating(false)

        var ok = true
        try {
            recorder?.stop()
        } catch (e: RuntimeException) {
            ok = false // stop() throws if no frames were recorded
        }
        recorder?.release()
        recorder = null
        try { videoPfd?.close() } catch (_: Exception) {}
        videoPfd = null

        val uri = videoUri
        videoUri = null
        if (uri != null) {
            if (ok) {
                contentResolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
            } else {
                contentResolver.delete(uri, null, null)
            }
        }

        val csvText = csv?.toString()
        csv = null
        var csvSaved = false
        if (ok && csvText != null) csvSaved = saveCsv("$baseName.csv", csvText)

        toast(
            if (ok) "Saved Movies/FastCam/$baseName.mp4" +
                (if (csvSaved) "\n+ Download/FastCam/$baseName.csv ($framesLogged frames)" else "")
            else "Recording failed (no frames)"
        )
        val annotate = ok && uri != null && embedThisRecording
        val savedBaseName = baseName
        val savedFps = recordedFps
        runOnUiThread {
            recordButton.text = "● REC"
            recordButton.isEnabled = true
            modeSpinner.isEnabled = true
            embedTrackingSwitch.isEnabled = true
            if (annotate && uri != null && !isFinishing && !isDestroyed) {
                setExportUi(true)
                try { videoExporter.start(uri, savedBaseName, savedFps) }
                catch (e: Exception) {
                    setExportUi(false)
                    exportStatus.text = "MP4 overlay failed: ${e.message}. Original recording kept."
                }
            }
        }
    }

    private fun setExportUi(busy: Boolean) {
        recordButton.isEnabled = !busy && activityResumed && session != null
        modeSpinner.isEnabled = !busy && !recording
        embedTrackingSwitch.isEnabled = !busy && !recording
        cancelExportButton.visibility = if (busy) View.VISIBLE else View.GONE
        // Export re-runs Python on every saved frame; suspend live sampling during that work.
        tracking.setResumed(activityResumed && !busy)
        if (!busy && activityResumed) tryOpenCamera()
    }

    private fun saveCsv(name: String, text: String): Boolean = try {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, "text/csv")
            put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/FastCam")
        }
        val uri = contentResolver.insert(MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
        if (uri != null) {
            contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) }
            true
        } else false
    } catch (e: Exception) {
        false
    }

    // ---------------------------------------------------------------- UI helpers

    private fun displayRotationDegrees(): Int = when (display?.rotation) {
            Surface.ROTATION_90 -> 90
            Surface.ROTATION_180 -> 180
            Surface.ROTATION_270 -> 270
            else -> 0
        }

    private fun previewRotation(): Int = (sensorOrientation - displayRotationDegrees() + 360) % 360

    /** Explicit rotation and aspect-fit: sampled pixels and the overlay share this geometry. */
    private fun updatePreviewLayout() {
        val mode = currentMode ?: return
        val parent = textureView.parent as View
        if (parent.width == 0 || parent.height == 0) return
        val angle = previewRotation()
        val (displayW, displayH) = PreviewCoordinates.displaySize(mode.size.width, mode.size.height, angle)
        val scale = minOf(parent.width.toDouble() / displayW, parent.height.toDouble() / displayH)
        val w = (displayW * scale).roundToInt().coerceAtLeast(1)
        val h = (displayH * scale).roundToInt().coerceAtLeast(1)
        textureView.layoutParams = FrameLayout.LayoutParams(w, h, Gravity.CENTER)
        puckOverlay.layoutParams = FrameLayout.LayoutParams(w, h, Gravity.CENTER)
        // Camera2's SurfaceTexture producer transform already applies SENSOR_ORIENTATION.
        // Applying `angle` here rotates the image twice (a sideways portrait preview).
        // Only compensate the remaining display rotation, while `angle` above still
        // controls the fitted aspect ratio and the tracker-to-recording coordinate map.
        val source = floatArrayOf(0f, 0f, w.toFloat(), 0f, 0f, h.toFloat())
        val target = when (PreviewCoordinates.textureRotation(displayRotationDegrees())) {
            90 -> floatArrayOf(w.toFloat(), 0f, w.toFloat(), h.toFloat(), 0f, 0f)
            180 -> floatArrayOf(w.toFloat(), h.toFloat(), 0f, h.toFloat(), w.toFloat(), 0f)
            270 -> floatArrayOf(0f, h.toFloat(), 0f, 0f, w.toFloat(), h.toFloat())
            else -> source
        }
        textureView.setTransform(Matrix().apply { setPolyToPoly(source, 0, target, 0, 3) })
        tracking.configure(mode.size.width, mode.size.height, angle)
    }

    private fun updateShutterButton() {
        val mode = currentMode
        if (mode == null || mode.highSpeed || !manualSensorSupported) {
            shutterButton.isEnabled = false
            shutterButton.text = if (mode?.highSpeed == true) "Shutter: Auto\n(locked in high-speed)" else "Shutter: Auto"
            return
        }
        shutterButton.isEnabled = true
        val exp = SHUTTER_OPTIONS[shutterIndex]
        shutterButton.text = if (exp == null) "Shutter: Auto" else "Shutter: 1/${1_000_000_000L / exp}"
    }

    private fun updateInfo() {
        val mode = currentMode ?: return
        val skewMs = lastSkewNs / 1e6
        val exp = lastExposureNs
        val expText = if (exp > 0) "1/${(1e9 / exp).toInt()}s" else "-"
        val sb = StringBuilder()
        sb.append(mode.label).append('\n')
        sb.append("Rolling shutter: ").append(if (lastSkewNs > 0) "%.2f ms".format(skewMs) else "not reported").append('\n')
        sb.append("Exposure: $expText   ISO $lastIso   ").append("%.1f fps".format(fpsEma))
        if (recording) {
            val secs = (SystemClock.uptimeMillis() - recordStartMs) / 1000
            sb.append("\n● REC %d:%02d   %d frames logged".format(secs / 60, secs % 60, framesLogged))
        }
        infoText.text = sb.toString()
    }

    private fun toast(msg: String) = runOnUiThread { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }
}
