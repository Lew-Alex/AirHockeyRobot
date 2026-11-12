package com.example.fastcam

/** Dependency-free executable checks for ExposureControl. Source-only; not run as part of this change. */
object ExposureControlTest {
    @JvmStatic
    fun main(args: Array<String>) {
        val minNs = 100_000L
        val sensorMaxNs = 100_000_000L
        val frameNs = 16_666_666L

        check(ExposureControl.exposureForProgress(0, minNs, sensorMaxNs, frameNs) == null)
        check(ExposureControl.exposureForProgress(1, minNs, sensorMaxNs, frameNs) == frameNs)
        check(ExposureControl.exposureForProgress(1000, minNs, sensorMaxNs, frameNs) == minNs)
        check(ExposureControl.exposureForProgress(-50, minNs, sensorMaxNs, frameNs) == null)
        check(ExposureControl.exposureForProgress(5000, minNs, sensorMaxNs, frameNs) == minNs)

        val slower = ExposureControl.exposureForProgress(250, minNs, sensorMaxNs, frameNs)!!
        val faster = ExposureControl.exposureForProgress(750, minNs, sensorMaxNs, frameNs)!!
        check(slower in minNs..frameNs && faster in minNs..frameNs && slower > faster)

        check(ExposureControl.progressForExposure(null, minNs, sensorMaxNs, frameNs) == 0)
        check(ExposureControl.progressForExposure(frameNs, minNs, sensorMaxNs, frameNs) == 1)
        check(ExposureControl.progressForExposure(minNs, minNs, sensorMaxNs, frameNs) == 1000)
        check(ExposureControl.progressForExposure(1L, minNs, sensorMaxNs, frameNs) == 1000)

        // A one-value feasible interval is legal at every manual slider position.
        for (progress in 1..1000 step 100) {
            check(ExposureControl.exposureForProgress(progress, 8_000_000L, 20_000_000L, 8_000_000L) == 8_000_000L)
        }
        check(ExposureControl.exposureForProgress(1, 10_000_000L, 20_000_000L, 9_000_000L) == null)
        check(ExposureControl.exposureForProgress(1, 0L, 20_000_000L, frameNs) == null)
        check(ExposureControl.exposureForProgress(1, 20_000_000L, 10_000_000L, frameNs) == null)

        check(ExposureControl.labelForExposureNs(null) == "Auto")
        check(ExposureControl.labelForExposureNs(2_000_000L) == "2000000 ns (1/500 s)")
    }
}
