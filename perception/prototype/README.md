# Yellow Puck Tracker Prototype

This standalone prototype reads a webcam, creates an HSV yellow mask, filters
yellow regions by area and circularity, and tracks the selected puck centre.

## Setup

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

On macOS, allow the terminal or Python application to access the camera when
prompted.

## Run

```bash
python3 puck_tracker.py
```

If the wrong camera opens:

```bash
python3 puck_tracker.py --camera 1
```

Optional capture requests:

```bash
python3 puck_tracker.py --camera 0 --width 1280 --height 720 --fps 60
```

The camera may choose the nearest supported resolution or frame rate.

## Controls

- Adjust the HSV, area, circularity, and morphology sliders while viewing the
  `Yellow mask` window. The puck should be solid white and most of the table
  should be black.
- Use `Crop left X` and `Crop top Y` for the top-left corner of the region to
  process. Use `Crop right X` and `Crop bottom Y` for its bottom-right corner.
  The tracker window and reported puck coordinates are relative to this crop.
- Press `s` to save the current values to `settings.json`.
- Press `c` to clear the current tracked object and reacquire it.
- Press `r` to begin recording synchronized clean RGB and mask frames. Press
  `r` again to stop. Every take is saved under `recordings/<timestamp>/`, with
  matching numbered files in its `rgb/` and `mask/` folders. A red `REC`
  indicator appears in the tracker window but is not included in saved frames.
- Press `q` or Escape to quit.

For the best result, use a matte yellow marker on top of the puck, fixed camera
settings, bright diffuse lighting, and minimal yellow elsewhere in view.

## Test

```bash
python3 -m unittest discover -s tests
```
