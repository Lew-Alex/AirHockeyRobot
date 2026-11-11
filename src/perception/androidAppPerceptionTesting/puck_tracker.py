"""Very simple yellow-puck tracker: colour mask, clean-up, blob filter, continuity.

Only uses OpenCV calls that exist in the Android OpenCV SDK (GaussianBlur, cvtColor, inRange,
morphologyEx, findContours, moments), so the same steps can be ported to the phone later.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Settings:
    # Yellow puck in OpenCV HSV (H 0-179). Measured on the video: H 26-29, S ~160, V ~190.
    lower: tuple = (22, 90, 70)   # wide enough for the puck in shadow; H >= 22 stays clear of skin
    upper: tuple = (40, 255, 255)
    scale: float = 0.5            # work on a half-size frame (4x fewer pixels)
    kernel: int = 3               # morphology kernel at working size
    min_area: float = 80.0        # blob area limits, in working-size pixels
    max_area: float = 2500.0
    min_circularity: float = 0.6  # strict shape test when looking for the puck from scratch
    track_min_area: float = 6.0   # relaxed tests near the last position: a hand or the rail can hide part
    track_min_circularity: float = 0.2
    max_jump: float = 60.0        # max centre move between frames, in working-size pixels
    reacquire_after: int = 12     # after this many missed frames, accept a blob anywhere


@dataclass
class Detection:
    x: float                      # full-size frame pixels
    y: float
    radius: float
    area: float
    circularity: float


class PuckTracker:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings()
        self.last = None          # last centre, working-size pixels
        self.missed = 0
        k = self.s.kernel
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    def make_mask(self, frame_bgr):
        small = cv2.resize(frame_bgr, None, fx=self.s.scale, fy=self.s.scale, interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(self.s.lower, np.uint8), np.array(self.s.upper, np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)    # remove speckles
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel)   # fill holes in the puck
        return mask

    def candidates(self, mask, relaxed):
        min_area = self.s.track_min_area if relaxed else self.s.min_area
        min_circ = self.s.track_min_circularity if relaxed else self.s.min_circularity
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for c in contours:
            area = cv2.contourArea(c)
            if not min_area <= area <= self.s.max_area:
                continue
            perimeter = cv2.arcLength(c, True)
            if perimeter <= 0:
                continue
            circularity = 4.0 * np.pi * area / (perimeter * perimeter)
            if circularity < min_circ:
                continue
            m = cv2.moments(c)
            if m["m00"] == 0:
                continue
            found.append((m["m10"] / m["m00"], m["m01"] / m["m00"], float(np.sqrt(area / np.pi)), area, circularity))
        return found

    def update(self, frame_bgr):
        """Returns a Detection in full-size pixels, or None when the puck is lost this frame."""
        mask = self.make_mask(frame_bgr)
        tracking = self.last is not None and self.missed < self.s.reacquire_after
        found = self.candidates(mask, relaxed=tracking)

        if found and tracking:
            lx, ly = self.last
            found = [f for f in found if (f[0] - lx) ** 2 + (f[1] - ly) ** 2 <= self.s.max_jump ** 2]

        if not found:
            self.missed += 1
            return None

        # nearest to the last position, or the most puck-like blob when starting fresh
        if not tracking:
            best = max(found, key=lambda f: f[3] * f[4])
        else:
            lx, ly = self.last
            best = min(found, key=lambda f: (f[0] - lx) ** 2 + (f[1] - ly) ** 2)

        self.last = (best[0], best[1])
        self.missed = 0
        inv = 1.0 / self.s.scale
        return Detection(best[0] * inv, best[1] * inv, best[2] * inv, best[3] * inv * inv, best[4])
