# Camera120: iPhone frame-rate and shutter test

A small iOS app that runs the back camera at a chosen frame rate (default 120 fps)
with a fixed shutter speed (default 1/500 s) and reports what the camera actually
delivers. It can record a take with a timestamp for every frame. It does **no
tracking**. The point is to find out, on the real iPhone, whether the frame rate,
shutter speed and low-resolution format needed for puck tracking are available.

## Status

The source is written and every file passes a Swift syntax check, but **it has not
been compiled or run.** Xcode was not installed on the Mac it was written on, so
the first build on your Mac may report errors. Fix those first, then test on the
phone. The iOS Simulator has no camera, so the app only shows a "no camera"
message there.

## Build and run

You need Xcode, an iPhone (the target is an iPhone 13) and an Apple ID. A free
Apple ID works; the app then needs re-installing every 7 days.

```bash
cd src/iphone_camera_test
open Camera120.xcodeproj        # run `xcodegen generate` first if you change project.yml
```

1. Select the **Camera120** target, then Signing & Capabilities, and choose your
   Team. (Regenerating the project with XcodeGen resets this.)
2. Plug in the iPhone, choose it as the run destination and press Run.
3. On the phone, trust the developer profile if asked (Settings, General, VPN and
   Device Management) and allow camera access.

## Using it

The app starts in the smallest format that can reach 120 fps. The overlay shows:

| Line | Meaning |
|---|---|
| format | Resolution of the active camera format |
| fps | Frame rate measured from frame timestamps over one second, and the target |
| gap | Longest time between two frames in the last second, and dropped frames |
| shutter | Shutter speed the camera applied, and what was asked for |
| ISO | ISO the camera applied |

A good 120 fps result is about 120 measured fps, a longest gap near 8.3 ms, zero
dropped frames and `1/500` applied. The controls change the frame rate, format,
shutter speed and ISO.

- **Format menu** lists every format that reaches 60 fps or more. Whether a small
  format such as 640x480 exists at 120 fps depends on the phone. This menu shows
  what is really offered. If none is small enough, the plan is to crop or
  downscale in the tracking code instead.
- **Shutter and ISO are fixed, not automatic.** At 1/500 s a normal room is dark,
  so raise the ISO or add light. Keep the table lighting flicker-free (DC LED).
- Shutter times the camera cannot do are clamped, and the overlay shows what was
  applied.

## Recording

Press Record, then Stop recording. Settings are locked during a take. Each take is
saved as:

- `rec_<date>_<time>.mov` in the app's Documents folder and in Photos
- `rec_<date>_<time>.csv` in the Documents folder, with columns `frame`,
  `pts_seconds`, `gap_ms`

Copy them to the Mac from the Files app (On My iPhone, Camera120), or with Finder
(select the iPhone, then the Files tab, then Camera120). Then summarize a take:

```bash
python3 summarize_timestamps.py rec_20261107_120000.csv
```

This prints the frame count, average frame rate, median and worst gap, and the
number of gaps over 1.5 times the median.

## What this does not tell you yet

- Camera-to-Mac latency. The timestamps are the phone's own capture clock.
- Whether tracking at this rate keeps up on the phone.
- How the picture looks on the real table. Lighting decides what shutter speed and
  ISO are usable.

## Files

- `Camera120/CameraController.swift`: session, format selection, frame rate,
  exposure, statistics and recording
- `Camera120/CameraPreview.swift`: live preview view, locked to landscape
- `Camera120/ContentView.swift`: overlay and controls
- `project.yml`: XcodeGen description; `Camera120.xcodeproj` is generated from it
- `summarize_timestamps.py`: analyses the CSV files from a recording
