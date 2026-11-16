package com.example.fastcam

import java.nio.ByteBuffer

/** JNI consumes the existing direct packed mask; no frame-sized Java copy or Python. */
class NativePuckDetector private constructor(private var handle: Long) : AutoCloseable {
    private val result = DoubleArray(4)

    fun detect(mask: ByteBuffer, timestampNs: Long, rowStride: Int, pixelStride: Int): PuckMaskDetector.Hit? {
        check(handle != 0L) { "Native detector is closed" }
        require(mask.isDirect) { "Native detector requires a direct mask" }
        if (!bindings.detect(handle,mask,rowStride,pixelStride,timestampNs,result)) return null
        return PuckMaskDetector.Hit(result[0],result[1],result[2],result[3])
    }

    /** Called on the GL worker after processing stops. */
    override fun close() {
        if (handle != 0L) { bindings.destroy(handle); handle = 0L }
    }

    companion object {
        private val bindings = PuckNativeBindings()
        private val loadError: String? by lazy {
            try { System.loadLibrary("puck_native"); null }
            catch (error: UnsatisfiedLinkError) { error.message ?: "Native library unavailable" }
            catch (error: SecurityException) { error.message ?: "Native library could not load" }
        }
        val unavailableReason: String? get() = loadError
        fun createOrNull(width: Int, height: Int): NativePuckDetector? {
            if (loadError != null) return null
            return try {
                val handle = bindings.create(width,height)
                check(handle != 0L) { "Native detector allocation failed" }
                NativePuckDetector(handle)
            } catch (_: UnsatisfiedLinkError) { null }
        }
    }
}

/** Separate instance methods keep JNI symbol names independent of Kotlin companion bridges. */
class PuckNativeBindings {
    external fun create(width: Int,height: Int): Long
    external fun detect(handle: Long,mask: ByteBuffer,rowStride: Int,pixelStride: Int,timestampNs: Long,result: DoubleArray): Boolean
    external fun destroy(handle: Long)
}
