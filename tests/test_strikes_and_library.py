"""Deleted glyphs stay out of new renders; strike spans survive edits."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app
from handwriting_concat.composition import CompositionError, parse_strikethrough
from tests.test_words import make_font


def test_strike_syntax_and_saved_render(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    make_font(data_root / "fonts" / "english" / "letters")
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
        response = client.post("/api/compositions", json={
            "font_id": "letters", "text": "~~AB~~ AB", "seed": 1,
        })
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["text"] == "~~AB~~ AB"
        draft_url = f"/api/compositions/{result['id']}/draft"
        draft = client.get(draft_url).json()
        assert draft["text"] == "AB AB"
        assert draft["strikes"] == [{"line": 0, "column": 0, "end_column": 2}]
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
