"""Conservatively separate dark handwriting from a light paper background."""

from __future__ import annotations

import cv2
import numpy as np

from .types import InkResult


def extract_ink(crop_rgb: np.ndarray) -> InkResult:
    """Return one RGBA glyph for the entire cell, including detached dots.

    This intentionally does not split connected components: punctuation and
    letters such as i and j may consist of multiple separate ink regions.
    """
    if crop_rgb.ndim != 3 or crop_rgb.shape[2] != 3:
        raise ValueError("Expected an RGB cell crop")
    height, width = crop_rgb.shape[:2]
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)

    # Closing estimates the paper illumination beneath narrow, dark strokes.
    # A per-cell background tolerates shadows better than one page-wide cutoff.
    kernel_width = max(9, min(height, width) // 3)
    kernel_width += 1 - kernel_width % 2
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_width, kernel_width)
    )
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    contrast = cv2.subtract(background, gray)
    peak_contrast = float(np.max(contrast))

    # Keep antialiasing as soft alpha. A tiny number of dark pixels may be a
    # period, so only clearly empty cells are omitted automatically.
    alpha = np.clip((contrast.astype(np.float32) - 12.0) * (255.0 / 68.0),
                    0, 255).astype(np.uint8)
    foreground = alpha >= 32
    foreground_pixels = int(np.count_nonzero(foreground))
    minimum_pixels = max(3, round(height * width * 0.0004))
    if foreground_pixels < minimum_pixels:
        return InkResult(None, None, foreground_pixels, peak_contrast, False)

    ys, xs = np.nonzero(foreground)
    left, top = int(xs.min()), int(ys.min())
    right, bottom = int(xs.max()) + 1, int(ys.max()) + 1
    touches_border = (left <= 1 or top <= 1 or
                      right >= width - 1 or bottom >= height - 1)
    margin = max(1, round(min(height, width) * 0.025))
    crop_left = max(0, left - margin)
    crop_top = max(0, top - margin)
    crop_right = min(width, right + margin)
    crop_bottom = min(height, bottom + margin)

    strong_ink = contrast >= 80
    color_mask = strong_ink if np.any(strong_ink) else foreground
    ink_color = np.median(crop_rgb[color_mask], axis=0).astype(np.uint8)
    rgba = np.empty((crop_bottom - crop_top, crop_right - crop_left, 4),
                    dtype=np.uint8)
    rgba[:, :, :3] = ink_color
    rgba[:, :, 3] = alpha[crop_top:crop_bottom, crop_left:crop_right]
    return InkResult(
        rgba=rgba,
        ink_bbox_px=(left, top, right, bottom),
        foreground_pixels=foreground_pixels,
        peak_contrast=peak_contrast,
        touches_border=touches_border,
    )
