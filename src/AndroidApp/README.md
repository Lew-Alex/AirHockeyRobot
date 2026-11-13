# Android App Perception Test

Android Camera2 recorder with optional on-device Python tracking of the yellow puck.
The existing camera mode selection, manual shutter controls, MP4 recording and per-frame
camera metadata CSV remain available. The launcher name is **Android App Perception Test**;
its package remains `com.example.fastcam` so it updates the original FastCam installation.

## Build and install

1. Install Android Studio, Android SDK Platform 35, and JDK 17.
2. Install **Python 3.10** on the build computer. The app embeds Python 3.10 via
   Chaquopy 17.2.0; NumPy 1.26.2 and OpenCV 4.5.1.48 are pinned to available Android wheels.
   The first sync needs internet access to download Gradle, Maven dependencies and wheels.
3. Open this `src/AndroidApp` directory in Android Studio. Keep the pinned AGP 8.7.3,
   Kotlin 2.0.21 and Gradle 8.9 versions while validating the app.
4. This source checkout originally includes only `gradle-wrapper.properties`. If Android
   Studio cannot sync without a wrapper, use an installed Gradle to run
   `gradle wrapper --gradle-version 8.9` in this directory first. Then use `gradlew.bat`
   on Windows or `./gradlew` on macOS/Linux.
5. If Chaquopy cannot discover Python 3.10, set `trackingPython` in your local Gradle
   properties or pass `-PtrackingPython=C:/path/to/python.exe`. Do not commit local paths.
6. Enable Developer options and USB debugging on the phone, connect USB and authorize
   the computer, select the device in Android Studio and run the app. Grant camera access.

The APK includes `arm64-v8a` (phone) and `x86_64` (emulator). No Python installation,
server, internet connection or laptop is needed on the phone to run the tracker.

## Record and track

- Select a resolution/frame-rate mode. The existing camera discovery still offers
  supported 120/240 fps high-speed modes, standard 60 fps modes, or a 30 fps fallback.
- **Shutter** changes exposure in standard modes when manual sensor control is available.
  High-speed sessions keep automatic exposure.
- Turn on **Track yellow puck (Python)**. It works before recording to help aim the camera,
  and continues when **REC** is pressed. A green ring follows the detected puck, and the
  status shows X/Y and Python processing time. Toggle it off to disable analysis/output.
- **REC / STOP** saves the original video and metadata as before:
  - `Movies/FastCam/FASTCAM_<date>_<WxH>_<fps>fps.mp4` (HEVC with H.264 fallback, no audio)
  - `Download/FastCam/FASTCAM_<...>.csv` (camera frame metadata)
- **Embed green circle in MP4 (after Stop)** is a separate toggle, off by default.
  Select it before recording; it is locked for the duration of that recording. After
  Stop, the app automatically analyses every saved frame with the Python tracker and
  creates `Movies/FastCam/FASTCAM_<...>_tracked.mp4`, with the green circle embedded in
  the actual video pixels. The original MP4 and sensor CSV are retained. This toggle
  works even when live tracking is off.
- MP4 export displays progress in two stages (analysis, then encoding). Keep the app
  open until it finishes. Recording controls and live preview analysis pause during
  export to avoid competing for the encoder/Python worker. **Cancel MP4 overlay export**
  discards the incomplete annotated copy and keeps the original; destroying the
  activity also cancels unfinished work. Export errors keep the original.
- Missing detections clear the live ring immediately; it also expires after 250 ms
  without an update. The exported ring is matched to each decoded frame's actual
  presentation timestamp, with no stale circle held over a lost frame. Video dimensions,
  frame count and timestamps are checked before the annotated copy is published;
  unsupported encoder configurations report an error instead of silently reducing size.
  Pausing/backgrounding closes live XY connections and clears live tracker history.
- The target is the **yellow puck** from `../perception/androidAppPerceptionTesting`.
  This is colour/shape/continuity tracking, not identification of any arbitrary ball.
  HSV and blob thresholds remain in the shared `puck_tracker.py` Settings class.

## Tracking rate and geometry

The app embeds and imports the **same** `puck_tracker.py`, plus `android_bridge.py` from
`../perception/androidAppPerceptionTesting`; there is no copied Kotlin tracker. The bridge
unpacks Android signed ARGB pixels into BGR NumPy images and adapts temporal continuity
limits to live sample timing. Its timestamp-free API preserves offline tracker behaviour.

Tracking samples the existing rotated TextureView, at most **30 samples/second**, with a
maximum analysis-image edge of 1280 pixels. Python runs on a dedicated single worker;
frames are dropped while it is busy. There is no analysis queue or third camera output,
which preserves the two-surface constrained high-speed camera configuration. Video can
record at 120/240 fps while detection runs at the lower preview/processing rate. GPU
readback, Python startup, lighting, thermal throttling and device speed still affect
latency and must be measured on the target phone; no 240 Hz tracking claim is made.

TextureView's camera producer already applies sensor orientation. The app's preview
matrix now applies **only display-rotation compensation**, so a portrait sensor image
is not rotated a second time into landscape. Preview and live ring use matching fitted
bounds and the same sampled image. Exported XY coordinates undo the total sensor-to-display
rotation and use native recorded image axes (before MP4 rotation metadata).

