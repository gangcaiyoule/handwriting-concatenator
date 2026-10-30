"""Edited letter groups become reusable PNG words and can be split again."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from api.main import create_app


def make_font(root: Path) -> None:
    root.mkdir(parents=True)
    samples = []
    for character in "AB":
        relative = f"glyphs/U+{ord(character):04X}/001.png"
        path = root / relative
        path.parent.mkdir(parents=True)
        image = Image.new("RGBA", (12, 22))
        ImageDraw.Draw(image).rectangle((2, 2, 9, 19), fill="black")
        image.save(path)
        samples.append({
            "character": character, "codepoint": f"U+{ord(character):04X}",
            "occurrence": 1, "glyph_file": relative,
            "original_crop": f"cells/{character}.png",
            "crop_size_px": [22, 30], "ink_bbox_in_crop_px": [4, 5, 12, 23],
            "accepted": None, "flags": [], "row": 0, "column": 0,
        })
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 2, "font_name": root.name,
        "uploads": [], "samples": samples,
        "summary": {"sample_count": 2, "glyph_count": 2, "review_count": 0},
    }), encoding="utf-8")


def test_save_reuse_and_split_word(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    font_root = data_root / "fonts" / "english" / "en-潦草"
    make_font(font_root)
    with TestClient(create_app(data_root)) as client:
        first = client.post("/api/compositions", json={
            "font_id": "en-潦草", "text": "AB AB", "seed": 2,
        })
        assert first.status_code == 201, first.text
        render_id = first.json()["id"]
        draft_url = f"/api/compositions/{render_id}/draft"
        draft = client.get(draft_url).json()
        assert len(draft["placements"]) == 4

        edits = [{key: item[key] for key in ("index", "sample_file", "x", "y", "scale")}
                 for item in draft["placements"]]
        edits[1]["y"] += 5
        saved_draft = client.put(draft_url, json={"revision": 0, "placements": edits})
        assert saved_draft.status_code == 200, saved_draft.text

        candidates_url = f"/api/compositions/{render_id}/word-candidates"
        candidates = client.get(candidates_url).json()
        assert [(item["key"], item["word"]) for item in candidates] == [
            ("0-0", "AB"), ("0-3", "AB")
        ]
        preview = client.get(candidates[0]["preview_url"])
        assert preview.status_code == 200
        with Image.open(BytesIO(preview.content)) as word_image:
            assert word_image.mode == "RGBA"
            assert word_image.height == 112
            assert word_image.getchannel("A").getbbox() is not None

        stored = client.post(f"/api/compositions/{render_id}/words", json={
            "revision": 1, "keys": ["0-0"],
        })
        assert stored.status_code == 200, stored.text
        assert len(stored.json()) == 1
        assert [item["saved"] for item in client.get(candidates_url).json()] == [True, False]
        second_stored = client.post(f"/api/compositions/{render_id}/words", json={
            "revision": 1, "keys": ["0-3"],
        })
        assert second_stored.status_code == 200, second_stored.text
        stored_files = stored.json() + second_stored.json()
        assert all(item["word"] == "AB" for item in stored_files)
        assert all((font_root / item["file"]).is_file() for item in stored_files)
        assert (font_root / "words" / "AB").is_dir()
        assert {path.suffix for path in (font_root / "words" / "AB").iterdir()} == {".png"}
        assert all(item["saved"] for item in client.get(candidates_url).json())
        assert client.get("/api/imports/en-潦草").json()["word_counts"] == {"AB": 2}

        reused = client.post("/api/compositions", json={
            "font_id": "en-潦草", "text": "AB AB", "seed": 3,
        })
        assert reused.status_code == 201, reused.text
        word_draft_url = f"/api/compositions/{reused.json()['id']}/draft"
        word_draft = client.get(word_draft_url).json()
        assert len(word_draft["placements"]) == 2
        assert all(item["kind"] == "word" for item in word_draft["placements"])
        assert len({item["sample_file"] for item in word_draft["placements"]}) == 2

        first_word = word_draft["placements"][0]
        glyph_variants = {item["character"]: item for item in word_draft["variants"]
                          if item["kind"] == "glyph"}
        replacement = []
        for offset, character in enumerate("AB"):
            variant = glyph_variants[character]
            replacement.append({
                "index": offset, "kind": "glyph", "character": character,
                "line": 0, "column": offset, "sample_file": variant["sample_file"],
                "x": first_word["x"] + offset * 25, "y": first_word["y"] + 20,
                "scale": 1,
            })
        second_word = word_draft["placements"][1]
        replacement.append({
            "index": 2, "kind": "word", "character": "AB",
            "line": 0, "column": 3, "sample_file": second_word["sample_file"],
            "x": second_word["x"], "y": second_word["y"], "scale": 1,
        })
        split = client.put(word_draft_url, json={"revision": 0, "placements": replacement})
        assert split.status_code == 200, split.text
        assert [item["kind"] for item in split.json()["placements"]] == [
            "glyph", "glyph", "word"
        ]
        fresh_candidates = client.get(
            f"/api/compositions/{reused.json()['id']}/word-candidates"
        ).json()
        assert [(item["key"], item["word"]) for item in fresh_candidates] == [("0-0", "AB")]

        manifest_path = font_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for sample in manifest["samples"]:
            sample["accepted"] = False
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        word_only = client.post("/api/compositions", json={
            "font_id": "en-潦草", "text": "AB", "seed": 4,
        })
        assert word_only.status_code == 201, word_only.text
        only_draft = client.get(
            f"/api/compositions/{word_only.json()['id']}/draft"
        ).json()
        assert len(only_draft["placements"]) == 1
        assert only_draft["placements"][0]["kind"] == "word"
