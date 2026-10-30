"""Named font libraries stay separate and legacy data can be copied once."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app


LEGACY_ID = "b" * 32


def make_legacy(data_root: Path) -> None:
    root = data_root / "fonts" / "english" / LEGACY_ID
    (root / "cells").mkdir(parents=True)
    (root / "glyphs" / "U+0041").mkdir(parents=True)
    Image.new("RGB", (20, 20), "white").save(root / "registered_page.png")
    Image.new("RGB", (10, 10), "white").save(root / "cells" / "r01_c01.png")
    Image.new("RGBA", (8, 12), (0, 0, 0, 255)).save(
        root / "glyphs" / "U+0041" / "001.png"
    )
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "registered_page": "registered_page.png",
        "summary": {"sample_count": 1, "glyph_count": 1, "review_count": 0},
        "samples": [{
            "character": "A", "codepoint": "U+0041", "occurrence": 1,
            "row": 0, "column": 0, "flags": [], "accepted": None,
            "original_crop": "cells/r01_c01.png",
            "glyph_file": "glyphs/U+0041/001.png",
            "crop_size_px": [10, 10], "ink_bbox_in_crop_px": [1, 1, 9, 9],
        }],
    }), encoding="utf-8")
    (data_root / "file").mkdir(parents=True)
    (data_root / "file" / f"{LEGACY_ID}.jpg").write_bytes(b"old source")


def test_font_creation_and_legacy_claim_are_idempotent(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    make_legacy(data_root)
    with TestClient(create_app(data_root)) as client:
        first = client.post("/api/fonts", json={"name": "en-潦草"})
        assert first.status_code == 201, first.text
        assert first.json()["id"] == "en-潦草"
        assert first.json()["summary"]["sample_count"] == 0
        assert first.json()["legacy_imports"] == [LEGACY_ID]
        assert client.post("/api/fonts", json={"name": "EN-潦草"}).json()["id"] == "en-潦草"

        claim_url = f"/api/fonts/en-潦草/claim/{LEGACY_ID}"
        claimed = client.post(claim_url)
        assert claimed.status_code == 200, claimed.text
        result = claimed.json()
        assert result["summary"]["glyph_count"] == 1
        assert result["upload_count"] == 1
        assert result["legacy_imports"] == []
        assert client.get(result["registered_url"]).status_code == 200
        assert client.get(result["original_url"]).status_code == 200
        assert client.get(result["samples"][0]["glyph_url"]).status_code == 200
        assert client.get(result["samples"][0]["original_crop_url"]).status_code == 200
        assert client.post(claim_url).json()["summary"]["glyph_count"] == 1
        assert (data_root / "fonts" / "english" / LEGACY_ID / "manifest.json").is_file()

        other = client.post("/api/fonts", json={"name": "工整体"}).json()
        assert other["summary"]["glyph_count"] == 0
        assert other["legacy_imports"] == []
        assert [font["name"] for font in client.get("/api/fonts").json()] == ["en-潦草", "工整体"]
        assert client.post("/api/fonts", json={"name": "../bad"}).status_code == 422
        assert client.post("/api/fonts", json={"name": LEGACY_ID}).status_code == 422
