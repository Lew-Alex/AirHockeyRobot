# Android App Perception Test

A native USB puck tracker with a camera preview. The Android app contains no Python,
recording/export code, status bars or position boxes.

## Phone controls

The camera occupies the screen above one row of two click buttons and the camera-mode selector:

- **USB tracking: On/Off** starts/stops C++ tracking and the TCP coordinate output.
- **Preview: On/Off** shows/hides the camera image. With preview off, USB tracking continues.
- **Camera mode** chooses a resolution and requested frame rate reported by the phone.

The green ring marks detections on displayed frames. There is no header, preview stats
panel, miniature position box, recording button, shutter slider or Python toggle.
With both buttons off, the camera is closed. Camera errors use a toast instead of
adding another permanent UI panel.

## Build elsewhere

Use Android Studio, JDK 17, Android SDK Platform 35, **NDK 28.2.13676358** and
**CMake 3.22.1**. Open this directory (`src/AndroidApp`) in Android Studio. The
pinned versions are AGP 8.7.3, Kotlin 2.0.21 and Gradle 8.9. If a Gradle wrapper
script/JAR is missing, generate the wrapper on the build machine using
`gradle wrapper --gradle-version 8.9`.

No Python installation or pip dependencies are needed to build or run the Android
app. Chaquopy, NumPy/OpenCV wheels and Media3 were removed from this app. Python is
still used by the optional **laptop receiver** and separate offline perception scripts.

The package remains `com.example.fastcam` and launcher name remains
**Android App Perception Test**. The native library supports arm64-v8a and x86_64.
Install the resulting APK, grant camera permission and press **USB tracking** to
start the stream. No Android app compilation has been performed here.

## Preview smoothness and tracking rate

The previous 15 fps preview limit was deliberate and made the camera look choppy.
The preview now targets **60 fps** with an anchored deadline and jitter tolerance.
That timer applies only to display rendering. The coordinate stream has **no fixed
60-update/s cap**: each analyzed fresh camera texture can produce one result.

Selecting a **60 fps camera mode** normally bounds fresh measurements to about 60/s.
Choose a supported fixed **120/240 fps high-speed mode** to test higher rates.
A mode's requested FPS is not a guarantee of delivered images or analyzed results.
The app prefers 720p/120 when available, then another advertised 720p high-speed mode.
Camera modes are discovered from SurfaceTexture/high-speed capabilities, without
requiring a recording encoder to support the same mode.

The image is consumed on an offscreen GL worker, independently of TextureView's UI
refresh callback. GPU thresholding creates a <=640px analysis mask; four mask samples
are packed into each RGBA texel and passed directly to the native C++ detector.
Kotlin detection is a fallback if the native library cannot load; the stream's
`detector_backend` field identifies which is running.

Coordinates are published before preview drawing. Display swaps still use the same
GL worker and can block on a particular driver; compare preview on/off rates to measure
that cost. Disabling USB skips the mask readback, detector and coordinate publishing
while allowing a smooth camera-only preview. There is no per-frame stats-box UI work.
Actual preview smoothness and capture/stream throughput still need phone validation.

## Mac receiver

Enable USB debugging, authorize the Mac and connect using a USB data cable. Install
Android SDK Platform Tools and Python 3 (with Tk for the optional receiver window).

From this directory, after setting **USB tracking: On** on the phone:

```sh
adb devices
adb forward tcp:8765 tcp:8765
python3 tools/view_puck_stream.py --headless --live --latency --duration 30 --report native-stream.json
```

Omit `--headless` to open the laptop's small position window. That window's redraw
rate does not limit the receiver thread. `--live` prints received messages/s and valid
positions/s once per second, not every coordinate line. Keep `puck_clock_sync.py`
beside the viewer for `--latency`.

Run a new receiver after changing camera modes, turning USB off/on or returning from
background: these operations close the existing connection. Keep the phone foregrounded.

## Windows receiver

Install Python 3.8+ and Android SDK Platform Tools for Windows. Enable USB debugging
and authorize the computer. If a Pixel is not recognized, check the Google USB Driver.

Keep `tools/view_puck_stream_windows.py`, `tools/view_puck_stream.py` and, for latency
measurements, `tools/puck_clock_sync.py` together. From this directory:

