package com.example.fastcam

import java.nio.ByteBuffer
import kotlin.math.abs

/** Source-only checks: run on the build machine, not part of an Android build here. */
object FastTrackingMathTest {
    @JvmStatic fun main(args: Array<String>) {
        val w = 64
        val h = 40
        fun disk(cx: Int, cy: Int, radius: Int): ByteBuffer {
            val buffer = ByteBuffer.allocate(w*h*4)
            for (y in 0 until h) for (x in 0 until w) {
                if ((x-cx)*(x-cx)+(y-cy)*(y-cy) <= radius*radius)
                    buffer.put(((h-1-y)*w+x)*4, 255.toByte())
            }
            return buffer
        }
        val detector = PuckMaskDetector(w,h)
        val hit = detector.detect(disk(15,12,3),1_000_000_000L)!!
        check(abs(hit.x-15) < 0.01 && abs(hit.y-12) < 0.01) // catches GL row reversal
        check(detector.detect(disk(15,12,3),1_000_000_000L) == null) // duplicate capture
        check(detector.detect(ByteBuffer.allocate(w*h*4),1_010_000_000L) == null)
        val reacquired = detector.detect(disk(50,30,3),1_300_000_000L)!!
        check(abs(reacquired.x-50) < 0.01) // elapsed-time reacquisition
        check(PuckMaskDetector(w,h).detect(ByteBuffer.allocate(w*h*4).apply { put(0,255.toByte()) },1L) == null)
        val rate = FrameRateWindow()
        for (i in 0..120) rate.add(1_000_000_000L+i*8_333_333L)
        check(abs(rate.rate(2_000_000_000L)-120.0) < 0.01)
        check(rate.rate(4_000_000_000L) == 0.0) // stalls must not leave a stale high FPS
        for (rotation in listOf(0,90,180,270)) {
            val preview = PreviewCoordinates.toPreview(0.2,0.7,rotation)
            val sensor = PreviewCoordinates.toSensor(preview.first,preview.second,rotation)
            check(abs(sensor.first-0.2) < 1e-9 && abs(sensor.second-0.7) < 1e-9)
        }
    }
}
