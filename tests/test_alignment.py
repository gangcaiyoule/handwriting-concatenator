"""Agent alignment reaches the baseline in one call and preserves other glyphs."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from handwriting_concat.editing import align_baselines_exact
from tests.test_agent_cli import cli
from tests.test_words import make_font


def test_exact_baseline_rule_excludes_descenders_words_and_other_lines() -> None:
    placements = [
        {"kind": "glyph", "character": "A", "line": 0, "x": 0, "y": 20, "width": 10, "height": 20},
        {"kind": "glyph", "character": "b", "line": 0, "x": 15, "y": 45, "width": 10, "height": 20},
        {"kind": "glyph", "character": "c", "line": 0, "x": 30, "y": 25, "width": 10, "height": 20},
        {"kind": "glyph", "character": "g", "line": 0, "x": 45, "y": 50, "width": 10, "height": 20},
        {"kind": "word", "character": "Apple", "line": 0, "x": 60, "y": 50, "width": 50, "height": 30},
        {"kind": "glyph", "character": "A", "line": 1, "x": 0, "y": 80, "width": 10, "height": 20},
    ]
    aligned = align_baselines_exact(placements, line=0)
    assert [item["y"] + item["height"] for item in aligned[:3]] == [45, 45, 45]
    assert aligned[3]["y"] == 50
    assert aligned[4]["y"] == 50
    assert aligned[5]["y"] == 80
    assert placements[1]["y"] == 45
    assert align_baselines_exact(aligned, line=0) == aligned


def test_cli_and_http_alignment_save_revision(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    make_font(data_root / "fonts" / "english" / "en-潦草")
    rendered = cli(data_root, "compose", "--font", "en-潦草", "--text-file", "-",
                   input_text="AB\nAB")
    render_id = rendered["id"]
    draft_url = f"/api/compositions/{render_id}/draft"
    with TestClient(create_app(data_root)) as client:
        draft = client.get(draft_url).json()
        original_second_line = [item["y"] for item in draft["placements"] if item["line"] == 1]
        edits = [{key: item[key] for key in
                  ("index", "kind", "character", "line", "column", "sample_file", "x", "y", "scale")}
                 for item in draft["placements"]]
        edits[1]["y"] += 30
        changed = client.put(draft_url, json={"revision": 0, "placements": edits})
        assert changed.status_code == 200, changed.text

    aligned = cli(data_root, "align-baselines", render_id, "--revision", "1", "--line", "0")
    assert aligned["revision"] == 2
    assert aligned["moved_count"] > 0
    assert Path(aligned["image"]).is_file()
    with TestClient(create_app(data_root)) as client:
        current = client.get(draft_url).json()
        first_line = [item for item in current["placements"] if item["line"] == 0]
        assert first_line[0]["y"] + first_line[0]["height"] == first_line[1]["y"] + first_line[1]["height"]
        assert [item["y"] for item in current["placements"] if item["line"] == 1] == original_second_line
        repeated = client.post(f"/api/compositions/{render_id}/align-baselines", json={
            "revision": 2, "line": 0,
        })
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["revision"] == 2
        stale = client.post(f"/api/compositions/{render_id}/align-baselines", json={
            "revision": 1,
        })
        assert stale.status_code == 409
        invalid_line = client.post(f"/api/compositions/{render_id}/align-baselines", json={
            "revision": 2, "line": 3,
        })
        assert invalid_line.status_code == 422