```powershell
py tools/view_puck_stream_windows.py --headless --live --latency --duration 30 --report native-stream-windows.json
```

The launcher discovers ADB, selects an authorized USB phone, establishes forwarding,
starts the shared receiver and prints the report path. `--adb PATH`, `--serial SERIAL`
and `--port 8766` handle nondefault SDK paths, multiple devices and local port conflicts.
It preserves an identical existing forward and removes only a forward it created.
Without `--report`, reports go in a timestamped JSON under `puck-reports`.

## Stream and measurements

Phone loopback **127.0.0.1:8765** sends newline-delimited JSON to up to four readers.
Socket workers keep only the newest pending result, use TCP_NODELAY and request a
small send buffer to reduce hidden backlog. This is not a hard latency guarantee.
A disconnected receiver does not stop the camera. No old coordinates are replayed.

| Field | Meaning |
|---|---|
| `frame_id` | Increasing consumed-texture ID; not the sensor frame number. |
| `detected` | False means no puck; XY fields are JSON null. |
| `x`, `y` | Native sensor-image pixel centres, top-left origin, X right/Y down. |
| `x_normalized`, `y_normalized` | Normalized pixel centres: `(x + 0.5) / image_width`, `(y + 0.5) / image_height`. |
| `rotation_degrees` | Clockwise rotation used for the displayed image. |
| `requested_fps` | Camera mode target, not a measured result. |
| `capture_fps` | Camera metadata timestamp cadence; results can be batched. |
| `source_fps`, `analysis_fps`, `detected_fps` | Consumed frames, completed analyses and successful detections per elapsed phone time. |
| `processing_ms` | Texture acquisition + mask/readback + detection, excluding publish and preview. |
| `acquire_ms`, `mask_readback_ms`, `detection_ms` | Individual stages of that processing interval. |
| `previous_publish_ms`, `previous_preview_ms`, `previous_frame_work_ms` | Prior frame's formatting/enqueue, display work and complete worker duration. |
| `preview_target_fps` | 60 fps display target; never a coordinate-stream cap. |
| `socket_*_messages` | Per-client aggregate offered/written/replaced counters. Test with one reader for simple interpretation. |
| `pipeline_revision`, `stream_revision` | 3 and 5 for this minimal native app. |

The report separates actual received message/position rates from phone-reported rates.
Missing detections can make valid-position rate lower than message rate. Frame-ID gaps
and socket replacement counters help identify dropped intermediate updates.

Clock probes (`CLOCK_SYNC id`) estimate phone-minus-laptop clock offset using four
timestamps. Clock replies are excluded from coordinate counters. Estimated
sensor/sample/publish-to-receiver ages are reported only after compatible synchronization.
Sensor age additionally requires REALTIME sensor timestamps. Do not subtract raw phone
and laptop clocks; inspect the report's round-trip and offset-uncertainty values.
A reported 180 ms has not been attributed to a specific stage without a device report.

These are image coordinates, not calibrated table coordinates. Table calibration and
rolling-shutter correction remain separate work.

## Validation

Receiver/launcher/clock-sync tests (no camera or app build):

```sh
python3 tools/view_puck_stream.py --self-test
python3 -m unittest discover -s tools -p "test_*.py" -v
```

Native detector core tests on a host C++17 compiler:

```sh
g++ -std=c++17 -O3 -Wall -Wextra -pedantic -I app/src/main/cpp app/src/main/cpp/puck_detector.cpp tools/native_puck_detector_test.cpp -o native-puck-test
./native-puck-test
```

Standalone Kotlin test sources cover coordinate rotation, packed-mask detection,
cadence (including a 60 Hz preview target), rate windows and socket output. Run them
on the build machine; no Kotlin or Android compilation is performed here.

Required phone checks: camera permission grant/deny; both buttons individually and
together; each camera mode; smooth preview and circle alignment at all corners;
preview off with USB still receiving; USB off with camera preview still working;
both off closing the camera; rapid toggles; background/resume; mode changes while
connected; receiver reconnect; and preview-on/off rate/latency comparisons at 60/120/240 fps.
