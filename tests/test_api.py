"""HTTP upload writes the original and the extracted font set separately."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import shutil

import cv2
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.main import create_app
from handwriting_concat.cells import mm_bbox_to_px
from handwriting_concat.image_io import load_image
from handwriting_concat.template import load_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("pdftoppm") is None or
                    shutil.which("pdfinfo") is None,
                    reason="Poppler is needed to render the printed template")
def test_upload_and_browse_extracted_glyph(tmp_path: Path) -> None:
    page = load_image(PROJECT_ROOT / "手写字母采集模板_A4.pdf", pdf_dpi=160)
    layout = load_template()
    first_cell = next(cell for cell in layout.cells if cell.write)
    left, top, right, bottom = mm_bbox_to_px(first_cell.safe_bbox_mm,
                                              page.shape, layout)
    center = (left + right) // 2
    cv2.line(page, (center, top + 7), (center, bottom - 7),
             (0, 0, 0), 3)
    data = BytesIO()
    Image.fromarray(page).save(data, format="PNG")

    with TestClient(create_app(tmp_path / "data")) as client:
        response = client.post(
            "/api/imports", files={"file": ("filled.png", data.getvalue(), "image/png")}
        )
        assert response.status_code == 201, response.text
        result = response.json()
        run_id = result["id"]
        assert result["summary"]["sample_count"] == 387
        assert result["summary"]["glyph_count"] == 1
        assert (tmp_path / "data" / "file" / f"{run_id}.png").is_file()
        run_dir = tmp_path / "data" / "fonts" / "english" / run_id
        assert (run_dir / "glyphs" / "U+0041" / "001.png").is_file()
        assert client.get(f"/api/imports/{run_id}").status_code == 200
        assert client.get(f"/api/imports/{run_id}/manifest").status_code == 200
        assert client.get(result["registered_url"]).status_code == 200
        assert client.get(result["original_url"]).status_code == 200
        glyph = next(sample for sample in result["samples"] if sample["glyph_url"])
        assert client.get(glyph["glyph_url"]).status_code == 200
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["summary"]["glyph_count"] == 1
        assert client.get("/api/template").status_code == 200
        assert client.get("/").status_code == 200


def test_unsupported_upload_is_rejected(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "data")) as client:
        response = client.post(
            "/api/imports", files={"file": ("notes.txt", b"not an image", "text/plain")}
        )
        assert response.status_code == 422
        file_dir = tmp_path / "data" / "file"
        assert not file_dir.exists() or not any(file_dir.iterdir())
