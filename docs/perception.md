# Perception

## What exists

- `src/AndroidApp`: Android App Perception Test, retaining the high-speed Camera2
  recorder and adding an opt-in Python yellow-puck tracker with a live green
  preview ring. It imports `androidAppPerceptionTesting/puck_tracker.py` via
  Chaquopy. Analysis samples the preview at up to 30 Hz, independently of the
  recording frame rate. A local TCP NDJSON server on port 8765 exposes native
  recording-pixel XY and normalized coordinates (not calibrated table units).
  See the Android README for setup, the output contract and device checks.
  An independent MP4 toggle now runs a frame-by-frame Python scan after Stop and
  produces an additional `_tracked.mp4` with the green circle burned into the video.
  The original recording is retained; no additional high-speed camera output is used.
- `src/perception/androidAppPerceptionTesting`: shared yellow-puck tracker,
  offline video runner and Android ARGB adapter with synthetic bridge tests.

- `src/perception/prototype`: a webcam tracker. It crops the table, converts to
  HSV, thresholds yellow, cleans the mask with morphology, filters regions by area
  and circularity, and tracks the puck centre. Sliders tune the mask. `r` records
  synchronized RGB and mask frames. Unit tests cover the tracker.
- `src/perception/input_testing/camera_latency.py`: shows a source clock and the
  received frame side by side and stamps frames with the Mac's clock, so
  camera-to-Mac delay can be read from a screen recording.
- `src/iphone_camera_test`: an iOS app that captures at a chosen frame rate and
  fixed shutter speed and reports the delivered rate. Written, not yet built or run.

## Camera plan (open)

The aim is 120 fps or more, because a fast puck moves several centimetres between
frames at 30 fps. Options considered, none decided:

| Option | Note |
|---|---|
| Continuity Camera / webcam apps | Generally limited to about 30 to 60 fps (verify per app). Good enough for a first version. |
| Custom iPhone app, tracking on the phone | The iPhone 13 can record 1080p at 120 and 240 fps. The app would send only (x, y, timestamp) to the Mac, which avoids streaming video. Needs Xcode. |
| USB high-frame-rate camera | The most predictable option. A PS3 Eye is a common cheap example. |

For any camera at 120 fps the exposure per frame must be shorter than 8.3 ms, so
the table needs bright, flicker-free (DC) lighting, with exposure, ISO and white
balance locked. Mains-powered LED and fluorescent lights flicker at 120 Hz in
Canada and beat against a 120 fps camera.

Measuring latency at this rate needs more than a 60 Hz screen can resolve. Options:
the camera's own capture timestamp with a clock sync over the link, an LED driven
by the ESP32 and detected in the frame, or a 120 Hz display flash.

## Filtering and what the policy sees (proposal)

Do not make the network learn wall bounces. They are simple known physics, and the
policy should learn strategy.

1. **State estimation:** a Kalman-style filter on `[x, y, vx, vy]`. Its predict
   step uses the same physics as the simulator: drag, and reflection at the walls
   with a restitution coefficient. Add velocity process noise near walls, and treat
   a spike in the measurement residual as a hit or bounce to correct.
2. **Latency compensation:** predict the state forward by the camera and control
   latency before it is given to the policy.
3. **Policy input:** the same 8 normalized values as the simulator, plus
   optionally predicted-trajectory features: where and when the puck will cross the
   mallet's defence line, found by unfolding wall reflections.
4. **Sim-to-real match:** the simulator currently adds noise directly to the true
   state in `get_observation`. Instead, feed simulated noisy measurements through
   the same filter with the same latency, and train on the filter output.
   Randomize noise, drag, restitution and latency.
5. **Calibration:** record real puck tracks, fit restitution and drag from them,
   and use the same values in the filter and the simulator. Check the filter's
   prediction error on recorded tracks before training on it.

## Table calibration (not implemented)

Four ArUco markers at the table corners give an image-to-table homography. Markers
should be flat, rigid, fully visible and outside the playable area. A red puck is
hard to separate from a red table, so use a contrasting matte marker.
