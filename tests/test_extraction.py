"""End-to-end checks for registration, cell mapping and glyph extraction."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image
import pytest

from handwriting_concat.cells import mm_bbox_to_px
from handwriting_concat.image_io import load_image
from handwriting_concat.pipeline import extract_page
from handwriting_concat.registration import RegistrationError, register_page
from handwriting_concat.template import load_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PDF = PROJECT_ROOT / "手写字母采集模板_A4.pdf"


def test_template_has_four_unique_markers_and_expected_samples() -> None:
    layout = load_template()
    assert layout.version == 2
    assert {marker.id for marker in layout.markers} == {11, 17, 23, 29}
    assert sum(cell.write for cell in layout.cells) == 387
    assert any(cell.character == "i" and cell.write for cell in layout.cells)


@pytest.mark.skipif(shutil.which("pdftoppm") is None or
                    shutil.which("pdfinfo") is None,
                    reason="Poppler is needed to render the printed template")
def test_blank_template_does_not_create_false_glyphs(tmp_path: Path) -> None:
    report = extract_page(TEMPLATE_PDF, tmp_path / "blank", pdf_dpi=160)
    assert report.sample_count == 387
    assert report.glyph_count == 0
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert all(sample["flags"] == ["empty"] for sample in manifest["samples"])


def test_perspective_and_rotation_keep_detached_ink_in_one_glyph(
    tmp_path: Path,
) -> None:
    layout = load_template()
    dpi = 160
    width = round(layout.width_mm / 25.4 * dpi)
    height = round(layout.height_mm / 25.4 * dpi)
    page = np.full((height, width, 3), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for marker in layout.markers:
        x1, y1, x2, y2 = mm_bbox_to_px(marker.bbox_mm, page.shape, layout)
        code = cv2.aruco.generateImageMarker(
            dictionary, marker.id, max(x2 - x1, y2 - y1)
        )
        code = cv2.resize(code, (x2 - x1, y2 - y1),
                          interpolation=cv2.INTER_NEAREST)
        page[y1:y2, x1:x2] = cv2.cvtColor(code, cv2.COLOR_GRAY2RGB)

    a_cell = next(cell for cell in layout.cells
                  if cell.write and cell.character == "A")
    i_cell = next(cell for cell in layout.cells
                  if cell.write and cell.character == "i")
    ax1, ay1, ax2, ay2 = mm_bbox_to_px(a_cell.safe_bbox_mm, page.shape, layout)
    cx, top, bottom = (ax1 + ax2) // 2, ay1 + 5, ay2 - 5
    cv2.line(page, (cx, top), (ax1 + 6, bottom), (0, 0, 0), 2)
    cv2.line(page, (cx, top), (ax2 - 6, bottom), (0, 0, 0), 2)
    cv2.line(page, (ax1 + 12, ay1 + (ay2 - ay1) // 2),
             (ax2 - 12, ay1 + (ay2 - ay1) // 2), (0, 0, 0), 2)

    ix1, iy1, ix2, iy2 = mm_bbox_to_px(i_cell.safe_bbox_mm, page.shape, layout)
    ix = (ix1 + ix2) // 2
    cv2.circle(page, (ix, iy1 + 7), 2, (0, 0, 0), -1)
    cv2.line(page, (ix, iy1 + 17), (ix, iy2 - 5), (0, 0, 0), 2)

    source = np.float32([[0, 0], [width - 1, 0],
                         [width - 1, height - 1], [0, height - 1]])
    target = np.float32([[100, 65], [width + 60, 85],
                         [width + 35, height + 75], [75, height + 45]])
    transformed = cv2.warpPerspective(
        page, cv2.getPerspectiveTransform(source, target),
        (width + 150, height + 140), borderValue=(255, 255, 255)
    )
    transformed = cv2.rotate(transformed, cv2.ROTATE_180)
    input_file = tmp_path / "filled.png"
    Image.fromarray(transformed).save(input_file)

    report = extract_page(input_file, tmp_path / "result")
    assert report.sample_count == 387
    assert report.glyph_count == 2
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    glyphs = {sample["character"]: sample for sample in manifest["samples"]
              if sample["glyph_file"]}
    assert set(glyphs) == {"A", "i"}
    i_png = Image.open(report.output_dir / glyphs["i"]["glyph_file"])
    alpha = np.asarray(i_png)[:, :, 3]
    components, _ = cv2.connectedComponents((alpha > 32).astype(np.uint8))
    assert components >= 3  # background, stem and dot

    with pytest.raises(RegistrationError, match="Missing ArUco markers"):
        register_page(transformed[300:-300, 300:-300], layout)
