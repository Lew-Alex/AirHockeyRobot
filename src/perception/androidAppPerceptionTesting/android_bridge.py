"""Small Python-facing adapter for calling the shared tracker from Android.

Kotlin should pass pixels from ``Bitmap.getPixels`` as a Java ``int[]``. The
values are packed ARGB, while the tracker expects a BGR ``uint8`` image.
"""

from __future__ import annotations

import numpy as np
import math
import cv2

from puck_tracker import PuckTracker


class AndroidTracker:
    """Convert packed Android pixels to BGR and run a persistent tracker."""

    def __init__(self) -> None:
        self._tracker = PuckTracker()
        self._last_timestamp_ns: int | None = None

    def reset(self) -> None:
        """Clear the tracker history, for example after a camera restart."""
        self._tracker = PuckTracker()
        self._last_timestamp_ns = None

    def process_argb(
        self, pixels, width: int, height: int, timestamp_ns: int | None = None
    ) -> list[float]:
        """Process packed ARGB pixels and return ``[x, y, r, area, circularity]``.

        ``pixels`` may be a Java signed ``int[]`` as produced by Android's
        ``Bitmap.getPixels``. Coordinates and radius are in the input bitmap's
        pixel units. ``timestamp_ns`` is an optional monotonic nanosecond time;
        when provided, motion and reacquisition thresholds are adjusted to the
        sampling interval. Returns an empty list when no puck is detected.
        """
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")

        packed = np.asarray(pixels, dtype=np.int64)
        if packed.ndim != 1 or packed.size != width * height:
            raise ValueError("pixels must be a flat array of width * height ARGB values")

        # Java int values above 0x7fffffff arrive signed; cast modulo 2**32 to
        # recover the original 0xAARRGGBB bit pattern. Alpha is not used.
        argb = packed.astype(np.uint32, copy=False).reshape(height, width)
        bgr = np.empty((height, width, 3), dtype=np.uint8)
        bgr[..., 0] = argb & 0xFF
        bgr[..., 1] = (argb >> 8) & 0xFF
        bgr[..., 2] = (argb >> 16) & 0xFF

        return self._process_bgr(bgr, width, height, timestamp_ns)

    def process_yuv420(
        self,
        y_plane,
        u_plane,
        v_plane,
        width: int,
        height: int,
        y_row_stride: int,
        y_pixel_stride: int,
        u_row_stride: int,
        u_pixel_stride: int,
        v_row_stride: int,
        v_pixel_stride: int,
        crop_left: int = 0,
        crop_top: int = 0,
        crop_width: int | None = None,
        crop_height: int | None = None,
        timestamp_ns: int | None = None,
    ) -> list[float]:
        """Process Android ``YUV_420_888`` planes without creating an ARGB bitmap.

        Plane inputs are byte-like buffers containing bytes from each Android
        ``Image.Plane`` buffer's current position. Strides are the corresponding
        plane row/pixel strides. The optional crop rectangle uses decoded-image
        coordinates. Results use crop-relative input pixels and the same five
        values as :meth:`process_argb`.
        """
        width, height = int(width), int(height)
        crop_left, crop_top = int(crop_left), int(crop_top)
        crop_width = width - crop_left if crop_width is None else int(crop_width)
        crop_height = height - crop_top if crop_height is None else int(crop_height)
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        if crop_left < 0 or crop_top < 0 or crop_width <= 0 or crop_height <= 0:
            raise ValueError("crop rectangle must have positive dimensions inside the image")
        if crop_left + crop_width > width or crop_top + crop_height > height:
            raise ValueError("crop rectangle must be inside the image")

        y_row_stride, y_pixel_stride = int(y_row_stride), int(y_pixel_stride)
        u_row_stride, u_pixel_stride = int(u_row_stride), int(u_pixel_stride)
        v_row_stride, v_pixel_stride = int(v_row_stride), int(v_pixel_stride)
        if min(y_row_stride, y_pixel_stride, u_row_stride, u_pixel_stride,
               v_row_stride, v_pixel_stride) <= 0:
            raise ValueError("plane strides must be positive")

        # Android's flexible format may use separate planar chroma (pixel stride
        # 1) or slices of interleaved chroma (pixel stride 2). Materialize a
        # compact I420 buffer directly from the strides and crop, then decode.
        y_src = np.frombuffer(y_plane, dtype=np.uint8)
        u_src = np.frombuffer(u_plane, dtype=np.uint8)
        v_src = np.frombuffer(v_plane, dtype=np.uint8)
        # I420 conversion requires even-origin/even-size planes. Include the
        # partial 2x2 blocks around odd crop edges, then slice back to the exact
        # caller crop after conversion.
        aligned_left = crop_left & ~1
        aligned_top = crop_top & ~1
        aligned_right = (crop_left + crop_width + 1) & ~1
        aligned_bottom = (crop_top + crop_height + 1) & ~1
        aligned_width = aligned_right - aligned_left
        aligned_height = aligned_bottom - aligned_top
        pad_right = max(0, aligned_right - width)
        pad_bottom = max(0, aligned_bottom - height)

        yy = (aligned_left + np.arange(min(aligned_width, width - aligned_left), dtype=np.intp)) * y_pixel_stride
        yr = aligned_top + np.arange(min(aligned_height, height - aligned_top), dtype=np.intp)
        y_index = yr[:, None] * y_row_stride + yy[None, :]
        if y_index.size and int(y_index.max()) >= y_src.size:
            raise ValueError("Y plane buffer is shorter than its declared strides")
        y = y_src[y_index]
        if pad_right or pad_bottom:
            y = np.pad(y, ((0, pad_bottom), (0, pad_right)), mode="edge")

        chroma_left = aligned_left // 2
        chroma_top = aligned_top // 2
        chroma_width = aligned_width // 2
        chroma_height = aligned_height // 2
        cx = chroma_left + np.arange(chroma_width, dtype=np.intp)
        cy = chroma_top + np.arange(min(chroma_height, (height + 1) // 2 - chroma_top), dtype=np.intp)
        ui = cy[:, None] * u_row_stride + (cx * u_pixel_stride)[None, :]
        vi = cy[:, None] * v_row_stride + (cx * v_pixel_stride)[None, :]
        if (ui.size and int(ui.max()) >= u_src.size) or (vi.size and int(vi.max()) >= v_src.size):
            raise ValueError("chroma plane buffer is shorter than its declared strides")
        u, v = u_src[ui], v_src[vi]

        chroma_w, chroma_h = aligned_width // 2, aligned_height // 2
        if u.shape[1] < chroma_w:
            u = np.pad(u, ((0, 0), (0, chroma_w - u.shape[1])), mode="edge")
            v = np.pad(v, ((0, 0), (0, chroma_w - v.shape[1])), mode="edge")
        if u.shape[0] < chroma_h:
            u = np.pad(u, ((0, chroma_h - u.shape[0]), (0, 0)), mode="edge")
            v = np.pad(v, ((0, chroma_h - v.shape[0]), (0, 0)), mode="edge")
        i420 = np.concatenate((y.reshape(-1), u[:chroma_h, :chroma_w].reshape(-1),
                               v[:chroma_h, :chroma_w].reshape(-1)))
        bgr = cv2.cvtColor(i420.reshape(aligned_height * 3 // 2, aligned_width), cv2.COLOR_YUV2BGR_I420)
        crop_offset_x, crop_offset_y = crop_left - aligned_left, crop_top - aligned_top
        bgr = bgr[crop_offset_y:crop_offset_y + crop_height,
                  crop_offset_x:crop_offset_x + crop_width]

        # Keep processing cost bounded for full-resolution camera recordings.
        scale = min(1.0, 1280.0 / max(crop_width, crop_height))
        if scale < 1.0:
            analysis_w = max(1, round(crop_width * scale))
            analysis_h = max(1, round(crop_height * scale))
            bgr = cv2.resize(bgr, (analysis_w, analysis_h), interpolation=cv2.INTER_AREA)
        else:
            analysis_w, analysis_h = crop_width, crop_height

        result = self._process_bgr(bgr, analysis_w, analysis_h, timestamp_ns)
        if result:
            factor_x, factor_y = crop_width / analysis_w, crop_height / analysis_h
            result[0] = (result[0] + 0.5) * factor_x - 0.5
            result[1] = (result[1] + 0.5) * factor_y - 0.5
            result[2] *= (factor_x + factor_y) / 2.0
            result[3] *= factor_x * factor_y
        return result

    def _process_bgr(self, bgr, width: int, height: int, timestamp_ns: int | None) -> list[float]:
        """Shared timing and tracker invocation for already-converted BGR data."""
        if timestamp_ns is not None:
            timestamp_ns = int(timestamp_ns)
            previous = self._last_timestamp_ns
            self._last_timestamp_ns = timestamp_ns
            if previous is not None:
                dt = (timestamp_ns - previous) / 1_000_000_000
                if dt <= 0 or dt > 0.4:
                    self._tracker = PuckTracker()
                else:
                    settings = self._tracker.s
                    settings.max_jump = min(
                        math.hypot(width * settings.scale, height * settings.scale),
                        60.0 * max(1.0, dt * 240.0),
                    )
                    settings.reacquire_after = max(1, math.ceil((12 / 240) / dt))
        detection = self._tracker.update(bgr)
        if detection is None:
            return []
        return [float(detection.x), float(detection.y), float(detection.radius),
                float(detection.area), float(detection.circularity)]
