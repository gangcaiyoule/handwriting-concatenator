"""Load and validate the physical collection-sheet layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import BBoxMM, Cell, Marker, TemplateLayout


DEFAULT_LAYOUT_PATH = Path(__file__).parent / "assets" / "template_v2.json"


class TemplateError(ValueError):
    """The layout does not match the supported collection sheet."""


def _bbox(value: Any, *, name: str, page_size: tuple[float, float]) -> BBoxMM:
    if not isinstance(value, list) or len(value) != 4:
        raise TemplateError(f"{name} must contain four millimetre coordinates")
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise TemplateError(f"{name} contains a non-numeric coordinate") from exc
    if not (0 <= left < right <= page_size[0] and
            0 <= top < bottom <= page_size[1]):
        raise TemplateError(f"{name} lies outside the A4 page")
    return left, top, right, bottom


def load_template(path: str | Path | None = None) -> TemplateLayout:
    source = Path(path) if path is not None else DEFAULT_LAYOUT_PATH
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateError(f"Cannot read template layout: {source}") from exc

    if data.get("template_version") != 2:
        raise TemplateError("Only the ArUco template version 2 is supported")
    size = data.get("page_size_mm")
    if size != [210, 297] or data.get("coordinate_origin") != "top-left":
        raise TemplateError("Expected A4 coordinates measured from the top-left")
    if data.get("registration_marker_type") != "ArUco":
        raise TemplateError("Expected ArUco registration markers")
    dictionary = data.get("registration_dictionary")
    if dictionary != "DICT_4X4_50":
        raise TemplateError("Expected the DICT_4X4_50 marker dictionary")

    markers = tuple(
        Marker(
            id=int(item["id"]),
            corner=str(item["corner"]),
            bbox_mm=_bbox(item["bbox_mm"], name="marker bbox", page_size=(210, 297)),
        )
        for item in data.get("registration_markers", [])
    )
    if {marker.id for marker in markers} != {11, 17, 23, 29} or len(markers) != 4:
        raise TemplateError("The four expected marker IDs are 11, 17, 23 and 29")
    if {marker.corner for marker in markers} != {
        "top_left", "top_right", "bottom_left", "bottom_right"
    }:
        raise TemplateError("Each marker must identify a different page corner")

    cells: list[Cell] = []
    positions: set[tuple[int, int]] = set()
    sample_keys: set[tuple[str, int]] = set()
    for item in data.get("cells", []):
        row, column = int(item["row"]), int(item["column"])
        if (row, column) in positions:
            raise TemplateError(f"Duplicate cell at row {row}, column {column}")
        positions.add((row, column))
        char = item.get("character")
        write = item.get("write") is True
        occurrence = item.get("occurrence")
        if write and (not isinstance(char, str) or len(char) != 1 or char == " "
                      or not isinstance(occurrence, int) or occurrence < 1):
            raise TemplateError(f"Invalid writable cell at row {row}, column {column}")
        if write:
            sample_key = (char, occurrence)
            if sample_key in sample_keys:
                raise TemplateError(f"Duplicate sample {char!r} #{occurrence}")
            sample_keys.add(sample_key)
        cell_bbox = _bbox(item["cell_bbox_mm"], name="cell bbox", page_size=(210, 297))
        safe_bbox = _bbox(item["safe_bbox_mm"], name="safe bbox", page_size=(210, 297))
        if not (cell_bbox[0] < safe_bbox[0] < safe_bbox[2] < cell_bbox[2]
                and cell_bbox[1] < safe_bbox[1] < safe_bbox[3] < cell_bbox[3]):
            raise TemplateError(f"Safe bbox is outside cell {row}, {column}")
        cells.append(Cell(row, column, char, write, occurrence, cell_bbox, safe_bbox))
    if not cells or not any(cell.write for cell in cells):
        raise TemplateError("Template has no writable cells")

    return TemplateLayout(2, 210.0, 297.0, dictionary, markers, tuple(cells))
