"""Internal data types, independent of HTTP and storage formats."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np


BBoxMM: TypeAlias = tuple[float, float, float, float]
BBoxPX: TypeAlias = tuple[int, int, int, int]


@dataclass(frozen=True)
class Marker:
    id: int
    corner: str
    bbox_mm: BBoxMM


@dataclass(frozen=True)
class Cell:
    row: int
    column: int
    character: str | None
    write: bool
    occurrence: int | None
    cell_bbox_mm: BBoxMM
    safe_bbox_mm: BBoxMM


@dataclass(frozen=True)
class TemplateLayout:
    version: int
    width_mm: float
    height_mm: float
    dictionary_name: str
    markers: tuple[Marker, ...]
    cells: tuple[Cell, ...]


@dataclass
class RegisteredPage:
    rgb: np.ndarray
    homography: np.ndarray
    detected_ids: tuple[int, ...]
    reprojection_rms_px: float
    output_dpi: float
    input_size_px: tuple[int, int]


@dataclass
class InkResult:
    rgba: np.ndarray | None
    ink_bbox_px: BBoxPX | None
    foreground_pixels: int
    peak_contrast: float
    touches_border: bool


@dataclass(frozen=True)
class ExtractionReport:
    output_dir: Path
    sample_count: int
    glyph_count: int
    review_count: int
    manifest_path: Path
