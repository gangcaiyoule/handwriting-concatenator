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
        selected = client.post("/api/fonts", json={"name": "en-潦草"})
        assert selected.status_code == 201, selected.text
        assert selected.json()["summary"]["glyph_count"] == 0
        assert client.get("/api/fonts").json()[0]["name"] == "en-潦草"
        response = client.post(
            "/api/imports", data={"font_name": "en-潦草"},
            files={"file": ("filled.png", data.getvalue(), "image/png")}
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["id"] == "en-潦草"
        run_id = result["latest_upload_id"]
        assert result["summary"]["sample_count"] == 395
        assert result["summary"]["glyph_count"] == 1
        assert (tmp_path / "data" / "file" / f"{run_id}.png").is_file()
        run_dir = tmp_path / "data" / "fonts" / "english" / "en-潦草"
        assert (run_dir / "glyphs" / "U+0041" / f"{run_id}-001.png").is_file()
        assert client.get("/api/imports/en-潦草").status_code == 200
        assert client.get("/api/imports/en-潦草/manifest").status_code == 200
        assert client.get(result["registered_url"]).status_code == 200
        assert client.get(result["original_url"]).status_code == 200
        glyph = next(sample for sample in result["samples"] if sample["glyph_url"])
        assert client.get(glyph["glyph_url"]).status_code == 200
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["summary"]["glyph_count"] == 1
        assert manifest["uploads"][0]["id"] == run_id
        assert manifest["samples"][0]["upload_id"] == run_id

        second = client.post(
            "/api/imports", data={"font_name": "en-潦草"},
            files={"file": ("filled-again.png", data.getvalue(), "image/png")}
        )
        assert second.status_code == 201, second.text
        again = second.json()
        assert again["upload_count"] == 2
        assert again["latest_upload_id"] != run_id
        assert again["summary"]["sample_count"] == 790
        assert again["summary"]["glyph_count"] == 2
        assert len(list((run_dir / "glyphs" / "U+0041").glob("*.png"))) == 2
        composed = client.post("/api/compositions", json={
            "font_id": "en-潦草", "text": "AA", "seed": 12,
        })
        assert composed.status_code == 201, composed.text
        draft = client.get(f"/api/compositions/{composed.json()['id']}/draft").json()
        assert len({item["sample_file"] for item in draft["placements"]}) == 2

        other = client.post("/api/fonts", json={"name": "工整体"})
        assert other.status_code == 201
        assert other.json()["summary"]["glyph_count"] == 0
        assert client.get("/api/fonts").json()[1]["name"] == "工整体"
        assert client.get("/api/imports/工整体").json()["samples"] == []
        assert client.get("/api/template").status_code == 200
        assert client.get("/").status_code == 200


def test_unsupported_upload_is_rejected(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "data")) as client:
        response = client.post(
            "/api/imports", data={"font_name": "en-潦草"},
            files={"file": ("notes.txt", b"not an image", "text/plain")}
        )
        assert response.status_code == 422
        file_dir = tmp_path / "data" / "file"
        assert not file_dir.exists() or not any(file_dir.iterdir())
