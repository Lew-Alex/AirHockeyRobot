"""Run the puck tracker over a video and report how many frames lost the puck.

    ../prototype/.venv/bin/python run_video.py [video.mp4]

Writes out/tracks.csv (frame, time, x, y, radius), out/annotated.mp4 and out/lost_frames.jpg.
"""

import csv
import os
import sys
import time

import cv2

from puck_tracker import PuckTracker

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "FASTCAM_20261110_230026_1280x720_240fps.mp4")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

cap = cv2.VideoCapture(VIDEO)
fps = cap.get(cv2.CAP_PROP_FPS)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
tracker = PuckTracker()

writer = None
rows, lost, lost_frames = [], 0, []
start = time.time()
index = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    det = tracker.update(frame)
    t = index / fps
    if det is None:
        lost += 1
        lost_frames.append(index)
        rows.append((index, round(t, 4), "", "", ""))
    else:
        rows.append((index, round(t, 4), round(det.x, 1), round(det.y, 1), round(det.radius, 1)))

    # annotated copy at half size
    view = cv2.resize(frame, None, fx=0.5, fy=0.5)
    if det is not None:
        cv2.circle(view, (int(det.x / 2), int(det.y / 2)), int(det.radius / 2) + 6, (0, 255, 0), 2)
    else:
        cv2.putText(view, "LOST", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
    if writer is None:
        writer = cv2.VideoWriter(os.path.join(OUT, "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 60,
                                 (view.shape[1], view.shape[0]))
    writer.write(view)
    index += 1

elapsed = time.time() - start
writer.release()
with open(os.path.join(OUT, "tracks.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["frame", "time_s", "x", "y", "radius"])
    w.writerows(rows)

# longest run of lost frames
longest, run = 0, 0
for i, r in enumerate(rows):
    run = run + 1 if r[2] == "" else 0
    longest = max(longest, run)

print(f"video: {os.path.basename(VIDEO)}  {index} frames at {fps:.1f} fps")
print(f"lost: {lost} frames = {100 * lost / index:.2f}%   tracked: {index - lost} frames = {100 * (index - lost) / index:.2f}%")
print(f"longest lost run: {longest} frames ({1000 * longest / fps:.0f} ms)")
print(f"processing speed: {index / elapsed:.0f} frames/s (offline, incl. video decode and writing)")
with open(os.path.join(OUT, "lost_frames.txt"), "w") as f:
    f.write("\n".join(map(str, lost_frames)))
