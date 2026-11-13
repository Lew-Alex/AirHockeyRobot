import com.example.fastcam.PreviewCoordinates
import com.example.fastcam.RecordedPuckFrame
import com.example.fastcam.RecordedPuckTimeline

/** Source-only tests for running elsewhere with the existing Kotlin test commands. */
object RecordedPuckTimelineTest {
    @JvmStatic fun main(args: Array<String>) {
        val first = RecordedPuckFrame(0, 0.25, 0.75, 0.03)
        val last = RecordedPuckFrame(8_333, 0.6, 0.1, 0.04)
        val timeline = RecordedPuckTimeline(listOf(first, RecordedPuckFrame(4_167, null, null, null), last))
        check(timeline.at(0) == first)
        check(timeline.at(4_167) == null) // do not reuse the earlier circle on a missing frame
        check(timeline.at(8_400) == last) // allow MP4 timestamp quantization
        check(timeline.at(100_000) == null)
        check(timeline.at(-1) == null)
        check(RecordedPuckTimeline(emptyList()).at(0) == null)
        for (rotation in listOf(0, 90, 180, 270)) {
            val displayed = PreviewCoordinates.toPreview(0.2, 0.7, rotation)
            val roundTrip = PreviewCoordinates.toSensor(displayed.first, displayed.second, rotation)
            check(kotlin.math.abs(roundTrip.first - 0.2) < 1e-10)
            check(kotlin.math.abs(roundTrip.second - 0.7) < 1e-10)
        }
        // Sensor=90 portrait already has the platform's quarter turn. Do not add another.
        check(PreviewCoordinates.textureRotation(0) == 0)
        check(PreviewCoordinates.textureRotation(90) == 270)
        check(PreviewCoordinates.textureRotation(180) == 180)
        check(PreviewCoordinates.textureRotation(270) == 90)
        println("Recorded puck timestamp/rotation tests passed")
    }
}
