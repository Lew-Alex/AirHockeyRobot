# Camera input testing

Run this from the repository root with the puck tracker's existing Python environment.

```bash
src/perception/prototype/.venv/bin/python src/perception/input_testing/camera_latency.py
```

For wireless testing, unplug the iPhone, leave Wi-Fi and Bluetooth on for
both devices, and enable Continuity Camera on the iPhone. Lock the phone and
set it near the Mac in landscape. Confirm the iPhone appears in FaceTime's
Video menu, then quit FaceTime before running the test.

The script opens camera index 1 by default. If the preview shows the MacBook
camera, rerun with `--camera 0`, then try `--camera 2` if needed. Cover the
iPhone's rear lens to confirm the feed. Press **Q** or **Escape** to finish.

## Measure latency

1. Place the **Source clock** and **Camera latency** windows side by side.
   Point the camera at the source clock. Keep the preview out of the camera's
   view to avoid a recursive image.
2. Screen-record both windows. In a paused recording, read the clock **inside
   the camera image** and the **Received** time printed on that same frame.
   Subtract the former from the latter. Both times use the Mac's local clock.
3. For a camera-to-screen estimate, instead compare the clock inside the image
   with the live Source clock in the same recording frame. Repeat several
   times and compare the median and worst readings across camera modes.

The first measurement estimates delay up to `VideoCapture.read()` returning.
It includes the source display's refresh delay, and the digits inside the
image are limited by the monitor's refresh rate. It excludes subsequent app
processing. The second measurement also includes the preview path. A receive
timestamp alone cannot reveal how long the frame took to arrive.

## Compare frame rates

The test requests 1280×720 at 60 FPS. The camera can negotiate a different
mode. Compare the measured delivery FPS shown in the preview.

`logs/frames_*.csv` contains one row per delivered frame, including Unix and
monotonic receive timestamps in nanoseconds and the interval since the previous
frame. Preview can skip frames while the capture thread continues to log them.

## Save individual frames

Click the preview and press **R** to start or stop saving frames. The preview
shows **REC** while recording. Each received frame during recording is saved
as a JPEG without the timestamp overlay in `logs/frames_*/`, next to the CSV
with the same name. Match the image filename's number to the CSV's `frame`
column to get its receive timestamp. Press **Q** or **Escape** and let the
program finish writing the queued images.

For the lowest-overhead latency baseline, leave recording off. Use the screen
recorder to capture the on-screen timestamps and **R** for individual images.
