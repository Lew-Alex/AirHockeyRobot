"""Core yellow-mask puck detection functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np


@dataclass(frozen=True)
class MaskSettings:
    lower_h: int = 18
    lower_s: int = 90
    lower_v: int = 90
    upper_h: int = 42
    upper_s: int = 255
    upper_v: int = 255
    min_area: float = 250.0
    max_area: float = 50_000.0
    min_circularity: float = 0.55
    kernel_size: int = 5
    crop_left_x: int = 0
    crop_top_y: int = 0
    crop_right_x: int = 0
    crop_bottom_y: int = 0

    @property
    def lower(self) -> np.ndarray:
        return np.array((self.lower_h, self.lower_s, self.lower_v), dtype=np.uint8)

    @property
    def upper(self) -> np.ndarray:
        return np.array((self.upper_h, self.upper_s, self.upper_v), dtype=np.uint8)


@dataclass(frozen=True)
class PuckDetection:
    center: tuple[int, int]
    radius: float
    area: float
    circularity: float
    contour: np.ndarray


def crop_frame(
    frame: np.ndarray,
    settings: MaskSettings,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Crop a frame and return (crop, (left, top, right, bottom)).

    Right or bottom values of zero mean the corresponding full-frame edge.
    Bounds are clamped so the result always contains at least one pixel.
    """
    height, width = frame.shape[:2]
    left = min(max(0, int(settings.crop_left_x)), max(0, width - 1))
    top = min(max(0, int(settings.crop_top_y)), max(0, height - 1))
    requested_right = int(settings.crop_right_x) or width
    requested_bottom = int(settings.crop_bottom_y) or height
    right = min(max(left + 1, requested_right), width)
    bottom = min(max(top + 1, requested_bottom), height)
    return frame[top:bottom, left:right].copy(), (left, top, right, bottom)


def make_yellow_mask(frame: np.ndarray, settings: MaskSettings) -> np.ndarray:
    """Return a cleaned binary mask containing yellow pixels."""
    blurred = cv2.GaussianBlur(frame, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, settings.lower, settings.upper)

    size = max(1, int(settings.kernel_size))
    if size % 2 == 0:
        size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def find_candidates(mask: np.ndarray, settings: MaskSettings) -> list[PuckDetection]:
    """Find approximately circular yellow regions that could be the puck."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[PuckDetection] = []

    for contour in contours:
        area = float(cv2.contourArea(contour))
        if not settings.min_area <= area <= settings.max_area:
            continue

        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        circularity = float(4.0 * np.pi * area / (perimeter * perimeter))
        if circularity < settings.min_circularity:
            continue

        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        center = (
            int(round(moments["m10"] / moments["m00"])),
            int(round(moments["m01"] / moments["m00"])),
        )
        _, radius = cv2.minEnclosingCircle(contour)
        candidates.append(
            PuckDetection(
                center=center,
                radius=float(radius),
                area=area,
                circularity=circularity,
                contour=contour,
            )
        )

    return candidates


def select_puck(
    candidates: Iterable[PuckDetection],
    previous_center: tuple[float, float] | None,
) -> PuckDetection | None:
    """Select the most plausible puck, favouring continuity after acquisition."""
    choices = list(candidates)
    if not choices:
        return None
    if previous_center is None:
        return max(choices, key=lambda item: item.area * item.circularity)

    px, py = previous_center
    return min(
        choices,
        key=lambda item: (item.center[0] - px) ** 2 + (item.center[1] - py) ** 2,
    )


def detect_puck(
    frame: np.ndarray,
    settings: MaskSettings,
    previous_center: tuple[float, float] | None = None,
) -> tuple[PuckDetection | None, np.ndarray]:
    mask = make_yellow_mask(frame, settings)
    return select_puck(find_candidates(mask, settings), previous_center), mask
