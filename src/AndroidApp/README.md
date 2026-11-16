# Android App Perception Test

Android Camera2 recorder with a GPU/C++ live puck stream and optional Python preview tracking.
The existing camera mode selection, manual shutter controls, MP4 recording and per-frame
camera metadata CSV remain available. The launcher name is **Android App Perception Test**;
its package remains `com.example.fastcam` so it updates the original FastCam installation.

## Build and install

1. Install Android Studio, Android SDK Platform 35, and JDK 17.
   The native tracker additionally requires **NDK 28.2.13676358** and **CMake 3.22.1**
   on the build computer (SDK Manager → SDK Tools → Show Package Details).
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

The screen keeps the camera and position monitor above a scrolling control panel,
with **Record video** always available in the bottom action bar. Controls use the
following names (older builds used the longer "USB tracking test" and "Track yellow
puck" labels):

| Control | Tracker and purpose |
|---|---|
| **Live USB tracking (C++)** | GPU mask plus native C++ detection and coordinate streaming. Recording is disabled while this mode runs. |
| **Show camera preview** | Optional video display during live USB tracking. Turn off to keep the position monitor and stream running without drawing the preview. |
| **Preview tracking (Python)** | Original recorder-compatible tracker, targeting up to 30 analyses/s. Paused while live USB tracking is active. |
| **Save MP4 with tracking circle** | Python processing after Stop to create an annotated copy. The original recording is kept. |

The tracking status names the **actual** live detector. If the C++ library cannot
load, it explicitly shows **Kotlin fallback**. Keeping the Python label is intentional:
that switch still selects Python, rather than the C++ streaming path.

- Select a resolution/frame-rate mode. The existing camera discovery still offers
  supported 120/240 fps high-speed modes, standard 60 fps modes, or a 30 fps fallback.
- **Shutter slider** changes exposure live in standard modes when manual sensor control
  is available. Far left is Auto; moving right requests progressively shorter exposures,
  down to the camera's advertised minimum. **Reset shutter to Auto** restores automatic
  exposure. The label shows the requested value; the top panel shows the **actual** value
  reported by the camera. High-speed sessions keep automatic exposure.
- Turn on **Preview tracking (Python)**. It works before recording to help aim the camera,
  and continues when **Record video** is pressed. A green ring follows the detected puck, and the
  status shows X/Y and Python processing time. Toggle it off to disable analysis/output.
- **Record video / Stop recording** saves the original video and metadata as before:
  - `Movies/FastCam/FASTCAM_<date>_<WxH>_<fps>fps.mp4` (HEVC with H.264 fallback, no audio)
  - `Download/FastCam/FASTCAM_<...>.csv` (camera frame metadata)
- **Save MP4 with tracking circle** is a separate toggle, off by default.
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

### Experimental high-rate USB tracking test

Enable **USB tracking test (GPU + C++; no recording)** to try the independent high-rate path.
It replaces the Python preview sampler for the duration of the test. The existing
recording/Python path is restored when the switch is turned off. No APK or phone
benchmark has been run for this change: requested camera rates are targets, not results.

The test configures exactly **one Camera2 output**, an offscreen SurfaceTexture consumed
on a dedicated EGL/GLES worker. A fragment shader thresholds the same yellow HSV range
as the Python tracker into a binary mask (longest edge at most 640 px). A C++
connected-component detector selects a blob using size, shape and timed continuity.
Four adjacent binary samples are packed into the RGBA channels of each readback texel,
reducing transferred mask data to about one quarter of the original full-RGBA mask.
JNI passes the direct GPU mask buffer to C++ without copying the full frame into Java.
The previous Kotlin detector remains a runtime fallback if the native library cannot load.
The report's `detector_backend` must say **cpp** to verify the native path; it says
`kotlin_fallback` otherwise, with a `native_load_error` when available.
The 640px analysis grid and blob-selection rules
are retained; no smaller analysis resolution is used for this optimization.
It does not embed OpenCV or call Python. Its results are experimental and must be checked
against the Python reference/ground truth; matching HSV bounds does not imply matching
detector accuracy. Very small/distant pucks can be lost by downsampling.

Each **new texture timestamp** produces at most one measured result; duplicate/coalesced
callbacks are ignored. Measurements are published from the worker directly to the existing
TCP 8765 stream. The latest camera image, green circle and small native-axis puck-position
monitor update at up to 30 Hz; the camera preview updates at up to 15 Hz. Measurement
streaming has no 15/21/30 Hz cap. Overlay refresh rate is not the tracking rate.
**Camera preview in GPU test** can be switched off while streaming. The camera image
is cleared, while the mini-map and coordinates stay live. This comparison isolates
preview drawing/swap cost from capture and tracking. The GL path applies the camera SurfaceTexture producer
transform once (including sensor orientation), plus display-rotation compensation; the
visible TextureView has an identity matrix for this copied output. Mode changes disconnect
Camera2 before switching between the camera and EGL preview producers.

The test intentionally disables REC and MP4 burn-in. This isolates capture/tracking
throughput and avoids the two-output high-speed request pattern. It is not a simultaneous
240-fps tracking + recording implementation. GL readback and preview buffer swaps may
still stall on a particular phone; the counters should reveal that. Unsupported GPU or
camera configurations report errors; choose another mode or toggle off to restore recording.

On the phone, start with **1280x720 @ 60fps (standard)**, enable the GPU test, aim at the
yellow puck, and move it across all four corners to check preview/ring/coordinate alignment.
Then try available standard 30/120 and constrained 120/240 modes. USB streaming starts
without pressing REC. Controls at the bottom scroll to expose the mode selector and shutter.

On the Mac, enable USB debugging on the phone, authorize the Mac, install Android SDK
Platform Tools and use a USB data cable. From this `src/AndroidApp` directory:

```sh
adb devices
adb forward tcp:8765 tcp:8765
python3 tools/view_puck_stream.py --duration 60 --report puck-720p60.json
```

This opens a small always-on-top position window and prints/saves a JSON report when
the run ends. If your Python installation lacks Tk, use:

```sh
python3 tools/view_puck_stream.py --headless --duration 60 --report puck-720p60.json
```

#### Windows receiver

The viewer is also compatible with Windows. Install Python 3.8+ with Tcl/Tk support
for the position window, plus [Android SDK Platform Tools for Windows](https://developer.android.com/tools/releases/platform-tools).
Enable USB debugging, connect a USB data cable and authorize the computer on the phone.
If the Pixel does not appear in ADB/Device Manager, check the
[Google USB Driver](https://developer.android.com/studio/run/win-usb).

Keep `tools/view_puck_stream_windows.py` and `tools/view_puck_stream.py` together.
From `src/AndroidApp` in PowerShell or Command Prompt, with the phone's GPU test on:

```powershell
py tools/view_puck_stream_windows.py
```

The launcher finds ADB on PATH, in Android Studio's default SDK, in `ANDROID_HOME` /
`ANDROID_SDK_ROOT`, or in `Downloads/platform-tools`. It selects a USB phone, sets up
TCP forwarding, opens the same small position window and collects a 60-second report.
The report's absolute path is printed before the test starts; by default it is a
timestamped JSON in `puck-reports` under the current directory. No pip packages are needed.
If `py` is unavailable, use the installed `python` command instead.

For a longer test without a window:

```powershell
py tools/view_puck_stream_windows.py --headless --duration 120 --report puck-720p60-windows.json
```

Use `--adb "C:\path\to\platform-tools\adb.exe"` for another ADB location, `--serial SERIAL`
for multiple phones, and `--port 8766` if PC port 8765 is already used. The phone still
uses port 8765. The launcher preserves existing forwards and refuses to replace a
different device/service's mapping. It removes only a forwarding entry it created,
after the viewer finishes. It does not build/install an APK or change system settings.

If you already forwarded the port manually, the shared script also works directly:

```powershell
adb forward tcp:8765 tcp:8765
py tools/view_puck_stream.py --duration 60 --report puck-720p60-windows.json
```

Run a new receiver for each camera mode (a mode change closes the old connection).
Repeat for a few minutes to check thermal throttling. Keep lighting, camera placement,
puck distance and movement similar between runs. Check visible detections against the
actual puck; detection ratio is **not** an accuracy score.

| Counter / JSON field | What it actually measures |
|---|---|
| Top panel / `capture_fps` | Camera capture-result timestamp cadence; indicative, can be batched, not proof every image was consumed. |
| Monitor Frames / `source_fps` | Unique texture frames consumed per elapsed phone time, over a sliding one-second window. |
| `analysis_fps` | Completed analyses per elapsed phone time, including samples where no puck was found. |
| `detected_fps` | Successful detections per elapsed phone time. |
| Mac `received_rate_hz` | Received coordinate/lost messages per Mac elapsed time, including connection startup. |
| `processing_ms` | Texture acquisition, GPU mask/readback and blob detection; excludes preview swap, network and UI work. |
| `acquire_ms` | Making the analysis context current and acquiring the newest texture frame. |
| `mask_readback_ms` | Transform/mask rendering and synchronous GPU-to-CPU readback. |
| `detection_ms` | Bulk mask unpacking and connected-component/continuity detection. |
| `previous_publish_ms` | Prior result's JSON construction and enqueue time; excludes background socket writes. |
| `previous_preview_ms` | Prior frame's preview context/draw/swap work (near zero on skipped preview frames). |
| `previous_frame_work_ms` | Prior frame's full worker time, including publishing, UI callback posting and preview work; excludes waiting for the next callback. |
| `frame_age_ms` | Sensor timestamp to detection completion on the phone, only for a comparable REALTIME clock; otherwise null. |

The stream also includes `tracker:gpu_mask_experimental`, `requested_fps`,
`capture_timestamp_ns`, `phone_publish_timestamp_ns` and `timestamp_source`. The common
sensor-pixel/normalized coordinate contract below is retained. Phone and Mac clocks must
not be subtracted directly: this report does **not** measure full one-way USB latency.
Sensor timestamps describe the start of first-row exposure, not the exact instant the
puck's row was captured. No table calibration or rolling-shutter correction is added.

#### Investigating a roughly 21 Hz stream

21 Hz is not a configured GPU tracking limit. The legacy **Python** switch caps its
sampler at 30 Hz and drops frames when busy; make sure the GPU switch is the active test.
The laptop mini-window redraws at about 20 Hz, independently of how many messages it
receives. It now displays **current source rate** and **received rate** separately and
does not sort full benchmark histories on every redraw.

After building/installing the updated app elsewhere, collect two 60-second runs in
the same camera mode, lighting and puck setup: one with **Camera preview in GPU test**
on, one with it off. Run the receiver again for each run. For example, on the Mac
from `src/AndroidApp`, after forwarding port 8765:

```sh
python3 tools/view_puck_stream.py --headless --duration 60 --report gpu-preview-on.json
python3 tools/view_puck_stream.py --headless --duration 60 --report gpu-preview-off.json
```

Toggle the phone preview off between those two commands. On Windows, use the Windows
launcher with the same `--headless`, `--duration` and `--report` arguments. Headless
mode removes laptop GUI rendering from the comparison; the phone mini-map remains live.
The report includes `latest_pipeline.pipeline_revision: 2` to identify the new app.
Old apps still work with the receiver, but their added stage timings remain null.

| Observation | What to investigate next |
|---|---|
| Camera metadata near 60, analyses near 21, received near 21 | Phone-side processing or preview stalls; inspect the stage timings. |
| Preview-off rate rises materially | Preview draw/swap is consuming the tracking worker's time. |
| Analyses are fast but camera metadata is also low | Camera mode, actual exposure/lighting and thermal conditions; metadata cadence is indicative, not a full capture audit. |
| Phone analyses are fast but laptop received rate is low | Receiver load, ADB/USB delivery and slow-client message replacement. |

The report's `pipeline_stage_ms` contains mean/p95 timing for each stage. `previous_*`
fields belong to the preceding processed frame so the result can be published before
preview work. They are not extra coordinates and no frame is replayed to raise the rate.
Actual speed improvement, accuracy equivalence on camera images and GPU shader operation
remain unverified until device testing. No Android app compilation is performed here.

#### C++ tracking and tracing a reported 180 ms latency

The GPU mode now uses a C++ detector (`app/src/main/cpp`) through JNI. The original
Python tracker remains available; the C++ path is selected with the **GPU + C++**
switch and does not call Python. The packed GPU mask is consumed directly by native
code, using reusable flood-fill buffers. C++ follows the experimental Kotlin detector's
size/shape/continuity rules, not a newly trained model. Test camera accuracy separately.
The new native library uses the pinned NDK/CMake versions listed above. Its standalone
host C++ tests pass; the Android JNI build/loading and phone speed remain unverified.

The Python preview path has also been improved: finished results are now published
on the Python worker without waiting for the phone UI thread. Its 30 Hz target uses
an anchored deadline with 1 ms tolerance instead of resetting the timer after every
accepted frame, avoiding unnecessary losses around nominal 30/60 Hz callback boundaries.
It still depends on preview readback and Python processing and cannot promise a higher rate.

180 ms must be attributed to a specific interval. `processing_ms` alone excludes
capture/readback before detection, display swaps, socket queuing and USB delivery.
The receiver's optional `--latency` uses bounded four-timestamp clock probes on the
same TCP connection to estimate the offset between phone and laptop clocks. Keep
`puck_clock_sync.py` next to the viewer for this feature. Ordinary receiving still
works without that helper. Raw phone and laptop timestamps must not be subtracted.

After building/installing the updated app elsewhere, enable GPU + C++, select a
standard 720p/60 mode, turn its camera preview off, and run on the Mac from `src/AndroidApp`:

```sh
adb forward tcp:8765 tcp:8765
python3 tools/view_puck_stream.py --headless --live --latency --duration 30 --report latency-native.json
```

On Windows:

```powershell
py tools/view_puck_stream_windows.py --headless --live --latency --duration 30 --report latency-native-windows.json
```

The terminal prints actual received **messages/sec** and **valid positions/sec** once
per second. A lost sample is a message with null XY, so these two counts can differ.
Reports identify `tracker`, `detector_backend`, `sampling_limit_fps` (Python only) and
`stream_revision:4`. Clock replies are excluded from every coordinate/rate counter.
For an older app that does not answer clock probes, ordinary rate reporting works,
but synchronized ages remain unavailable. Use a new receiver run after changing modes.

| Report field | Interpretation |
|---|---|
| `estimated_latency_ms.sensor_to_receiver_ms` | GPU sensor first-row exposure timestamp to laptop socket reception, only with REALTIME sensor timestamps. |
| `estimated_latency_ms.sample_to_receiver_ms` | Phone readback start to laptop reception; available for both updated trackers after synchronization. |
| `estimated_latency_ms.publish_to_receiver_ms` | Phone result formatting/enqueue to laptop reception; includes writer queuing and ADB/USB, not just cable time. |
| `clock_sync.offset_uncertainty_ms` | Half the minimum corrected round-trip time; one-way age estimates depend on path asymmetry and clock drift. |
| `latest_phone_transport.socket_replaced_messages` | Pending coordinate offers overwritten while a client writer lagged. Counters aggregate all connected readers; test with one reader. |
| `latest_phone_transport.socket_max_write_ms` | Maximum completed socket write+flush duration in the current server run; writing to a kernel buffer is not confirmation of laptop reception. |
| `frame_id_advance_rate_hz` | Observed sender ID advances per receiver time; high ID advance with low received cadence exposes skipped updates, not camera FPS. |

Compare per-stage processing times with these ages. High detection time points toward
the detector; large preview times point toward display; high readback time points toward
GPU synchronization; low processing time but high publish-to-receiver age points toward
the downstream path. The socket already uses TCP_NODELAY and a latest-only pending slot;
it now also requests a small kernel send buffer to reduce hidden backlog under load.
The OS can enlarge that buffer, so this is not a fixed latency guarantee. A reader
disconnect no longer reports a fatal tracker error, allowing the next test to reconnect.

No prerecorded coordinates are replayed to raise update counts. These changes do not
establish the cause of the reported 180 ms or promise a new phone FPS before measuring it.

### Fast shutter without 240 fps

Yes: frame rate and exposure duration are different. At 60 fps the frame interval is
about 16.7 ms; an exposure of 0.5 ms (1/2000 s) can still be requested if the sensor
supports it. Standard 30/60 modes now remain selectable even on high-speed cameras.
Regular 120 fps is offered only when advertised as a normal-session mode as well.

The logarithmic slider is capped by both the sensor exposure-time range and the selected
frame interval. It is not capped at the previous preset of 1/4000 s. Verify the top
panel's **actual exposure** because cameras may quantize/clamp requests. ISO is frozen
at the last automatic ISO when entering manual mode, so faster shutter can darken the
image; add bright, steady lighting and reset to Auto to meter again. Shorter exposures
reduce motion blur but do not change frame spacing or eliminate rolling-shutter skew.
Constrained high-speed sessions override manual exposure, so the slider is disabled
there. Manual shutter works in standard recording as well as the GPU streaming test.

### Existing Python preview tracker

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

For the experimental receiver, the stdlib-only statistics self-test can be run on the Mac:

```sh
python3 tools/view_puck_stream.py --self-test
```

Windows launcher/forwarding tests use mocks and require no connected phone:

```powershell
py tools/view_puck_stream_windows.py --self-test
py -m unittest discover -s tools -p test_windows_launcher.py -v
```

All receiver/launcher diagnostic tests (including separation of camera, analysis and
received rates) can be run with `py -m unittest discover -s tools -p "test_*.py" -v`.

`tools/ExposureControlTest.kt` and `tools/FastTrackingMathTest.kt` are additional source-only
JVM checks for slider limits, mask row orientation, lost/duplicate detections, reacquisition,
rate expiry and coordinate round trips. Packed-mask checks also compare odd-width/padded
readback against legacy RGBA centres and verify that padding cannot create blobs.
Compile/run them on the build machine alongside
`ExposureControl.kt`, `PuckMaskDetector.kt`, `FrameRateWindow.kt` and `PreviewCoordinates.kt`.
They have not been compiled/run here. They do not validate EGL, sensor orientation or
device timing. Receiver statistics tests, Python syntax and Android XML parsing passed;
no Android app compilation or device benchmark was performed for the GPU/shutter changes.

UI source checks cover XML/resource references and retained view IDs. The light theme,
larger text layout, preview fit/ring alignment, disabled record state, fallback/error
labels and scroll-to-cancel behavior still need visual/device validation after building
elsewhere. No Android compilation was performed for the UI refresh.

`tools/SamplingCadenceTest.kt` adds source-only cadence checks (jitter/stalls/duplicates).
Standalone C++ detector tests can be built on a host C++17 compiler from this directory:

```sh
g++ -std=c++17 -O3 -Wall -Wextra -pedantic -I app/src/main/cpp app/src/main/cpp/puck_detector.cpp tools/native_puck_detector_test.cpp -o native-puck-test
./native-puck-test
```

This tests the detector core only and does not build the Android app, JNI layer or shaders.
Clock-sync and receiver tests are included in `tools/test_*.py` (stdlib unittest).

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
