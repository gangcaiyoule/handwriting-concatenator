"""Store rendered handwriting separately from the source font library."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from PIL import Image
from starlette.concurrency import run_in_threadpool

from handwriting_concat.composition import (
    CompositionError, CompositionOptions, compose_text, load_library,
    render_edited,
)

from api.handler.imports import checked_run_id
from api.handler.libraries import library_root
from api.model.compositions import (
    CompositionRequest, CompositionResponse, DraftResponse, DraftUpdate,
)


class EditConflict(ValueError):
    """A stale editor attempted to overwrite a newer saved revision."""


def _render_root(data_root: Path, render_id: str) -> Path:
    checked_run_id(render_id)
    return data_root / "renders" / "english" / render_id


def load_composition(data_root: Path, render_id: str) -> CompositionResponse:
    root = _render_root(data_root, render_id)
    manifest = root / "manifest.json"
    image = root / "composition.png"
    if not manifest.is_file() or not image.is_file():
        raise FileNotFoundError("找不到拼接结果")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    revision = data.get("revision", 0)
    return CompositionResponse(
        id=render_id,
        font_id=data["font_id"],
        text=data["text"],
        seed=data["seed"],
        width=data["width"],
        height=data["height"],
        line_count=data["line_count"],
        background=data["background"],
        image_url=f"/api/compositions/{render_id}/image?revision={revision}",
        download_url=f"/api/compositions/{render_id}/download?revision={revision}",
    )


def _manifest(data_root: Path, render_id: str) -> tuple[Path, dict]:
    path = _render_root(data_root, render_id) / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError("找不到拼接结果")
    return path, json.loads(path.read_text(encoding="utf-8"))


def load_draft(data_root: Path, render_id: str) -> DraftResponse:
    _, data = _manifest(data_root, render_id)
    font_root = library_root(data_root, data["font_id"])
    font_id = font_root.name
    library = load_library(font_root, include_disabled=True)
    used_characters = {item["character"] for item in data["placements"]}
    variants: list[dict] = []
    for character, samples in library.items():
        if character not in used_characters:
            continue
        for sample in samples:
            relative = sample["glyph_file"]
            with Image.open(font_root / relative) as image:
                image_width, image_height = image.size
            ratio = data["cell_height_px"] / sample["crop_size_px"][1]
            variants.append({
                "character": character,
                "sample_file": relative,
                "image_url": f"/api/imports/{quote(font_id, safe='')}/images/{quote(relative, safe='/')}",
                "width": max(1, round(image_width * ratio)),
                "height": max(1, round(image_height * ratio)),
                "occurrence": sample.get("occurrence"),
                "accepted": sample.get("accepted") is not False,
                "flags": sample.get("flags", []),
            })
    placements = [
        {**item, "index": index, "scale": item.get("scale", 1.0)}
        for index, item in enumerate(data["placements"])
    ]
    return DraftResponse(
        id=render_id, font_id=font_id, text=data["text"],
        revision=data.get("revision", 0), width=data["width"],
        height=data["height"], line_count=data["line_count"],
        background=data["background"],
        cell_height_px=data["cell_height_px"],
        placements=placements, variants=variants,
    )


async def save_draft(data_root: Path, render_id: str,
                     request: DraftUpdate) -> DraftResponse:
    path, data = _manifest(data_root, render_id)
    if request.revision != data.get("revision", 0):
        raise EditConflict("此拼接图已在别处更新，请刷新后再编辑")
    original = data["placements"]
    if len(request.placements) != len(original):
        raise CompositionError("编辑数据与原文字符数不一致")
    placements = []
    for index, (edit, previous) in enumerate(zip(request.placements, original)):
        if edit.index != index:
            raise CompositionError("编辑数据的字符顺序不正确")
        placements.append({
            **previous,
            "index": index,
            "sample_file": edit.sample_file,
            "x": edit.x,
            "y": edit.y,
            "scale": edit.scale,
        })
    font_root = library_root(data_root, data["font_id"])
    image = await run_in_threadpool(
        render_edited, font_root, placements, data["cell_height_px"],
        data["background"], (data["width"], data["height"]),
    )
    root = path.parent
    image_tmp = root / "composition.png.tmp"
    manifest_tmp = root / "manifest.json.tmp"
    image.save(image_tmp, format="PNG")
    data.update(
        placements=placements, width=image.width, height=image.height,
        revision=data.get("revision", 0) + 1,
    )
    manifest_tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    image_tmp.replace(root / "composition.png")
    manifest_tmp.replace(path)
    return load_draft(data_root, render_id)


async def create_composition(data_root: Path,
                             request: CompositionRequest) -> CompositionResponse:
    font_dir = library_root(data_root, request.font_id)
    if not (font_dir / "manifest.json").is_file():
        raise FileNotFoundError("找不到所选字形库")

    options = CompositionOptions(
        cell_height_px=request.cell_height_px,
        spacing_jitter=request.spacing_jitter,
        line_height=request.line_height,
        background=request.background,
        seed=request.seed,
    )
    rendered = await run_in_threadpool(compose_text, request.text, font_dir, options)
    render_id = uuid4().hex
    root = _render_root(data_root, render_id)
    root.mkdir(parents=True, exist_ok=False)
    rendered.image.save(root / "composition.png", format="PNG")
    manifest = {
        "schema_version": 1,
        "font_id": font_dir.name,
        "text": rendered.text,
        "seed": rendered.seed,
        "cell_height_px": options.cell_height_px,
        "spacing_jitter": options.spacing_jitter,
        "line_height": options.line_height,
        "background": options.background,
        "width": rendered.image.width,
        "height": rendered.image.height,
        "line_count": rendered.line_count,
        "placements": rendered.placements,
    }
    temporary = root / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(root / "manifest.json")
    return load_composition(data_root, render_id)


def composition_image(data_root: Path, render_id: str) -> Path:
    root = _render_root(data_root, render_id)
    image = root / "composition.png"
    if not image.is_file():
        raise FileNotFoundError("找不到拼接图片")
    return image
