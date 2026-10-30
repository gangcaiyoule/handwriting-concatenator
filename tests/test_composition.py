"""Line breaks and per-character glyph reuse follow the composition rules."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from api.main import create_app
from handwriting_concat.composition import (
    CompositionOptions,
    MissingGlyphs,
    compose_text,
)


FONT_ID = "a" * 32


def make_font(root: Path) -> Path:
    root.mkdir(parents=True)
    samples = []
    for character in "AB":
        for occurrence in (1, 2):
            relative = f"glyphs/U+{ord(character):04X}/{occurrence:03d}.png"
            image_path = root / relative
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (12, 22), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rectangle((2, 2, 9, 19), fill=(25 * occurrence, 25, 25, 255))
            image.save(image_path)
            samples.append({
                "character": character,
                "glyph_file": relative,
                "accepted": None,
                "crop_size_px": [22, 30],
                "ink_bbox_in_crop_px": [4, 5, 12, 23],
                "row": occurrence - 1,
                "column": 0,
            })
    (root / "manifest.json").write_text(
        json.dumps({"samples": samples}), encoding="utf-8"
    )
    return root


def test_line_breaks_and_seeded_selection(tmp_path: Path) -> None:
    font = make_font(tmp_path / "font")
    options = CompositionOptions(seed=123, cell_height_px=60)
    first = compose_text("AB\r\n\r\nBA", font, options)
    second = compose_text("AB\n\nBA", font, options)
    assert first.text == "AB\n\nBA"
    assert first.line_count == 3
    assert [item["line"] for item in first.placements] == [0, 0, 2, 2]
    assert len({item["sample_file"] for item in first.placements}) == 4
    assert first.placements == second.placements
    assert first.image.tobytes() == second.image.tobytes()


def test_reuse_starts_only_after_every_variant_was_used(tmp_path: Path) -> None:
    font = make_font(tmp_path / "font")
    result = compose_text("AAAAA", font, CompositionOptions(seed=123))
    chosen = [item["sample_file"] for item in result.placements]
    assert len(set(chosen[:2])) == 2
    assert len(set(chosen[2:4])) == 2
    assert chosen[1] != chosen[2]


def test_composition_requires_at_least_one_sample_per_character(tmp_path: Path) -> None:
    font = make_font(tmp_path / "font")
    with pytest.raises(MissingGlyphs) as caught:
        compose_text("AAC", font)
    assert caught.value.missing == [
        {"character": "C", "required": 1, "available": 0}
    ]


def test_composition_http_api(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    make_font(data_root / "fonts" / "english" / FONT_ID)
    with TestClient(create_app(data_root)) as client:
        payload = {"font_id": FONT_ID, "text": "AB\nBA", "seed": 17}
        response = client.post("/api/compositions", json=payload)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["line_count"] == 2
        assert result["seed"] == 17
        assert client.get(result["image_url"]).status_code == 200
        assert client.get(result["download_url"]).status_code == 200
        assert client.get(f"/api/compositions/{result['id']}").status_code == 200
        manifest_path = (data_root / "renders" / "english" / result["id"]
                         / "manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["text"] == "AB\nBA"
        assert len({item["sample_file"] for item in manifest["placements"]}) == 4

        repeated = client.post("/api/compositions", json={
            "font_id": FONT_ID, "text": "AAAA"
        })
        assert repeated.status_code == 201, repeated.text
        repeated_id = repeated.json()["id"]
        repeated_manifest = json.loads((data_root / "renders" / "english"
                                        / repeated_id / "manifest.json").read_text(encoding="utf-8"))
        reused_files = [item["sample_file"] for item in repeated_manifest["placements"]]
        assert len(set(reused_files[:2])) == 2
        assert len(set(reused_files[2:])) == 2

        missing = client.post("/api/compositions", json={
            "font_id": FONT_ID, "text": "AAC"
        })
        assert missing.status_code == 422
        assert missing.json()["detail"]["missing"][0]["character"] == "C"
