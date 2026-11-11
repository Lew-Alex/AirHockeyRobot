# FastCam

A minimal Android camera app (Pixel 10 Pro target) that records 60/120/240fps video with the
fastest sensor readout it can get, and saves per-frame metadata for later filtering.

## Build & install (one-time setup)

1. Install **Android Studio** from https://developer.android.com/studio (includes Java + Android SDK).
2. Open Android Studio → **Open** → select this `FastCam` folder. Let it finish "Gradle sync"
   (first time downloads a few hundred MB). If it offers to upgrade the Android Gradle Plugin, accept.
3. On the phone: Settings → About phone → tap **Build number** 7 times (enables Developer options).
   Then Settings → System → Developer options → turn on **USB debugging**.
4. Plug the phone in via USB, tap **Allow** on the phone's prompt.
5. In Android Studio pick the phone in the device dropdown and press the green **Run ▶** button.

## Using it

- **Mode dropdown**: every 60fps+ mode the camera supports.
  - `(high-speed)` = 120/240fps modes. Fastest readout, but exposure is automatic only.
  - `(standard)` = 60fps modes. Allows a manual fast shutter (1/250 … 1/4000s) to cut motion blur.
- **Top overlay** shows the camera-reported **rolling shutter** time (sensor top-to-bottom readout),
  exposure, ISO and measured fps. Try modes and pick the one with the lowest rolling shutter number.
- **REC / STOP** records. Files are saved to:
  - `Movies/FastCam/FASTCAM_<date>_<WxH>_<fps>fps.mp4` (HEVC, no audio)
  - `Download/FastCam/FASTCAM_<...>.csv` per-frame metadata

## About rolling shutter

Android apps can't directly set sensor readout speed; it's fixed by the sensor mode the camera picks
for a resolution + frame rate. High frame rate modes must read a full frame in < 1/fps seconds, so
120/240fps modes are usually the fastest readout. Lower resolution often reads out faster too.
Shutter speed (exposure) affects motion blur, not rolling-shutter skew.

## CSV format

```
frame_number,sensor_timestamp_ns,exposure_ns,rolling_shutter_skew_ns,frame_duration_ns,iso
```

Row `r` (0 = top of sensor) of a frame begins exposing at
`sensor_timestamp_ns + rolling_shutter_skew_ns * r / (rows - 1)`.
Note the sensor is landscape; the video is rotated to portrait via an MP4 orientation flag, so in
the displayed (portrait) video the sensor "rows" run along the horizontal axis. Video stabilization
is turned off in standard modes so frames aren't warped.
