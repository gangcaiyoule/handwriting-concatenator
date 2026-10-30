"""The local agent path can edit a saved word and reuse a newly saved one."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_words import make_font


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def cli(data_root: Path, *args: str, input_text: str | None = None) -> dict:
    process = subprocess.run(
        [sys.executable, "-m", "api.agent_cli", "--data-root", str(data_root), *args],
        cwd=PROJECT_ROOT, input=input_text, text=True, capture_output=True,
        encoding="utf-8", check=False,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def test_agent_cli_round_trip_and_transform_endpoint(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    font_root = data_root / "fonts" / "english" / "en-潦草"
    make_font(font_root)
    assert cli(data_root, "fonts")["fonts"][0]["name"] == "en-潦草"

    first = cli(data_root, "compose", "--font", "en-潦草", "--text-file", "-",
                input_text="AB\nAB")
    assert Path(first["image"]).is_file()
    detail = cli(data_root, "inspect", first["id"], "--line", "0")
    assert detail["lines"][0]["text"] == "AB"
    assert Path(detail["preview"]).is_file()
    assert detail["lines"][0]["placements"][1]["column"] == 1
    assert all(Path(variant["image_path"]).is_file() for variant in detail["variants"])

    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps([
        {"type": "set_gap", "line": 0, "column": 1, "gap_px": 9},
        {"type": "move_line", "line": 1, "dx": 5, "dy": 4},
    ]), encoding="utf-8")
    changed = cli(data_root, "apply", first["id"], "--revision", "0", "--ops", str(ops))
    assert changed["revision"] == 1
    detail = cli(data_root, "inspect", first["id"], "--line", "0")
    assert detail["lines"][0]["placements"][1]["gap_before_px"] == 9
    candidates = cli(data_root, "word-candidates", first["id"])
    assert [item["key"] for item in candidates["candidates"]] == ["0-0", "1-0"]
    assert all(Path(item["preview"]).is_file() for item in candidates["candidates"])
    saved = cli(data_root, "save-words", first["id"], "--revision", "1", "--keys", "0-0")
    assert len(saved["saved"]) == 1
    assert Path(saved["saved"][0]["path"]).is_file()

    second = cli(data_root, "compose", "--font", "en-潦草", "--text-file", "-",
                 input_text="AB")
    second_detail = cli(data_root, "inspect", second["id"])
    assert second_detail["lines"][0]["placements"][0]["kind"] == "word"
    with TestClient(create_app(data_root)) as client:
        draft = client.get(f"/api/compositions/{second['id']}/draft").json()
        response = client.post(f"/api/compositions/{second['id']}/transform", json={
            "revision": 0,
            "placements": [{key: item[key] for key in
                            ("index", "kind", "character", "line", "column",
                             "sample_file", "x", "y", "scale")}
                           for item in draft["placements"]],
            "operations": [{"type": "split_word", "line": 0, "column": 0}],
        })
        assert response.status_code == 200, response.text
        assert [item["kind"] for item in response.json()["placements"]] == ["glyph", "glyph"]
        # Transforming the browser's local draft does not persist it.
        assert client.get(f"/api/compositions/{second['id']}/draft").json()["revision"] == 0

    ops.write_text(json.dumps([
        {"type": "split_word", "line": 0, "column": 0},
        {"type": "move", "line": 0, "column": 1, "dx": 3, "dy": 2},
    ]), encoding="utf-8")
    split = cli(data_root, "apply", second["id"], "--revision", "0", "--ops", str(ops))
    assert split["revision"] == 1
    assert [item["kind"] for item in cli(data_root, "inspect", second["id"])["lines"][0]["placements"]] == ["glyph", "glyph"]
    exported = cli(data_root, "export", second["id"], "--output", str(tmp_path / "final.png"))
    assert Path(exported["image"]).is_file()
