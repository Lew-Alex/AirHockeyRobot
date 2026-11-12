package com.example.fastcam

/** Coordinate conversions for a sensor image displayed after clockwise rotation. */
object PreviewCoordinates {
    /** TextureView already applies sensor rotation; its matrix corrects display rotation only. */
    fun textureRotation(displayRotation: Int): Int {
        require(displayRotation in listOf(0, 90, 180, 270)) { "displayRotation must be a quarter turn" }
        return (360 - displayRotation) % 360
    }

    /** Maps native sensor coordinates into an upright, clockwise-rotated video. */
    fun toPreview(x: Double, y: Double, rotation: Int): Pair<Double, Double> = when (rotation) {
        0 -> x to y
        90 -> (1.0 - y) to x
        180 -> (1.0 - x) to (1.0 - y)
        270 -> y to (1.0 - x)
        else -> throw IllegalArgumentException("rotation must be 0, 90, 180, or 270 degrees")
    }

    /**
     * Maps normalized coordinates in the rotated preview back to the sensor's native axes.
     *
     * Coordinates use a top-left origin, with x increasing right and y increasing down.
     * Values are not clamped, so points outside the preview bounds remain outside the sensor
     * bounds after conversion.
     *
     * @param u normalized horizontal preview coordinate
     * @param v normalized vertical preview coordinate
     * @param rotation clockwise rotation in degrees (0, 90, 180, or 270)
     */
    fun toSensor(u: Double, v: Double, rotation: Int): Pair<Double, Double> = when (rotation) {
        0 -> u to v
        90 -> v to (1.0 - u)
        180 -> (1.0 - u) to (1.0 - v)
        270 -> (1.0 - v) to u
        else -> throw IllegalArgumentException("rotation must be 0, 90, 180, or 270 degrees")
    }

    /** Returns the displayed image dimensions after clockwise rotation. */
    fun displaySize(sensorWidth: Int, sensorHeight: Int, rotation: Int): Pair<Int, Int> {
        require(sensorWidth > 0) { "sensorWidth must be positive" }
        require(sensorHeight > 0) { "sensorHeight must be positive" }
        return when (rotation) {
            0, 180 -> sensorWidth to sensorHeight
            90, 270 -> sensorHeight to sensorWidth
            else -> throw IllegalArgumentException("rotation must be 0, 90, 180, or 270 degrees")
        }
    }
}
