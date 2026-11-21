import com.example.fastcam.SamplingCadence

/** Pure Kotlin cadence checks; this source has no Android dependencies. */
object SamplingCadenceTest {
    @JvmStatic
    fun main(args: Array<String>) {
        sixtyHzJitterKeepsThirtyHzTarget()
        thirtyHzJitterDoesNotSkipBoundaryFrames()
        previewTargetsSixtyAcrossCameraModes()
        stallsSkipMissedSlots()
        backwardsClockAndDuplicateCallbacksReanchorSafely()
        println("Sampling cadence tests passed")
    }

    private fun previewTargetsSixtyAcrossCameraModes() {
        for (cameraFps in listOf(60,120,240)) {
            val cadence = SamplingCadence(16_666_667L)
            var accepted = 0
            for (frame in 0 until cameraFps*10) {
                val jitter = (frame%3-1)*200_000L
                if (cadence.tryClaim(frame*1_000_000_000L/cameraFps+jitter)) accepted++
            }
            check(accepted in 598..602) { "Preview target from $cameraFps fps camera: $accepted samples in 10s" }
        }
    }

    private fun sixtyHzJitterKeepsThirtyHzTarget() {
        val cadence = SamplingCadence()
        var accepted = 0
        for (frame in 0 until 600) {
            val jitter = if (frame % 2 == 0) 200_000L else -200_000L
            val now = frame * 16_666_667L + jitter
            if (cadence.tryClaim(now)) accepted++
        }
        check(accepted in 298..302) { "60 Hz jitter should produce about 30 samples/s, got $accepted" }
    }

    private fun thirtyHzJitterDoesNotSkipBoundaryFrames() {
        val cadence = SamplingCadence()
        var accepted = 0
        for (frame in 0 until 300) {
            val jitter = when (frame % 3) {
                0 -> -500_000L
                1 -> 350_000L
                else -> 0L
            }
            if (cadence.tryClaim(frame * 33_333_333L + jitter)) accepted++
        }
        check(accepted == 300) { "30 Hz boundary jitter skipped samples: $accepted/300" }
    }

    private fun stallsSkipMissedSlots() {
        val cadence = SamplingCadence()
        check(cadence.tryClaim(0L))
        check(cadence.tryClaim(1_000_000_000L))
        check(!cadence.tryClaim(1_000_000_001L)) { "stall caused a catch-up sample" }
        check(cadence.tryClaim(1_033_000_000L)) { "anchored cadence did not resume after stall" }
    }

    private fun backwardsClockAndDuplicateCallbacksReanchorSafely() {
        val cadence = SamplingCadence()
        check(cadence.tryClaim(5_000_000_000L))
        check(cadence.tryClaim(4_000_000_000L)) { "backwards clock did not reanchor" }
        check(!cadence.tryClaim(4_000_000_000L)) { "duplicate callback was accepted" }
        check(!cadence.tryClaim(4_032_000_000L)) { "callback outside tolerance was accepted" }
        check(cadence.tryClaim(4_033_100_000L))
        cadence.reset()
        check(cadence.tryClaim(4_033_100_000L)) { "reset did not start a fresh cadence" }
    }
}
