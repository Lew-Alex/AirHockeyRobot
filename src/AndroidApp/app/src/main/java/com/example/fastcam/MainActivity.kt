package com.example.fastcam

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Matrix
import android.graphics.SurfaceTexture
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
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
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
import android.widget.Toast
import java.util.concurrent.Executor
import kotlin.math.roundToInt

/** Native camera preview and USB puck-coordinate stream; one camera output. */
class MainActivity : Activity() {
    data class Mode(val size: Size, val fps: Int, val fpsRange: Range<Int>, val highSpeed: Boolean) {
        val label: String get() = "${size.width} × ${size.height} · $fps fps" + if (highSpeed) " (high-speed)" else ""
    }

    private lateinit var preview: TextureView
    private lateinit var ring: PuckOverlayView
    private lateinit var usbButton: Button
    private lateinit var previewButton: Button
    private lateinit var modeSpinner: Spinner
    private lateinit var manager: CameraManager
    private lateinit var characteristics: CameraCharacteristics
    private var cameraId = ""
    private var modes: List<Mode> = emptyList()
    @Volatile private var currentMode: Mode? = null
    @Volatile private var usbEnabled = false
    @Volatile private var previewEnabled = true
    @Volatile private var resumed = false
    @Volatile private var outputAvailable = false
    @Volatile private var pipeline: FastPuckPipeline? = null
    @Volatile private var sessionGeneration = 0
    @Volatile private var metadataFps = 0.0
    private var thread: HandlerThread? = null
    private var cameraHandler: Handler? = null
    private var camera: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var opening = false
    private var deviceGeneration = 0
    private var previousSensorTimestamp = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        preview = findViewById(R.id.preview)
        ring = findViewById(R.id.puckOverlay)
        usbButton = findViewById(R.id.fastTrackingSwitch)
        previewButton = findViewById(R.id.fastPreviewSwitch)
        modeSpinner = findViewById(R.id.modeSpinner)
        manager = getSystemService(CameraManager::class.java)
        try {
            if (!pickCamera()) throw IllegalStateException("No back camera found")
            modes = buildModes()
            if (modes.isEmpty()) throw IllegalStateException("No supported camera modes found")
        } catch (error: Exception) {
            usbButton.isEnabled = false
            previewButton.isEnabled = false
            toast(error.message ?: "Camera unavailable")
            return
        }
        val default = modes.indexOfFirst { it.highSpeed && it.fps == 120 && it.size == Size(1280,720) }
            .takeIf { it >= 0 } ?: modes.indexOfFirst { it.highSpeed && it.size == Size(1280,720) }
            .takeIf { it >= 0 } ?: modes.indexOfFirst { it.fps == 60 && it.size == Size(1280,720) }
            .takeIf { it >= 0 } ?: 0
        currentMode = modes[default]
        modeSpinner.adapter = ArrayAdapter(this,android.R.layout.simple_spinner_dropdown_item,modes.map { it.label })
        modeSpinner.setSelection(default)
        modeSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (currentMode == modes[position]) return
                currentMode = modes[position]
                ring.clear()
                fitPreview()
                cameraHandler?.post { restartCamera() }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
        usbButton.setOnClickListener {
            usbEnabled = !usbEnabled
            pipeline?.setTrackingEnabled(usbEnabled)
            if (!usbEnabled) ring.clear()
            updateButtons()
            if (usbEnabled && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(arrayOf(Manifest.permission.CAMERA),1)
            applyCameraState()
        }
        previewButton.setOnClickListener {
            previewEnabled = !previewEnabled
            pipeline?.setPreviewEnabled(previewEnabled)
            if (!previewEnabled) ring.clear()
            updateButtons()
            if (previewEnabled && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(arrayOf(Manifest.permission.CAMERA),1)
            applyCameraState()
        }
        updateButtons()
        preview.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(surface: SurfaceTexture,width: Int,height: Int) {
                outputAvailable = true; fitPreview(); tryOpenCamera()
            }
            override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture,width: Int,height: Int) { fitPreview() }
            override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
                outputAvailable = false
                pipeline?.stopStreaming()
                val handler = cameraHandler
                if (handler != null) handler.post {
                    val previous = pipeline
                    closeCamera()
                    releaseOutput(surface,previous)
                } else releaseOutput(surface,pipeline)
                return false // EGL must disconnect before releasing this TextureView buffer queue.
            }
            override fun onSurfaceTextureUpdated(surface: SurfaceTexture) {}
        }
        findViewById<View>(R.id.previewContainer).addOnLayoutChangeListener { _,l,t,r,b,ol,ot,or,ob ->
            if (r-l != or-ol || b-t != ob-ot) fitPreview()
        }
        preview.post { fitPreview() }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.CAMERA),1)
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        if (modes.isEmpty()) return
        thread = HandlerThread("camera").also { it.start() }
        cameraHandler = Handler(thread!!.looper)
        tryOpenCamera()
    }

    override fun onPause() {
        resumed = false
        pipeline?.stopStreaming()
        ring.clear()
        val worker = thread
        cameraHandler?.post { closeCamera() }
        worker?.quitSafely()
        try { worker?.join(3000) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
        thread = null
        cameraHandler = null
        super.onPause()
    }

    override fun onDestroy() { pipeline?.close(); super.onDestroy() }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code,permissions,results)
        if (code == 1) {
            if (results.firstOrNull() == PackageManager.PERMISSION_GRANTED) tryOpenCamera()
            else {
                usbEnabled = false; previewEnabled = false; updateButtons()
                toast("Camera permission is needed for preview and tracking")
            }
        }
    }

    private fun updateButtons() {
        usbButton.text = if (usbEnabled) "USB tracking: On" else "USB tracking: Off"
        usbButton.isSelected = usbEnabled
        usbButton.stateDescription = if (usbEnabled) "On" else "Off"
        previewButton.text = if (previewEnabled) "Preview: On" else "Preview: Off"
        previewButton.isSelected = previewEnabled
        previewButton.stateDescription = if (previewEnabled) "On" else "Off"
    }

    private fun applyCameraState() {
        if (!usbEnabled && !previewEnabled) cameraHandler?.post { closeCamera() }
        else tryOpenCamera()
    }

    private fun pickCamera(): Boolean {
        val back = manager.cameraIdList.filter {
            manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        }
        cameraId = back.firstOrNull {
            manager.getCameraCharacteristics(it).get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)
                ?.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO) == true
        } ?: back.firstOrNull() ?: return false
        characteristics = manager.getCameraCharacteristics(cameraId)
        return true
    }

    private fun buildModes(): List<Mode> {
        val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return emptyList()
        val output = mutableListOf<Mode>()
        val caps = characteristics.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
        if (caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO)) {
            for (size in map.highSpeedVideoSizes) for (range in map.getHighSpeedVideoFpsRangesFor(size)) {
                if (range.lower == range.upper && range.upper >= 120) output.add(Mode(size,range.upper,range,true))
            }
        }
        val sizes = map.getOutputSizes(SurfaceTexture::class.java)?.toSet() ?: emptySet()
        val ranges = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES) ?: emptyArray()
        val preferredSizes = listOf(Size(3840,2160),Size(1920,1080),Size(1280,720),Size(640,480)).filter { it in sizes }
            .ifEmpty { sizes.sortedBy { it.width.toLong()*it.height }.take(1) }
        for (fps in ranges.map { it.upper }.distinct().filter { it >= 30 }.sortedDescending()) {
            val range = ranges.firstOrNull { it.lower == fps && it.upper == fps }
                ?: ranges.filter { it.upper == fps }.maxByOrNull { it.lower } ?: continue
            for (size in preferredSizes) {
                val minDuration = map.getOutputMinFrameDuration(SurfaceTexture::class.java,size)
                if (minDuration == 0L || minDuration <= 1_000_000_000L/fps+100_000L)
                    output.add(Mode(size,fps,range,false))
            }
        }
        return output.distinct().sortedWith(compareByDescending<Mode> { it.fps }.thenByDescending { it.highSpeed }.thenByDescending { it.size.width })
    }

    @SuppressLint("MissingPermission")
    private fun tryOpenCamera() {
        if (!resumed || !outputAvailable || currentMode == null || !preview.isAvailable || (!usbEnabled && !previewEnabled)) return
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return
        val handler = cameraHandler ?: return
        handler.post {
            if (!resumed || !outputAvailable || (!usbEnabled && !previewEnabled) || camera != null || opening) return@post
            opening = true
            val generation = deviceGeneration
            try {
                manager.openCamera(cameraId,object : CameraDevice.StateCallback() {
                    override fun onOpened(device: CameraDevice) {
                        if (generation != deviceGeneration || !resumed || !outputAvailable) { device.close(); return }
                        opening = false
                        camera = device
                        startSession(device)
                    }
                    override fun onDisconnected(device: CameraDevice) {
                        device.close()
                        if (generation == deviceGeneration) cameraFailed("Camera disconnected")
                    }
                    override fun onError(device: CameraDevice,error: Int) {
                        device.close()
                        if (generation == deviceGeneration) cameraFailed("Camera error $error. Try another mode.")
                    }
                },handler)
            } catch (error: Exception) { opening = false; cameraFailed(error.message ?: "Could not open camera") }
        }
    }

    private fun startSession(device: CameraDevice) {
        if (!outputAvailable) return
        val mode = currentMode ?: return
        val texture = preview.surfaceTexture ?: return
        val handler = cameraHandler ?: return
        val generation = ++sessionGeneration
        val previous = pipeline
        if (previous != null && !previous.awaitReleased()) { cameraFailed("Camera is still stopping. Try again."); return }
        val realtime = characteristics.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
        val next = FastPuckPipeline(mode.size.width,mode.size.height,previewRotation(),displayRotation(),realtime,
            mode.fps,texture,{ metadataFps },
            onReady = { surface -> handler.post {
                if (generation == sessionGeneration && resumed && camera === device && pipeline?.isRunning == true) {
                    val configuration = OutputConfiguration(surface).apply {
                        if (Build.VERSION.SDK_INT >= 33) setTimestampBase(OutputConfiguration.TIMESTAMP_BASE_SENSOR)
                    }
                    try {
                        device.createCaptureSession(SessionConfiguration(
                            if (mode.highSpeed) SessionConfiguration.SESSION_HIGH_SPEED else SessionConfiguration.SESSION_REGULAR,
                            listOf(configuration),Executor { handler.post(it) },object : CameraCaptureSession.StateCallback() {
                                override fun onConfigured(configured: CameraCaptureSession) {
                                    if (generation != sessionGeneration || !resumed || !outputAvailable ||
                                        camera !== device || pipeline?.isRunning != true) { configured.close(); return }
                                    session = configured
                                    previousSensorTimestamp = 0L
                                    metadataFps = 0.0
                                    startRequests(device,configured,surface,mode)
                                }
                                override fun onConfigureFailed(failed: CameraCaptureSession) {
                                    failed.close()
                                    if (generation == sessionGeneration) cameraFailed("Camera refused ${mode.label}. Choose another mode.")
                                }
                            }))
                    } catch (error: Exception) { if (generation == sessionGeneration) cameraFailed(error.message ?: "Session failed") }
                }
            } },
            onSample = { sample -> runOnUiThread {
                if (generation == sessionGeneration && resumed && previewEnabled && usbEnabled && sample.previewRendered) {
                    if (sample.previewX != null && sample.previewY != null)
                        ring.show(sample.previewX,sample.previewY,sample.radiusX,sample.radiusY)
                    else ring.clear()
                }
            } },
            onError = { message -> handler.post { if (generation == sessionGeneration) cameraFailed(message) } })
        pipeline = next
        next.setTrackingEnabled(usbEnabled)
        next.setPreviewEnabled(previewEnabled)
        next.resize(preview.width,preview.height)
        next.start()
    }

    private fun startRequests(device: CameraDevice,configured: CameraCaptureSession,surface: Surface,mode: Mode) {
        try {
            val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(surface)
                set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,mode.fpsRange)
                set(CaptureRequest.CONTROL_AF_MODE,CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO)
                if (!mode.highSpeed) set(CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE,CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE_OFF)
            }.build()
            if (configured is CameraConstrainedHighSpeedCaptureSession)
                configured.setRepeatingBurst(configured.createHighSpeedRequestList(request),captureCallback,cameraHandler)
            else configured.setRepeatingRequest(request,captureCallback,cameraHandler)
        } catch (error: Exception) { cameraFailed(error.message ?: "Camera request failed") }
    }

    private val captureCallback = object : CameraCaptureSession.CaptureCallback() {
        override fun onCaptureCompleted(active: CameraCaptureSession,request: CaptureRequest,result: TotalCaptureResult) {
            if (active !== session) return
            val timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP) ?: return
            if (previousSensorTimestamp > 0 && timestamp > previousSensorTimestamp) {
                val fps = 1e9/(timestamp-previousSensorTimestamp)
                metadataFps = if (metadataFps == 0.0) fps else metadataFps*0.95+fps*0.05
            }
            previousSensorTimestamp = timestamp
        }
    }

    /** Camera thread; disconnect Camera2 before releasing/reconnecting the EGL producer. */
    private fun closeCamera(): Boolean {
        sessionGeneration++
        deviceGeneration++
        try { session?.close() } catch (_: Exception) {}
        session = null
        camera?.close()
        camera = null
        opening = false
        val previous = pipeline
        previous?.close()
        val released = previous?.awaitReleased() ?: true
        if (released) pipeline = null
        return released
    }

    private fun restartCamera() {
        if (closeCamera()) runOnUiThread { tryOpenCamera() }
        else toast("Camera is still stopping. Try again.")
    }

    private fun releaseOutput(surface: SurfaceTexture,previous: FastPuckPipeline?) {
        Thread({
            if (previous == null || previous.awaitReleased(Long.MAX_VALUE)) surface.release()
        },"preview-release").apply { isDaemon = true; start() }
    }

    private fun cameraFailed(message: String) {
        closeCamera()
        runOnUiThread { usbEnabled = false; previewEnabled = false; ring.clear(); updateButtons(); toast(message) }
    }

    private fun displayRotation(): Int = when (display?.rotation) {
        Surface.ROTATION_90 -> 90
        Surface.ROTATION_180 -> 180
        Surface.ROTATION_270 -> 270
        else -> 0
    }
    private fun previewRotation() = ((characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 90)-displayRotation()+360)%360

    private fun fitPreview() {
        val mode = currentMode ?: return
        val parent = preview.parent as View
        if (parent.width == 0 || parent.height == 0) return
        val (w,h) = PreviewCoordinates.displaySize(mode.size.width,mode.size.height,previewRotation())
        val scale = minOf(parent.width.toDouble()/w,parent.height.toDouble()/h)
        val width = (w*scale).roundToInt().coerceAtLeast(1)
        val height = (h*scale).roundToInt().coerceAtLeast(1)
        preview.layoutParams = FrameLayout.LayoutParams(width,height,Gravity.CENTER)
        ring.layoutParams = FrameLayout.LayoutParams(width,height,Gravity.CENTER)
        preview.setTransform(Matrix())
        pipeline?.resize(width,height)
    }

    private fun toast(message: String) = runOnUiThread { Toast.makeText(this,message,Toast.LENGTH_LONG).show() }
}
