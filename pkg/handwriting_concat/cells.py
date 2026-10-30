"""Convert physical cell positions into pixel crops on a registered page."""

from __future__ import annotations

import numpy as np

from .types import BBoxMM, BBoxPX, Cell, TemplateLayout


def mm_bbox_to_px(bbox: BBoxMM, image_shape: tuple[int, ...],
                  layout: TemplateLayout) -> BBoxPX:
    height, width = image_shape[:2]
    left, top, right, bottom = bbox
    pixel_bbox = (
        round(left * width / layout.width_mm),
        round(top * height / layout.height_mm),
        round(right * width / layout.width_mm),
        round(bottom * height / layout.height_mm),
    )
    x1, y1, x2, y2 = pixel_bbox
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f"Cell bbox {bbox} is outside the registered page")
    return pixel_bbox


def crop_cell(page_rgb: np.ndarray, cell: Cell,
              layout: TemplateLayout) -> tuple[np.ndarray, BBoxPX]:
    bbox = mm_bbox_to_px(cell.safe_bbox_mm, page_rgb.shape, layout)
    x1, y1, x2, y2 = bbox
    return page_rgb[y1:y2, x1:x2].copy(), bbox
