"""Import files into data/file and extracted glyph sets into data/fonts/english."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import quote
from uuid import uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from handwriting_concat import extract_page

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


def load_result(data_root: Path, run_id: str) -> ImportResponse:
    checked_run_id(run_id)
    run_root = data_root / "fonts" / "english" / run_id
    manifest_path = run_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到导入结果：{run_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = next((path for path in (data_root / "file").glob(f"{run_id}.*")
                     if path.is_file()), None)
    if original is None:
        raise FileNotFoundError(f"找不到上传原图：{run_id}")
    base_url = f"/api/imports/{run_id}"
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
        )
        for sample in manifest["samples"]
    ]
    return ImportResponse(
        id=run_id,
        original_url=f"{base_url}/original",
        registered_url=f"{base_url}/images/registered_page.png",
        summary=ImportSummary(**manifest["summary"]),
        samples=samples,
    )


def set_sample_acceptance(data_root: Path, run_id: str,
                          sample_file: str, accepted: bool) -> ImportResponse:
    checked_run_id(run_id)
    path = data_root / "fonts" / "english" / run_id / "manifest.json"
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
    return load_result(data_root, run_id)


async def save_and_extract(upload: UploadFile, data_root: Path) -> ImportResponse:
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

    output = data_root / "fonts" / "english" / run_id
    try:
        await run_in_threadpool(extract_page, source, output)
    except (ValueError, OSError) as exc:
        # Keep the original upload for troubleshooting. A partial output has
        # no manifest and will never be exposed as a completed import.
        raise ImportErrorMessage(
            f"图片已保存为 data/file/{run_id}{suffix}，但自动提取失败：{exc}"
        ) from exc
    return load_result(data_root, run_id)


def resolve_result_image(data_root: Path, run_id: str, image_path: str) -> Path:
    checked_run_id(run_id)
    if "\\" in image_path or image_path.startswith("/"):
        raise ImportErrorMessage("无效的图片路径")
    parts = Path(image_path).parts
    if ".." in parts or not parts or parts[0] not in {
        "cells", "glyphs", "registered_page.png"
    }:
        raise ImportErrorMessage("无效的图片路径")
    run_root = (data_root / "fonts" / "english" / run_id).resolve()
    image = (run_root / image_path).resolve()
    if image != run_root and run_root not in image.parents:
        raise ImportErrorMessage("无效的图片路径")
    if not image.is_file():
        raise FileNotFoundError("找不到图片")
    return image


def resolve_original(data_root: Path, run_id: str) -> Path:
    checked_run_id(run_id)
    original = next((path for path in (data_root / "file").glob(f"{run_id}.*")
                     if path.is_file()), None)
    if original is None:
        raise FileNotFoundError("找不到上传原图")
    return original
