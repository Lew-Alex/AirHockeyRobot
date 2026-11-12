package com.example.fastcam

import android.graphics.SurfaceTexture
import android.opengl.EGL14
import android.opengl.EGLConfig
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLSurface
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.view.Surface
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

/** Experimental single-camera-output path: camera -> external GL texture -> yellow mask.
 * GPU thresholds a <=640px image; Kotlin labels components and publishes measured centres.
 * Preview rendering is capped at 30Hz, independently of frame consumption/detection/USB.
 * No recorder/Python/TextureView readback is involved. Actual throughput is device dependent.
 */
class FastPuckPipeline(
    private val sensorWidth: Int,
    private val sensorHeight: Int,
    private val rotation: Int,
    private val displayRotation: Int,
    private val timestampRealtime: Boolean,
    private val requestedFps: Int,
    private val outputTexture: SurfaceTexture,
    private val cameraFps: () -> Double,
    private val onReady: (Surface) -> Unit,
    private val onSample: (Sample) -> Unit,
    private val onError: (String) -> Unit
) {
    data class Sample(
        val x: Double?, val y: Double?, val xNormalized: Double?, val yNormalized: Double?,
        val previewX: Double?, val previewY: Double?, val radiusX: Double, val radiusY: Double,
        val sourceFps: Double, val analysisFps: Double, val detectedFps: Double,
        val processingMs: Double, val frameAgeMs: Double?
    )

    private val thread = HandlerThread("puck-gpu").apply { start() }
    private val handler = Handler(thread.looper)
    private val stopped = AtomicBoolean(false)
    private val closing = AtomicBoolean(false)
    private val released = CountDownLatch(1)
    private val output = PuckCoordinateServer { fail(it) }
    private val sourceRate = FrameRateWindow()
    private val analysisRate = FrameRateWindow()
    private val detectedRate = FrameRateWindow()
    private val matrix = FloatArray(16)
    private val dims = PreviewCoordinates.displaySize(sensorWidth, sensorHeight, rotation)
    private val scale = minOf(1.0, 640.0 / maxOf(dims.first, dims.second))
    private val maskWidth = (dims.first * scale).roundToInt().coerceAtLeast(1)
    private val maskHeight = (dims.second * scale).roundToInt().coerceAtLeast(1)
    private val pixels = ByteBuffer.allocateDirect(maskWidth * maskHeight * 4).order(ByteOrder.nativeOrder())
    private val detector = PuckMaskDetector(maskWidth, maskHeight)
    private val vertices: FloatBuffer = ByteBuffer.allocateDirect(16 * 4).order(ByteOrder.nativeOrder())
        .asFloatBuffer().apply {
            put(floatArrayOf(-1f,-1f, 0f,0f, 1f,-1f, 1f,0f, -1f,1f, 0f,1f, 1f,1f, 1f,1f)); position(0)
        }
    private var display: EGLDisplay = EGL14.EGL_NO_DISPLAY
    private var context: EGLContext = EGL14.EGL_NO_CONTEXT
    private var pbuffer: EGLSurface = EGL14.EGL_NO_SURFACE
    private var window: EGLSurface = EGL14.EGL_NO_SURFACE
    private var windowSurface: Surface? = null
    private var input: SurfaceTexture? = null
    private var cameraSurface: Surface? = null
    private var cameraTexture = 0
    private var maskTexture = 0
    private var framebuffer = 0
    private var program = 0
    private var frameId = 0L
    private var lastCaptureNs = 0L
    private var lastDisplayNs = 0L
    private var lastUiNs = 0L
    @Volatile private var windowWidth = 1
    @Volatile private var windowHeight = 1
    val isRunning: Boolean get() = !stopped.get()

    fun resize(width: Int, height: Int) {
        windowWidth = maxOf(1, width); windowHeight = maxOf(1, height)
        handler.post { if (!stopped.get() && window != EGL14.EGL_NO_SURFACE) outputTexture.setDefaultBufferSize(windowWidth, windowHeight) }
    }

    fun start() { handler.post {
        if (stopped.get()) return@post
        try { initialize(); if (!stopped.get()) { output.start(); onReady(cameraSurface!!) } }
        catch (error: Exception) { fail("GPU setup: ${error.message}") }
    } }

    /** Stops the listener synchronously so the Python path can immediately reclaim port 8765. */
    fun stopStreaming() {
        stopped.set(true)
        output.stop()
    }

    fun close() {
        stopStreaming()
        if (closing.getAndSet(true)) return
        handler.post {
            try { releaseGl() }
            finally { released.countDown(); thread.quitSafely() }
        }
    }

    /** Camera-thread only. Do not reconnect a second producer before EGL disconnects. */
    fun awaitReleased(): Boolean = released.await(1500, TimeUnit.MILLISECONDS)

    private fun fail(message: String) {
        if (!stopped.getAndSet(true)) {
            output.stop()
            onError(message)
            // Owner closes Camera2 first, then calls close(). An asynchronous TCP
            // bind failure must not release a Surface while onReady is configuring it.
        }
    }

    private fun initialize() {
        display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
        check(display != EGL14.EGL_NO_DISPLAY) { "No EGL display" }
        val versions = IntArray(2)
        check(EGL14.eglInitialize(display, versions, 0, versions, 1)) { "EGL initialization failed" }
        val configAttrs = intArrayOf(EGL14.EGL_RED_SIZE,8, EGL14.EGL_GREEN_SIZE,8, EGL14.EGL_BLUE_SIZE,8,
            EGL14.EGL_ALPHA_SIZE,8, EGL14.EGL_RENDERABLE_TYPE,EGL14.EGL_OPENGL_ES2_BIT,
            EGL14.EGL_SURFACE_TYPE,EGL14.EGL_WINDOW_BIT or EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE)
        val configs = arrayOfNulls<EGLConfig>(1)
        val count = IntArray(1)
        check(EGL14.eglChooseConfig(display, configAttrs,0,configs,0,1,count,0) && count[0] > 0) { "No EGL configuration" }
        val config = configs[0]!!
        context = EGL14.eglCreateContext(display,config,EGL14.EGL_NO_CONTEXT,intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE),0)
        check(context != EGL14.EGL_NO_CONTEXT) { "No GL context" }
        pbuffer = EGL14.eglCreatePbufferSurface(display,config,intArrayOf(EGL14.EGL_WIDTH,1,EGL14.EGL_HEIGHT,1,EGL14.EGL_NONE),0)
        check(pbuffer != EGL14.EGL_NO_SURFACE) { "No EGL pbuffer" }
        makeCurrent(pbuffer)
        outputTexture.setDefaultBufferSize(windowWidth, windowHeight)
        windowSurface = Surface(outputTexture)
        window = EGL14.eglCreateWindowSurface(display,config,windowSurface,intArrayOf(EGL14.EGL_NONE),0)
        check(window != EGL14.EGL_NO_SURFACE) { "No preview EGL surface" }
        makeCurrent(window)
        EGL14.eglSwapInterval(display, 0) // applies to the window, not the pbuffer
        makeCurrent(pbuffer)
        program = createProgram()
        val ids = IntArray(1)
        GLES20.glGenTextures(1,ids,0)
        cameraTexture = ids[0]
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,cameraTexture)
        textureParameters(GLES11Ext.GL_TEXTURE_EXTERNAL_OES)
        input = SurfaceTexture(cameraTexture).apply {
            setDefaultBufferSize(sensorWidth,sensorHeight)
            setOnFrameAvailableListener({ processFrame() },handler)
        }
        cameraSurface = Surface(input!!)
        GLES20.glGenTextures(1,ids,0)
        maskTexture = ids[0]
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,maskTexture)
        textureParameters(GLES20.GL_TEXTURE_2D)
        GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D,0,GLES20.GL_RGBA,maskWidth,maskHeight,0,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,null)
        GLES20.glGenFramebuffers(1,ids,0)
        framebuffer = ids[0]
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER,framebuffer)
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,GLES20.GL_COLOR_ATTACHMENT0,GLES20.GL_TEXTURE_2D,maskTexture,0)
        check(GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) == GLES20.GL_FRAMEBUFFER_COMPLETE) { "Mask framebuffer incomplete" }
        GLES20.glDisable(GLES20.GL_DITHER)
        checkGl("initialize")
    }

    private fun processFrame() {
        if (stopped.get()) return
        try {
            val started = SystemClock.elapsedRealtimeNanos()
            makeCurrent(pbuffer)
            val texture = input ?: return
            texture.updateTexImage()
            val captureNs = texture.timestamp
            if (captureNs <= lastCaptureNs) return // coalesced callbacks are not new measurements
            lastCaptureNs = captureNs
            frameId++
            sourceRate.add(started)
            texture.getTransformMatrix(matrix)
            // Camera writes sensor orientation into this producer transform. Apply it
            // once here; our EGL copy has no camera transform of its own. See
            // developer.android.com/reference/androidx/camera/core/Preview.
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER,framebuffer)
            draw(maskWidth,maskHeight,true)
            pixels.position(0)
            GLES20.glReadPixels(0,0,maskWidth,maskHeight,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,pixels)
            checkGl("mask readback")
            val hit = detector.detect(pixels,captureNs)
            val completed = SystemClock.elapsedRealtimeNanos()
            analysisRate.add(completed)
            if (hit != null) detectedRate.add(completed)
            val processingMs = (completed-started)/1e6
            val u = hit?.let { (it.x+0.5)/maskWidth }
            val v = hit?.let { (it.y+0.5)/maskHeight }
            val sensorPoint = if (u != null && v != null) PreviewCoordinates.toSensor(u,v,rotation) else null
            val age = if (timestampRealtime && completed >= captureNs && completed-captureNs < 5_000_000_000L)
                (completed-captureNs)/1e6 else null
            val sample = Sample(sensorPoint?.first?.times(sensorWidth)?.minus(0.5),
                sensorPoint?.second?.times(sensorHeight)?.minus(0.5), sensorPoint?.first,sensorPoint?.second,
                u,v,(hit?.radius ?: 0.0)/maskWidth,(hit?.radius ?: 0.0)/maskHeight,
                sourceRate.rate(completed),analysisRate.rate(completed),detectedRate.rate(completed),processingMs,age)
            val json = JSONObject().apply {
                put("type","puck"); put("version",1); put("tracker","gpu_mask_experimental")
                put("frame_id",frameId); put("timestamp_ns",started); put("capture_timestamp_ns",captureNs)
                put("phone_publish_timestamp_ns",SystemClock.elapsedRealtimeNanos())
                put("timestamp_source",if (timestampRealtime) "REALTIME" else "UNKNOWN")
                put("detected",hit != null); put("coordinate_space","sensor_pixels")
                put("image_width",sensorWidth); put("image_height",sensorHeight); put("rotation_degrees",rotation)
                put("x",sample.x ?: JSONObject.NULL); put("y",sample.y ?: JSONObject.NULL)
                put("x_normalized",sample.xNormalized ?: JSONObject.NULL); put("y_normalized",sample.yNormalized ?: JSONObject.NULL)
                put("analysis_width",maskWidth); put("analysis_height",maskHeight)
                put("requested_fps",requestedFps); put("capture_fps",cameraFps())
                put("source_fps",sample.sourceFps); put("analysis_fps",sample.analysisFps); put("detected_fps",sample.detectedFps)
                put("processing_ms",processingMs); put("frame_age_ms",age ?: JSONObject.NULL)
            }.toString()
            output.publish(json) // never waits for the UI thread or socket writes
            if (completed-lastUiNs >= 33_333_333L) { lastUiNs = completed; onSample(sample) }
            if (completed-lastDisplayNs >= 33_333_333L) {
                lastDisplayNs = completed
                makeCurrent(window)
                GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER,0)
                draw(windowWidth,windowHeight,false)
                check(EGL14.eglSwapBuffers(display,window)) { "Preview swap failed" }
                // Swap can still block on some devices: source_fps will expose that cost.
            }
        } catch (error: Exception) { fail("GPU tracking: ${error.message}") }
    }

    private fun makeCurrent(surface: EGLSurface) {
        check(EGL14.eglMakeCurrent(display,surface,surface,context)) { "eglMakeCurrent failed" }
    }

    private fun draw(width: Int,height: Int,mask: Boolean) {
        GLES20.glViewport(0,0,width,height)
        GLES20.glUseProgram(program)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,cameraTexture)
        GLES20.glUniform1i(GLES20.glGetUniformLocation(program,"uCamera"),0)
        GLES20.glUniform1i(GLES20.glGetUniformLocation(program,"uMask"),if (mask) 1 else 0)
        GLES20.glUniform1i(GLES20.glGetUniformLocation(program,"uDisplayRotation"),PreviewCoordinates.textureRotation(displayRotation))
        GLES20.glUniformMatrix4fv(GLES20.glGetUniformLocation(program,"uTexture"),1,false,matrix,0)
        val position = GLES20.glGetAttribLocation(program,"aPosition")
        val uv = GLES20.glGetAttribLocation(program,"aUv")
        vertices.position(0); GLES20.glVertexAttribPointer(position,2,GLES20.GL_FLOAT,false,16,vertices)
        vertices.position(2); GLES20.glVertexAttribPointer(uv,2,GLES20.GL_FLOAT,false,16,vertices)
        GLES20.glEnableVertexAttribArray(position); GLES20.glEnableVertexAttribArray(uv)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP,0,4)
    }

    private fun textureParameters(target: Int) {
        GLES20.glTexParameteri(target,GLES20.GL_TEXTURE_MIN_FILTER,GLES20.GL_LINEAR)
        GLES20.glTexParameteri(target,GLES20.GL_TEXTURE_MAG_FILTER,GLES20.GL_LINEAR)
        GLES20.glTexParameteri(target,GLES20.GL_TEXTURE_WRAP_S,GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(target,GLES20.GL_TEXTURE_WRAP_T,GLES20.GL_CLAMP_TO_EDGE)
    }

    private fun createProgram(): Int {
        fun shader(type: Int,source: String): Int {
            val id = GLES20.glCreateShader(type)
            GLES20.glShaderSource(id,source); GLES20.glCompileShader(id)
            val ok = IntArray(1); GLES20.glGetShaderiv(id,GLES20.GL_COMPILE_STATUS,ok,0)
            if (ok[0] == 0) {
                val log = GLES20.glGetShaderInfoLog(id); GLES20.glDeleteShader(id); error(log)
            }
            return id
        }
        val vs = shader(GLES20.GL_VERTEX_SHADER,"""
            attribute vec2 aPosition; attribute vec2 aUv; varying vec2 vUv;
            void main() { gl_Position=vec4(aPosition,0.0,1.0); vUv=aUv; }
        """.trimIndent())
        val fs = try { shader(GLES20.GL_FRAGMENT_SHADER,"""
            #extension GL_OES_EGL_image_external : require
            precision highp float;
            uniform samplerExternalOES uCamera; uniform mat4 uTexture;
            uniform int uMask; uniform int uDisplayRotation; varying vec2 vUv;
            void main() {
                vec2 p=vec2(vUv.x,1.0-vUv.y);
                if (uDisplayRotation==90) p=vec2(p.y,1.0-p.x);
                else if (uDisplayRotation==180) p=vec2(1.0-p.x,1.0-p.y);
                else if (uDisplayRotation==270) p=vec2(1.0-p.y,p.x);
                vec2 uv=(uTexture*vec4(p.x,1.0-p.y,0.0,1.0)).xy;
                vec3 rgb=texture2D(uCamera,uv).rgb;
                if (uMask==0) { gl_FragColor=vec4(rgb,1.0); return; }
                float hi=max(rgb.r,max(rgb.g,rgb.b)); float lo=min(rgb.r,min(rgb.g,rgb.b));
                float delta=hi-lo; float hue=0.0;
                if (delta>0.00001) {
                    if (hi==rgb.r) hue=mod((rgb.g-rgb.b)/delta,6.0)*60.0;
                    else if (hi==rgb.g) hue=((rgb.b-rgb.r)/delta+2.0)*60.0;
                    else hue=((rgb.r-rgb.g)/delta+4.0)*60.0;
                }
                float saturation=delta/max(hi,0.00001);
                // Same yellow HSV bounds as Python (OpenCV hue units are half degrees).
                float yellow=(hue>=44.0 && hue<=80.0 && saturation>=90.0/255.0 && hi>=70.0/255.0)?1.0:0.0;
                gl_FragColor=vec4(yellow,yellow,yellow,1.0);
            }
        """.trimIndent()) } catch (error: Exception) { GLES20.glDeleteShader(vs); throw error }
        val id = GLES20.glCreateProgram()
        GLES20.glAttachShader(id,vs); GLES20.glAttachShader(id,fs); GLES20.glLinkProgram(id)
        GLES20.glDeleteShader(vs); GLES20.glDeleteShader(fs)
        val ok = IntArray(1); GLES20.glGetProgramiv(id,GLES20.GL_LINK_STATUS,ok,0)
        if (ok[0] == 0) { val log=GLES20.glGetProgramInfoLog(id); GLES20.glDeleteProgram(id); error(log) }
        return id
    }

    private fun checkGl(stage: String) {
        val error = GLES20.glGetError()
        check(error == GLES20.GL_NO_ERROR) { "$stage: GL error $error" }
    }

    private fun releaseGl() {
        input?.setOnFrameAvailableListener(null)
        cameraSurface?.release(); cameraSurface = null
        input?.release(); input = null
        if (display != EGL14.EGL_NO_DISPLAY) {
            if (pbuffer != EGL14.EGL_NO_SURFACE && context != EGL14.EGL_NO_CONTEXT &&
                EGL14.eglMakeCurrent(display,pbuffer,pbuffer,context)) {
                if (program != 0) GLES20.glDeleteProgram(program)
                GLES20.glDeleteTextures(2,intArrayOf(cameraTexture,maskTexture),0)
                GLES20.glDeleteFramebuffers(1,intArrayOf(framebuffer),0)
            }
            EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT)
            if (window != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display,window)
            if (pbuffer != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display,pbuffer)
            if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display,context)
            EGL14.eglTerminate(display)
            EGL14.eglReleaseThread()
        }
        windowSurface?.release(); windowSurface = null
    }
}
