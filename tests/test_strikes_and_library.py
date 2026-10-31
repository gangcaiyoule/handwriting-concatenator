"""Deleted glyphs stay out of new renders; strike spans survive edits."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from api.main import create_app
from handwriting_concat.composition import CompositionError, parse_strikethrough
from tests.test_words import make_font


def add_handwritten_marks(font_root: Path) -> None:
    path = font_root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for character, points in (
        ("→", [(1, 9), (24, 9), (18, 4), (24, 9), (18, 14)]),
        ("\ue000", [(1, 8), (8, 7), (16, 9), (25, 6)]),
        ("\ue001", [(1, 16), (10, 12), (18, 7), (25, 3)]),
    ):
        relative = f"glyphs/U+{ord(character):04X}/001.png"
        image_path = font_root / relative
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (27, 19))
        ImageDraw.Draw(image).line(points, fill=(12, 12, 12, 255), width=2)
        image.save(image_path)
        manifest["samples"].append({
            "character": character, "codepoint": f"U+{ord(character):04X}",
            "occurrence": 1, "glyph_file": relative,
            "original_crop": f"cells/{ord(character)}.png",
            "crop_size_px": [30, 24], "ink_bbox_in_crop_px": [1, 3, 28, 22],
            "accepted": None, "flags": [], "row": 19, "column": 14,
        })
    manifest["summary"]["sample_count"] += 3
    manifest["summary"]["glyph_count"] += 3
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_strike_syntax_and_saved_render(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    font_root = data_root / "fonts" / "english" / "letters"
    make_font(font_root)
    assert parse_strikethrough("A ~~AB~~ B\n~~A~~") == (
        "A AB B\nA", [{"line": 0, "column": 2, "end_column": 4},
                      {"line": 1, "column": 0, "end_column": 1}],
    )
    for invalid in ("A~~AB~~", "~~AB~~B", "~~A B~~", "~~A"):
        try:
            parse_strikethrough(invalid)
        except CompositionError:
            pass
        else:
            raise AssertionError(f"Accepted invalid strike syntax: {invalid}")

    with TestClient(create_app(data_root)) as client:
        missing_mark = client.post("/api/compositions", json={
            "font_id": "letters", "text": "~~AB~~ AB", "seed": 1,
        })
        assert missing_mark.status_code == 422
        assert "手写删除线" in missing_mark.text
        add_handwritten_marks(font_root)
        response = client.post("/api/compositions", json={
            "font_id": "letters", "text": "~~AB~~ AB", "seed": 1,
        })
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["text"] == "~~AB~~ AB"
        draft_url = f"/api/compositions/{result['id']}/draft"
        draft = client.get(draft_url).json()
        assert draft["text"] == "AB AB"
        assert len(draft["strikes"]) == 1
        assert {key: draft["strikes"][0][key] for key in ("line", "column", "end_column")} == {
            "line": 0, "column": 0, "end_column": 2,
        }
        assert draft["strikes"][0]["sample_file"].startswith("glyphs/U+E00")
        assert any(variant["sample_file"] == draft["strikes"][0]["sample_file"]
                   for variant in draft["variants"])
        candidates = client.get(f"/api/compositions/{result['id']}/word-candidates").json()
        assert [item["key"] for item in candidates] == ["0-3"]
        with Image.open(BytesIO(client.get(result["image_url"]).content)) as image:
            before = image.convert("RGBA").copy()
        edits = [{key: item[key] for key in (
            "index", "kind", "character", "line", "column", "sample_file", "x", "y", "scale"
        )} for item in draft["placements"]]
        edits[0]["y"] += 6
        changed = client.put(draft_url, json={"revision": 0, "placements": edits})
        assert changed.status_code == 200, changed.text
        with Image.open(BytesIO(client.get(f"/api/compositions/{result['id']}/image").content)) as image:
            assert image.convert("RGBA").tobytes() != before.tobytes()
        assert changed.json()["strikes"] == draft["strikes"]
        repeated = client.post("/api/compositions", json={
            "font_id": "letters", "text": "~~AB~~ ~~AB~~", "seed": 2,
        })
        assert repeated.status_code == 201, repeated.text
        repeated_draft = client.get(f"/api/compositions/{repeated.json()['id']}/draft").json()
        assert len({item["sample_file"] for item in repeated_draft["strikes"]}) == 2
        arrow = client.post("/api/compositions", json={
            "font_id": "letters", "text": "A→B", "seed": 3,
        })
        assert arrow.status_code == 201, arrow.text
        arrow_draft = client.get(f"/api/compositions/{arrow.json()['id']}/draft").json()
        assert [item["character"] for item in arrow_draft["placements"]] == ["A", "→", "B"]


def test_delete_version_excludes_future_renders_but_keeps_old_draft(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    font_root = data_root / "fonts" / "english" / "letters"
    make_font(font_root)
    manifest_path = font_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_file = manifest["samples"][0]["glyph_file"]
    new_file = "glyphs/U+0041/002.png"
    shutil.copy2(font_root / old_file, font_root / new_file)
    duplicate = {**manifest["samples"][0], "glyph_file": new_file, "occurrence": 2}
    manifest["samples"].append(duplicate)
    manifest["summary"]["sample_count"] += 1
    manifest["summary"]["glyph_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with TestClient(create_app(data_root)) as client:
        prior = client.post("/api/compositions", json={
            "font_id": "letters", "text": "AAA", "seed": 1,
        }).json()
        prior_draft = client.get(f"/api/compositions/{prior['id']}/draft").json()
        disabled = client.patch("/api/imports/letters/sample", json={
            "sample_file": old_file, "accepted": False,
        })
        assert disabled.status_code == 200, disabled.text
        assert any(item["sample_file"] == old_file and item["accepted"] is False
                   for item in client.get(f"/api/compositions/{prior['id']}/draft").json()["variants"])
        response = client.delete("/api/imports/letters/sample", params={"sample_file": old_file})
        assert response.status_code == 200, response.text
        assert response.json()["summary"]["glyph_count"] == 2
        assert old_file not in [sample["sample_file"] for sample in response.json()["samples"]]
        future = client.post("/api/compositions", json={
            "font_id": "letters", "text": "AAA", "seed": 1,
        })
        assert future.status_code == 201, future.text
        future_draft = client.get(f"/api/compositions/{future.json()['id']}/draft").json()
        assert {item["sample_file"] for item in future_draft["placements"]} == {new_file}
        assert any(item["sample_file"] == old_file for item in prior_draft["placements"])
        old_variants = client.get(f"/api/compositions/{prior['id']}/draft").json()["variants"]
        assert next(item for item in old_variants if item["sample_file"] == old_file)["deleted"] is True
        edits = [{key: item[key] for key in (
            "index", "kind", "character", "line", "column", "sample_file", "x", "y", "scale"
        )} for item in prior_draft["placements"]]
        transformed = client.post(f"/api/compositions/{prior['id']}/transform", json={
            "revision": 0, "placements": edits,
            "operations": [{"type": "replace_unavailable"}],
        })
        assert transformed.status_code == 200, transformed.text
        assert {item["sample_file"] for item in transformed.json()["placements"]} == {new_file}
        assert client.get(f"/api/compositions/{prior['id']}/draft").json()["revision"] == 0
        updated = client.put(f"/api/compositions/{prior['id']}/draft", json={
            "revision": 0,
            "placements": [{key: item[key] for key in (
                "index", "kind", "character", "line", "column", "sample_file", "x", "y", "scale"
            )} for item in transformed.json()["placements"]],
        })
        assert updated.status_code == 200, updated.text
        removed_character = client.delete("/api/imports/letters/character", params={"character": "A"})
        assert removed_character.status_code == 200, removed_character.text
        assert removed_character.json()["summary"]["glyph_count"] == 1
        assert all(item["character"] != "A" for item in removed_character.json()["samples"])
        assert client.post("/api/compositions", json={"font_id": "letters", "text": "A"}).status_code == 422
