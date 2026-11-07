---
name: iphone-camera-app
description: Work on the Camera120 iOS app in src/iphone_camera_test, a test of 120 fps capture at a fixed shutter speed. Use when editing its Swift code, regenerating the Xcode project, or planning the on-phone puck tracker built on it.
---

# Camera120 iOS app

Source is in `src/iphone_camera_test/Camera120/`. `project.yml` is the source of
truth for the Xcode project. After adding or removing a Swift file, regenerate:

```bash
cd src/iphone_camera_test
xcodegen generate
```

XcodeGen resets the signing Team each time, so the user picks it again in Xcode.

## Verification limits

Xcode may not be installed, in which case the app cannot be compiled here. The
checks that do work are:

```bash
swiftc -parse Camera120/<file>.swift        # syntax only
plutil -lint Camera120/Info.plist
```

Never say the app builds or runs unless it was built. Say that it passed a syntax
check and has not been compiled. The Simulator has no camera.

## Structure

- `CameraController`: owns the `AVCaptureSession`. All camera calls run on
  `sessionQueue`. Frame statistics and recorded timestamps are touched only on
  `frameQueue`. `@Published` values change only on the main queue (use `publish`).
- Format choice: video-range 4:2:0 formats that reach 60 fps. The default is the
  smallest one that reaches the target rate.
- Exposure: custom mode. The requested duration is clamped to the format's minimum
  and maximum and to one frame, and ISO to the format's range, because an
  out-of-range value throws an exception.
- The frame rate must lie inside one of the format's supported ranges before
  `activeVideoMinFrameDuration` and `activeVideoMaxFrameDuration` are set.
- Recording: `AVCaptureMovieFileOutput` plus a timestamp CSV. Settings are locked
  while recording.
- The app is locked to landscape-right, and the preview and movie connections are
  set to match.

## Direction (proposal, not built)

The longer-term idea is to track the puck on the phone and send only
`(x, y, timestamp)` to the Mac, since webcam apps generally cap near 30 to 60 fps.
Measure the delivered frame rate, gaps and dropped frames with this app first. Then
add a Metal or Accelerate colour threshold on the frames from the video data
output, and send results over USB or UDP. Keep calibration and filtering on the
Mac so they can change without rebuilding the app.
