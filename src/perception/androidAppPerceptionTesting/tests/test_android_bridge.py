from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from android_bridge import AndroidTracker  # noqa: E402


def argb_pixels(image_bgr: np.ndarray) -> np.ndarray:
    """Pack BGR pixels as Android ARGB int values, returned as signed int32."""
    blue, green, red = (image_bgr[..., i].astype(np.uint32) for i in range(3))
    packed = 0xFF000000 | (red << 16) | (green << 8) | blue
    return packed.view(np.int32).reshape(-1)


def scene(width: int = 320, height: int = 240, center=(120, 110)) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    if center is not None:
        cv2.circle(image, center, 20, (0, 255, 255), -1)
    return image


def yuv420_planes(image_bgr: np.ndarray, row_padding: int = 0):
    """Return compact I420 planes copied into padded Android-style rows."""
    height, width = image_bgr.shape[:2]
    assert width % 2 == 0 and height % 2 == 0
    i420 = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2YUV_I420).reshape(-1)
    y_size = width * height
    c_size = y_size // 4
    y = i420[:y_size].reshape(height, width)
    u = i420[y_size:y_size + c_size].reshape(height // 2, width // 2)
    v = i420[y_size + c_size:].reshape(height // 2, width // 2)

    def padded(plane):
        stride = plane.shape[1] + row_padding
        result = np.zeros((plane.shape[0], stride), dtype=np.uint8)
        result[:, :plane.shape[1]] = plane
        return result.tobytes(), stride

    y_bytes, y_stride = padded(y)
    u_bytes, u_stride = padded(u)
    v_bytes, v_stride = padded(v)
    return y_bytes, u_bytes, v_bytes, y_stride, u_stride, v_stride


def yuv420_pixel_stride_two(image_bgr: np.ndarray):
    """Make U/V byte views matching separately based interleaved Android planes."""
    y_bytes, u_bytes, v_bytes, y_stride, u_stride, v_stride = yuv420_planes(image_bgr)
    height, width = image_bgr.shape[:2]
    i420 = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2YUV_I420).reshape(-1)
    y_size = width * height
    chroma_size = y_size // 4
    u = i420[y_size:y_size + chroma_size].reshape(height // 2, width // 2)
    v = i420[y_size + chroma_size:].reshape(height // 2, width // 2)
    u_view = np.zeros((height // 2, width), dtype=np.uint8)
    v_view = np.zeros((height // 2, width), dtype=np.uint8)
    u_view[:, ::2] = u
    v_view[:, ::2] = v
    return y_bytes, u_view.tobytes(), v_view.tobytes(), y_stride, width, width


def test_detects_yellow_puck_and_returns_full_frame_coordinates():
    width, height = 320, 240
    tracker = AndroidTracker()

    result = tracker.process_argb(argb_pixels(scene(width, height)), width, height)

    assert len(result) == 5
    x, y, radius, area, circularity = result
    assert x == pytest.approx(120, abs=2)
    assert y == pytest.approx(110, abs=2)
    assert radius == pytest.approx(20, abs=3)
    assert area > 0
    assert 0.6 <= circularity <= 1.0


def test_black_frame_is_lost_then_tracker_reacquires_after_miss_window():
    width, height = 320, 240
    tracker = AndroidTracker()
    assert tracker.process_argb(argb_pixels(scene(width, height)), width, height)

    black = argb_pixels(scene(width, height, center=None))
    for _ in range(12):
        assert tracker.process_argb(black, width, height) == []

    moved = argb_pixels(scene(width, height, center=(260, 110)))
    result = tracker.process_argb(moved, width, height)
    assert result
    assert result[0] == pytest.approx(260, abs=2)


def test_signed_argb_values_preserve_rgb_channel_order():
    # Red is deliberately excluded by the tracker's yellow HSV mask; a red
    # pixel being detected here would indicate an ARGB/BGR channel-order bug.
    red = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.circle(red, (160, 120), 22, (0, 0, 255), -1)
    packed = argb_pixels(red)
    assert np.any(packed < 0)  # exercise Java int[] signed representation
    assert AndroidTracker().process_argb(packed, 320, 240) == []


@pytest.mark.parametrize(
    ("pixels", "width", "height"),
    [([], 0, 1), ([], 1, 0), ([0, 0, 0], 2, 2), ([[0, 0]], 1, 1)],
)
def test_rejects_invalid_dimensions_or_pixel_shapes(pixels, width, height):
    with pytest.raises(ValueError):
        AndroidTracker().process_argb(pixels, width, height)


def test_reset_clears_tracking_history():
    tracker = AndroidTracker()
    assert tracker.process_argb(argb_pixels(scene()), 320, 240)
    tracker.reset()
    assert tracker.process_argb(argb_pixels(scene(center=None)), 320, 240) == []


def test_timestamp_adjusts_motion_window_for_30_fps_sampling():
    tracker = AndroidTracker()
    first = argb_pixels(scene(center=(80, 110)))
    second = argb_pixels(scene(center=(240, 110)))

    assert tracker.process_argb(first, 320, 240, 1_000_000_000)
    result = tracker.process_argb(second, 320, 240, 1_033_333_333)

    assert result
    assert result[0] == pytest.approx(240, abs=2)


def test_process_yuv420_detects_using_android_plane_strides():
    image = scene()
    y, u, v, ys, us, vs = yuv420_planes(image, row_padding=7)

    result = AndroidTracker().process_yuv420(
        y, u, v, 320, 240,
        ys, 1, us, 1, vs, 1,
        timestamp_ns=1_000_000_000,
    )

    assert len(result) == 5
    assert result[0] == pytest.approx(120, abs=3)
    assert result[1] == pytest.approx(110, abs=3)
    assert result[2] == pytest.approx(20, abs=4)


def test_process_yuv420_crop_returns_crop_relative_pixels():
    image = scene(center=(160, 120))
    y, u, v, ys, us, vs = yuv420_planes(image)

    result = AndroidTracker().process_yuv420(
        y, u, v, 320, 240,
        ys, 1, us, 1, vs, 1,
        crop_left=40, crop_top=20, crop_width=240, crop_height=200,
    )

    assert result[0] == pytest.approx(120, abs=3)
    assert result[1] == pytest.approx(100, abs=3)


def test_process_yuv420_pads_odd_image_edges():
    width, height = 319, 239
    y = np.full(width * height, 16, dtype=np.uint8)
    u = np.full(((width + 1) // 2) * ((height + 1) // 2), 128, dtype=np.uint8)
    v = u.copy()
    result = AndroidTracker().process_yuv420(
        y, u, v, width, height,
        width, 1, (width + 1) // 2, 1, (width + 1) // 2, 1,
    )
    assert result == []


def test_process_yuv420_handles_interleaved_chroma_pixel_stride_two():
    image = scene()
    y, u, v, ys, us, vs = yuv420_pixel_stride_two(image)

    result = AndroidTracker().process_yuv420(
        y, u, v, 320, 240,
        ys, 1, us, 2, vs, 2,
    )

    assert result[0] == pytest.approx(120, abs=3)
    assert result[1] == pytest.approx(110, abs=3)


def test_process_yuv420_handles_odd_crop_edges_and_lost_frame():
    image = scene(center=(160, 120))
    y, u, v, ys, us, vs = yuv420_planes(image)
    tracker = AndroidTracker()

    result = tracker.process_yuv420(
        y, u, v, 320, 240,
        ys, 1, us, 1, vs, 1,
        crop_left=41, crop_top=21, crop_width=239, crop_height=199,
    )
    assert result[0] == pytest.approx(119, abs=3)
    assert result[1] == pytest.approx(99, abs=3)

    black = scene(center=None)
    y, u, v, ys, us, vs = yuv420_planes(black)
    assert AndroidTracker().process_yuv420(y, u, v, 320, 240, ys, 1, us, 1, vs, 1) == []


def test_stale_timestamp_resets_before_reacquiring():
    tracker = AndroidTracker()
    assert tracker.process_argb(
        argb_pixels(scene(center=(80, 110))), 320, 240, 1_000_000_000
    )

    result = tracker.process_argb(
        argb_pixels(scene(center=(260, 110))), 320, 240, 1_500_000_000
    )

    assert result
    assert result[0] == pytest.approx(260, abs=2)