Annotated export runs **after capture**, using MediaCodec to decode native YUV frames,
the same Python tracker to obtain per-frame detections, and Media3 Transformer 1.5.1
to re-encode the video with a GPU-composited green ring. Decoder crop rectangles and
YUV plane row/pixel strides are respected. The recording camera session is unchanged,
so no third camera output is added and available high-speed recording modes remain.
This extra pass takes processing time and storage; it is independent of the 30 Hz live
preview sampler. Re-encoding may change compressed file size/quality. The retained
source video is the original capture.

## XY output contract

`PuckCoordinateServer.DEFAULT_PORT` defines **TCP port 8765**. While tracking is enabled
and the app is foregrounded, a server binds to **127.0.0.1:8765 on the phone**. It emits
UTF-8 newline-delimited JSON to up to four connected clients. Slow clients retain only
the latest pending message and cannot block the tracker. No destination is configured.
This is a live stream: connect while tracking is running; old samples are not replayed.

For a connected development computer:

```sh
adb forward tcp:8765 tcp:8765
python tools/read_puck_coordinates.py
```

Example detection (additional timing/analysis fields are included):

```json
{"type":"puck","version":1,"frame_id":42,"timestamp_ns":123456789000,"preview_timestamp_ns":123450000000,"detected":true,"coordinate_space":"sensor_pixels","image_width":1280,"image_height":720,"rotation_degrees":90,"x":640.0,"y":360.0,"x_normalized":0.500390625,"y_normalized":0.5006944444,"analysis_width":720,"analysis_height":1280,"processing_ms":12.3}
```

| Field | Meaning |
|---|---|
| `frame_id` | Increasing analysis sample ID; not the camera metadata frame number. Gaps are allowed. |
| `timestamp_ns` | Android elapsed-realtime nanoseconds when preview readback starts. Not wall clock or sensor exposure time. |
| `preview_timestamp_ns` | SurfaceTexture timestamp read with the sample; diagnostic only, not guaranteed frame-perfect metadata alignment. |
| `detected` | `false` means no puck in this analysed sample; x/y and normalized fields are then JSON `null`. |
| `image_width`, `image_height` | Native recording-buffer dimensions before orientation metadata. |
| `x`, `y` | Floating-point pixel-centre coordinates: top-left origin, X right, Y down. |
| `x_normalized`, `y_normalized` | Normalized pixel centres: `(x + 0.5) / image_width`, `(y + 0.5) / image_height`. |
| `rotation_degrees` | Clockwise rotation applied for display and MP4 orientation. |
| `analysis_width`, `analysis_height` | Actual bitmap dimensions fed into Python. |
| `processing_ms` | Python conversion and detection time; excludes GPU readback and UI presentation. |

Consumers must handle `detected:false`, stale timestamps and EOF (toggle off, background
or app exit). These are image coordinates, not calibrated table coordinates. Homography,
physical units and forwarding to an external robot/service are future work.

## Camera metadata CSV

```text
frame_number,sensor_timestamp_ns,exposure_ns,rolling_shutter_skew_ns,frame_duration_ns,iso
```

Sensor row `r` begins exposing at
`sensor_timestamp_ns + rolling_shutter_skew_ns * r / (rows - 1)`.
Camera rolling-shutter readout is set by the sensor mode, not directly by the app.
Short manual exposure reduces motion blur but does not itself reduce readout skew.
Stabilization remains disabled in standard modes.

## Validation

Python bridge tests, from `../perception/androidAppPerceptionTesting`:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

Dependency-free JVM checks (requires `kotlinc` and Java; run from this directory):

```sh
kotlinc app/src/main/java/com/example/fastcam/PreviewCoordinates.kt app/src/main/java/com/example/fastcam/PuckCoordinateServer.kt tools/PreviewCoordinatesTest.kt tools/PuckCoordinateServerIntegrationTest.kt -include-runtime -d app/build/tracking-tests.jar
java -cp app/build/tracking-tests.jar com.example.fastcam.PreviewCoordinatesTest
java -cp app/build/tracking-tests.jar PuckCoordinateServerIntegrationTest
```

Additional source-only JVM test (compile/run elsewhere): include
`RecordedPuckTimeline.kt` and `tools/RecordedPuckTimelineTest.kt` alongside
`PreviewCoordinates.kt`, then run `RecordedPuckTimelineTest`. It checks timestamp
matching, missing/stale detections, sensor/display round trips and display-only rotation.
Python tests also cover planar/interleaved YUV chroma, row padding and odd crops/edges.

On-device acceptance checks still required: build/install the APK, confirm Python imports,
try each reported resolution/frame rate with tracking off/on, move the yellow puck to
all four corners, confirm XY axes after rotation, hide/reveal the puck, toggle during
recording, background/resume repeatedly, read TCP samples via adb, and compare saved
video/metadata frame timing with tracking disabled. Verify native-wheel loading on the
target phone, including its memory-page-size configuration.
Check the preview is upright with both toggles off/on, record a short clip with the MP4
toggle enabled, wait for `_tracked.mp4`, and inspect its four corners, ring alignment,
orientation, resolution, frame count and playback speed. Also try export with live
tracking off, loss/reacquisition, cancelling during each export stage, and an unsupported
encoder mode (the original must remain intact). No Android compilation was performed
for the preview-rotation and MP4-export changes in this session.
