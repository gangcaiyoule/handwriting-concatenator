"""Store rendered handwriting separately from the source font library."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from handwriting_concat.composition import CompositionOptions, compose_text

from api.handler.imports import checked_run_id
from api.model.compositions import CompositionRequest, CompositionResponse


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
    return CompositionResponse(
        id=render_id,
        font_id=data["font_id"],
        text=data["text"],
        seed=data["seed"],
        width=data["width"],
        height=data["height"],
        line_count=data["line_count"],
        background=data["background"],
        image_url=f"/api/compositions/{render_id}/image",
        download_url=f"/api/compositions/{render_id}/download",
    )


async def create_composition(data_root: Path,
                             request: CompositionRequest) -> CompositionResponse:
    checked_run_id(request.font_id)
    font_dir = data_root / "fonts" / "english" / request.font_id
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
        "font_id": request.font_id,
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
