"""Import files into data/file and extracted glyph sets into data/fonts/english."""

from __future__ import annotations

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import quote
from uuid import uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from handwriting_concat import extract_page

from api.handler.libraries import (
    checked_new_font_name, legacy_imports, library_root,
    merge_extraction,
)
from api.model.imports import ImportResponse, ImportSummary, SampleResponse


ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".pdf"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")


class ImportErrorMessage(ValueError):
    """A user-facing import failure."""


def checked_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ImportErrorMessage("无效的导入编号")
    return run_id


def load_result(data_root: Path, font_name: str) -> ImportResponse:
    run_root = library_root(data_root, font_name)
    name = run_root.name
    manifest_path = run_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到字形库：{name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    uploads = manifest.get("uploads", [])
    if manifest.get("schema_version") == 2:
        latest = uploads[-1] if uploads else None
        registered = latest["registered_page"] if latest else None
        upload_count = len(uploads)
        latest_upload_id = latest["id"] if latest else None
    else:
        registered = manifest.get("registered_page", "registered_page.png")
        upload_count = 1
        latest_upload_id = name
    base_url = f"/api/imports/{quote(name, safe='')}"
    samples = [
        SampleResponse(
            character=sample["character"],
            codepoint=sample["codepoint"],
            occurrence=sample["occurrence"],
            row=sample["row"],
            column=sample["column"],
            flags=sample["flags"],
            accepted=sample["accepted"],
            original_crop_url=f"{base_url}/images/{quote(sample['original_crop'], safe='/')}",
            glyph_url=(f"{base_url}/images/{quote(sample['glyph_file'], safe='/')}"
                       if sample["glyph_file"] else None),
            upload_id=sample.get("upload_id", latest_upload_id),
        )
        for sample in manifest["samples"]
    ]
    return ImportResponse(
        id=name,
        original_url=f"{base_url}/original" if latest_upload_id else None,
        registered_url=(f"{base_url}/images/{quote(registered, safe='/')}"
                        if registered else None),
        summary=ImportSummary(**manifest["summary"]),
        samples=samples,
        upload_count=upload_count,
        latest_upload_id=latest_upload_id,
        legacy_imports=(legacy_imports(data_root, name)
                        if manifest.get("schema_version") == 2 else []),
    )


def set_sample_acceptance(data_root: Path, font_name: str,
                          sample_file: str, accepted: bool) -> ImportResponse:
    root = library_root(data_root, font_name)
    name = root.name
    path = root / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError("找不到字形库")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    sample = next((item for item in manifest["samples"]
                   if item.get("glyph_file") == sample_file), None)
    if sample is None:
        raise ImportErrorMessage("找不到这个字形版本")
    sample["accepted"] = accepted
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)
    return load_result(data_root, name)


async def save_and_extract(upload: UploadFile, data_root: Path,
                           font_name: str) -> ImportResponse:
    name = checked_new_font_name(font_name)
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ImportErrorMessage("支持 JPG、PNG、TIFF、WEBP、BMP 和单页 PDF")
    run_id = uuid4().hex
    file_root = data_root / "file"
    file_root.mkdir(parents=True, exist_ok=True)
    source = file_root / f"{run_id}{suffix}"
    bytes_written = 0
    try:
        with source.open("xb") as destination:
            while chunk := await upload.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise ImportErrorMessage("文件不能超过 50 MB")
                destination.write(chunk)
        if bytes_written == 0:
            raise ImportErrorMessage("上传的文件为空")
    except Exception:
        source.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    try:
        with TemporaryDirectory(prefix="handwriting-import-", dir=data_root) as temporary:
            output = Path(temporary) / "extracted"
            await run_in_threadpool(extract_page, source, output)
            await run_in_threadpool(
                merge_extraction, data_root, name, run_id, output, source.name
            )
    except (ValueError, OSError) as exc:
        # Keep the original upload for troubleshooting. A partial output has
        # no manifest and will never be exposed as a completed import.
        raise ImportErrorMessage(
            f"图片已保存为 data/file/{run_id}{suffix}，但自动提取失败：{exc}"
        ) from exc
    return load_result(data_root, name)


def resolve_result_image(data_root: Path, font_name: str, image_path: str) -> Path:
    run_root = library_root(data_root, font_name).resolve()
    if "\\" in image_path or image_path.startswith("/"):
        raise ImportErrorMessage("无效的图片路径")
    parts = Path(image_path).parts
    if ".." in parts or not parts or parts[0] not in {
        "cells", "glyphs", "pages", "registered_page.png"
    }:
        raise ImportErrorMessage("无效的图片路径")
    image = (run_root / image_path).resolve()
    if image != run_root and run_root not in image.parents:
        raise ImportErrorMessage("无效的图片路径")
    if not image.is_file():
        raise FileNotFoundError("找不到图片")
    return image


def resolve_original(data_root: Path, font_name: str) -> Path:
    root = library_root(data_root, font_name)
    name = root.name
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("找不到字形库")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") == 2:
        uploads = manifest["uploads"]
        original = ((data_root / "file" / uploads[-1]["source_file"])
                    if uploads else None)
    else:
        original = next((path for path in (data_root / "file").glob(f"{name}.*")
                         if path.is_file()), None)
    if original is None:
        raise FileNotFoundError("找不到上传原图")
    if not original.is_file():
        raise FileNotFoundError("找不到上传原图")
    return original
