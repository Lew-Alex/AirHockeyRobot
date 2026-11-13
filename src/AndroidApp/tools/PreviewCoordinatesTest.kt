package com.example.fastcam

/** Dependency-free executable checks for PreviewCoordinates. */
object PreviewCoordinatesTest {
    @JvmStatic
    fun main(args: Array<String>) {
        val rotations = listOf(0, 90, 180, 270)
        val points = listOf(
            0.0 to 0.0,
            1.0 to 0.0,
            0.0 to 1.0,
            1.0 to 1.0,
            0.5 to 0.5,
            0.25 to 0.75
        )
        val expected = mapOf(
            0 to listOf(0.0 to 0.0, 1.0 to 0.0, 0.0 to 1.0, 1.0 to 1.0, 0.5 to 0.5, 0.25 to 0.75),
            90 to listOf(0.0 to 1.0, 0.0 to 0.0, 1.0 to 1.0, 1.0 to 0.0, 0.5 to 0.5, 0.75 to 0.75),
            180 to listOf(1.0 to 1.0, 0.0 to 1.0, 1.0 to 0.0, 0.0 to 0.0, 0.5 to 0.5, 0.75 to 0.25),
            270 to listOf(1.0 to 0.0, 1.0 to 1.0, 0.0 to 0.0, 0.0 to 1.0, 0.5 to 0.5, 0.25 to 0.25)
        )

        for (rotation in rotations) {
            for ((index, point) in points.withIndex()) {
                val actual = PreviewCoordinates.toSensor(point.first, point.second, rotation)
                checkClose(expected.getValue(rotation)[index], actual, "rotation=$rotation point=$point")
                check(actual.first in 0.0..1.0 && actual.second in 0.0..1.0) {
                    "Mapped point is outside normalized sensor bounds: $actual"
                }
            }

            val size = PreviewCoordinates.displaySize(1920, 1080, rotation)
            val expectedSize = if (rotation == 90 || rotation == 270) 1080 to 1920 else 1920 to 1080
            check(size == expectedSize) { "rotation=$rotation expected size=$expectedSize, got=$size" }
        }

        checkFails("rotation") { PreviewCoordinates.toSensor(0.0, 0.0, 45) }
        checkFails("rotation") { PreviewCoordinates.displaySize(1920, 1080, -90) }
        checkFails("sensorWidth") { PreviewCoordinates.displaySize(0, 1080, 0) }
        checkFails("sensorHeight") { PreviewCoordinates.displaySize(1920, -1, 0) }
    }

    private fun checkClose(expected: Pair<Double, Double>, actual: Pair<Double, Double>, context: String) {
        check(kotlin.math.abs(expected.first - actual.first) < 1e-12 &&
            kotlin.math.abs(expected.second - actual.second) < 1e-12) {
            "$context: expected=$expected actual=$actual"
        }
    }

    private inline fun checkFails(messagePart: String, action: () -> Unit) {
        try {
            action()
            error("Expected IllegalArgumentException containing '$messagePart'")
        } catch (e: IllegalArgumentException) {
            check(e.message.orEmpty().contains(messagePart)) { "Unexpected error: ${e.message}" }
        }
    }
}
