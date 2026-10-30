"""Preview and save selected edited words as transparent PNGs only."""

from __future__ import annotations

from hashlib import sha1
from io import BytesIO
import json
from pathlib import Path

from handwriting_concat.composition import (
    CompositionError, render_word_sample, word_spans,
)

from api.handler.imports import checked_run_id
from api.handler.libraries import library_root


class WordConflict(ValueError):
    """The editor changed after word candidates were shown."""


def _draft(data_root: Path, render_id: str) -> dict:
    path = data_root / "renders" / "english" / checked_run_id(render_id) / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError("找不到拼接结果")
    return json.loads(path.read_text(encoding="utf-8"))


def _word_folder(font_root: Path, word: str) -> Path:
    base = font_root / "words"
    if base.is_dir():
        for folder in base.iterdir():
            if folder.is_dir() and folder.name.split("~", 1)[0] == word:
                return folder
        if any(folder.name.casefold() == word.casefold() for folder in base.iterdir()):
            suffix = sha1(word.encode("ascii")).hexdigest()[:8]
            return base / f"{word}~{suffix}"
    return base / word


def _candidates(data_root: Path, render_id: str) -> tuple[dict, Path, list[dict]]:
    draft = _draft(data_root, render_id)
    font_root = library_root(data_root, draft["font_id"])
    indexed = {(item["line"], item["column"]): item
               for item in draft["placements"]}
    candidates = []
    for line_index, line in enumerate(draft["text"].split("\n")):
        for start, end, word in word_spans(line):
            letters = [indexed.get((line_index, column))
                       for column in range(start, end)]
            if any(item is None or item.get("kind", "glyph") != "glyph" or
                   item["character"] != character
                   for item, character in zip(letters, word)):
                continue
            key = f"{line_index}-{start}"
            filename = f"{render_id}-{key}-r{draft.get('revision', 0)}.png"
            path = _word_folder(font_root, word) / filename
            candidates.append({
                "key": key, "word": word, "line": line_index,
                "column": start, "saved": path.is_file(),
                "preview_url": f"/api/compositions/{render_id}/word-candidates/{key}/preview",
                "placements": letters,
                "path": path,
            })
    return draft, font_root, candidates


def list_word_candidates(data_root: Path, render_id: str) -> list[dict]:
    _, _, candidates = _candidates(data_root, render_id)
    return [{key: value for key, value in item.items()
             if key not in {"placements", "path"}} for item in candidates]


def preview_word(data_root: Path, render_id: str, key: str) -> bytes:
    draft, font_root, candidates = _candidates(data_root, render_id)
    candidate = next((item for item in candidates if item["key"] == key), None)
    if candidate is None:
        raise FileNotFoundError("找不到可保存的词")
    image = render_word_sample(font_root, candidate["word"],
                               candidate["placements"], draft["cell_height_px"])
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def save_words(data_root: Path, render_id: str, revision: int,
               keys: list[str]) -> list[dict]:
    draft, font_root, candidates = _candidates(data_root, render_id)
    if revision != draft.get("revision", 0):
        raise WordConflict("编辑内容已更新，请重新打开词选择窗口")
    by_key = {item["key"]: item for item in candidates}
    if len(keys) != len(set(keys)) or any(key not in by_key for key in keys):
        raise CompositionError("所选词不在这次编辑结果中")
    rendered = []
    for key in keys:
        candidate = by_key[key]
        image = render_word_sample(font_root, candidate["word"],
                                   candidate["placements"], draft["cell_height_px"])
        rendered.append((candidate, image))
    results = []
    for candidate, image in rendered:
        path = candidate["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            temporary = path.with_suffix(".png.tmp")
            image.save(temporary, format="PNG")
            temporary.replace(path)
        results.append({"word": candidate["word"], "file": path.relative_to(font_root).as_posix()})
    return results
