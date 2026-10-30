"""Keep one cumulative handwriting library per named font."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import shutil
from threading import Lock


FONT_NAME_PATTERN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff][A-Za-z0-9_\- \u4e00-\u9fff]{0,39}\Z")
LEGACY_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}
_merge_lock = Lock()


class LibraryError(ValueError):
    """A font name or library operation is invalid."""


def checked_new_font_name(font_name: str) -> str:
    name = font_name.strip()
    if (not FONT_NAME_PATTERN.fullmatch(name) or LEGACY_ID_PATTERN.fullmatch(name)
            or name.upper() in WINDOWS_RESERVED):
        raise LibraryError("字体库名称须为 1–40 个中文、英文字母、数字、空格、下划线或连字符")
    return name


def checked_font_name(name: str) -> str:
    if LEGACY_ID_PATTERN.fullmatch(name):
        return name
    return checked_new_font_name(name)


def library_root(data_root: Path, font_name: str) -> Path:
    name = checked_font_name(font_name)
    base = data_root / "fonts" / "english"
    if base.is_dir():
        for candidate in base.iterdir():
            if candidate.is_dir() and candidate.name.casefold() == name.casefold():
                return candidate
    return base / name


def _write_manifest(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def ensure_library(data_root: Path, font_name: str) -> Path:
    name = checked_new_font_name(font_name)
    root = library_root(data_root, name)
    path = root / "manifest.json"
    if not path.is_file():
        root.mkdir(parents=True, exist_ok=True)
        _write_manifest(path, {
            "schema_version": 2,
            "font_name": root.name,
            "uploads": [],
            "summary": {"sample_count": 0, "glyph_count": 0, "review_count": 0},
            "samples": [],
        })
    else:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 2:
            raise LibraryError("同名目录不是字体库，请换一个名称")
        if manifest.get("font_name") != root.name or "username" in manifest:
            manifest.pop("username", None)
            manifest["font_name"] = root.name
            _write_manifest(path, manifest)
    return root


def list_libraries(data_root: Path) -> list[dict]:
    font_root = data_root / "fonts" / "english"
    if not font_root.is_dir():
        return []
    libraries = []
    for root in font_root.iterdir():
        if not root.is_dir() or LEGACY_ID_PATTERN.fullmatch(root.name):
            continue
        try:
            checked_new_font_name(root.name)
        except LibraryError:
            continue
        path = root / "manifest.json"
        if not path.is_file():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != 2:
                continue
            libraries.append({
                "name": root.name,
                "upload_count": len(manifest.get("uploads", [])),
                "glyph_count": manifest.get("summary", {}).get("glyph_count", 0),
            })
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(libraries, key=lambda item: item["name"].casefold())


def legacy_imports(data_root: Path, font_name: str) -> list[str]:
    library_root(data_root, font_name)
    claimed = set()
    font_root = data_root / "fonts" / "english"
    if not font_root.is_dir():
        return []
    for library in list_libraries(data_root):
        manifest = font_root / library["name"] / "manifest.json"
        claimed.update(item["id"] for item in json.loads(manifest.read_text(encoding="utf-8"))
                       .get("uploads", []))
    found = []
    for candidate in font_root.iterdir():
        if not candidate.is_dir() or not LEGACY_ID_PATTERN.fullmatch(candidate.name):
            continue
        path = candidate / "manifest.json"
        if candidate.name in claimed or not path.is_file():
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("schema_version") == 1:
                found.append(candidate.name)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(found)


def merge_extraction(data_root: Path, font_name: str, upload_id: str,
                     extracted_root: Path, source_file: str) -> None:
    """Copy one extraction into the named library's shared glyph folders."""
    name = checked_new_font_name(font_name)
    if not LEGACY_ID_PATTERN.fullmatch(upload_id):
        raise LibraryError("无效的上传编号")
    with _merge_lock:
        root = ensure_library(data_root, name)
        path = root / "manifest.json"
        library = json.loads(path.read_text(encoding="utf-8"))
        if any(item["id"] == upload_id for item in library["uploads"]):
            return
        extracted = json.loads((extracted_root / "manifest.json").read_text(encoding="utf-8"))
        page_root = root / "pages" / upload_id
        page_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extracted_root / extracted["registered_page"],
                     page_root / "registered_page.png")
        shutil.copytree(extracted_root / "cells", page_root / "cells", dirs_exist_ok=True)

        occurrences = Counter(sample["character"] for sample in library["samples"])
        for original in extracted["samples"]:
            sample = dict(original)
            character = sample["character"]
            occurrences[character] += 1
            sample["occurrence"] = occurrences[character]
            sample["upload_id"] = upload_id
            sample["original_crop"] = f"pages/{upload_id}/{original['original_crop']}"
            if original["glyph_file"]:
                codepoint = sample["codepoint"]
                filename = f"{upload_id}-{Path(original['glyph_file']).name}"
                relative = f"glyphs/{codepoint}/{filename}"
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(extracted_root / original["glyph_file"], target)
                sample["glyph_file"] = relative
            library["samples"].append(sample)
        library["uploads"].append({
            "id": upload_id,
            "source_file": source_file,
            "registered_page": f"pages/{upload_id}/registered_page.png",
        })
        library["summary"] = {
            "sample_count": len(library["samples"]),
            "glyph_count": sum(bool(item["glyph_file"]) for item in library["samples"]),
            "review_count": sum(bool(item["flags"]) for item in library["samples"]),
        }
        _write_manifest(path, library)


def claim_legacy(data_root: Path, font_name: str, upload_id: str) -> None:
    name = checked_new_font_name(font_name)
    if not LEGACY_ID_PATTERN.fullmatch(upload_id):
        raise LibraryError("无效的旧字形库编号")
    source = data_root / "fonts" / "english" / upload_id
    path = source / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError("找不到旧字形库")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise LibraryError("这不是旧版字形库")
    original = next((item for item in (data_root / "file").glob(f"{upload_id}.*")
                     if item.is_file()), None)
    if original is None:
        raise FileNotFoundError("找不到旧字形库的上传原图")
    merge_extraction(data_root, name, upload_id, source, original.name)
