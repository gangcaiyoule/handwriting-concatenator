"""Local JSON CLI for agents; no HTTP server or browser is required."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import shutil
import sys

from pydantic import ValidationError

from handwriting_concat.composition import CompositionError, MissingGlyphs

from api.handler.compositions import (
    EditConflict, align_draft_baselines, composition_image, create_composition, load_draft, save_draft,
    transform_draft,
)
from api.handler.imports import ImportErrorMessage
from api.handler.libraries import LibraryError, list_libraries, library_root
from api.handler.words import WordConflict, list_word_candidates, preview_word, save_words
from api.main import PROJECT_ROOT
from api.model.compositions import (
    AlignBaselinesRequest, CompositionRequest, DraftTransformRequest, DraftUpdate, PlacementEdit,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地手写字拼接与编辑命令")
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data",
                        help="数据目录，默认项目内 data")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fonts", help="列出可用字体库")
    compose = commands.add_parser("compose", help="从 UTF-8 文字生成拼接图")
    compose.add_argument("--font", required=True)
    compose.add_argument("--text-file", required=True, help="UTF-8 文件；- 表示标准输入")
    compose.add_argument("--cell-height", type=int, default=72)
    compose.add_argument("--spacing-jitter", type=float, default=0.05)
    compose.add_argument("--line-height", type=float, default=1.55)
    compose.add_argument("--background", choices=["white", "transparent"], default="white")
    compose.add_argument("--seed", type=int)
    inspect = commands.add_parser("inspect", help="读取编辑草稿和图片位置")
    inspect.add_argument("id")
    preview = inspect.add_mutually_exclusive_group()
    preview.add_argument("--line", type=int, help="只查看一行，行号从 0 开始")
    preview.add_argument("--region", nargs=4, type=int,
                         metavar=("X", "Y", "WIDTH", "HEIGHT"),
                         help="裁出指定像素区域作为预览")
    apply = commands.add_parser("apply", help="批量调整并保存草稿")
    apply.add_argument("id")
    apply.add_argument("--revision", type=int, required=True)
    apply.add_argument("--ops", type=Path, required=True, help="UTF-8 JSON 操作数组")
    align = commands.add_parser("align-baselines", help="一次对齐各行的普通英文字母基线")
    align.add_argument("id")
    align.add_argument("--revision", type=int, required=True)
    align.add_argument("--line", type=int, help="只对齐指定行，行号从 0 开始")
    candidates = commands.add_parser("word-candidates", help="列出并生成词候选预览")
    candidates.add_argument("id")
    save = commands.add_parser("save-words", help="保存明确选中的词")
    save.add_argument("id")
    save.add_argument("--revision", type=int, required=True)
    save.add_argument("--keys", nargs="+", required=True)
    export = commands.add_parser("export", help="获取或复制最终 PNG")
    export.add_argument("id")
    export.add_argument("--output", type=Path, help="复制到指定 PNG 路径")
    return parser


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8-sig")


def _edit_payload(placements: list[dict]) -> list[PlacementEdit]:
    return [PlacementEdit.model_validate({
        key: item[key] for key in
        ("index", "kind", "character", "line", "column", "sample_file", "x", "y", "scale")
    }) for item in placements]


def _line_summary(draft, line: int) -> dict:
    items = [item for item in draft.placements if item["line"] == line]
    previous = None
    detailed = []
    for item in items:
        detailed.append({
            "column": item["column"], "character": item["character"],
            "kind": item.get("kind", "glyph"), "sample_file": item["sample_file"],
            "x": item["x"], "y": item["y"], "width": item["width"],
            "height": item["height"], "scale": item["scale"],
            "gap_before_px": (None if previous is None else
                              item["x"] - previous["x"] - previous["width"]),
        })
        previous = item
    return {"line": line, "text": draft.text.split("\n")[line], "placements": detailed}


def _preview(data_root: Path, render_id: str, *, line: int | None,
             region: list[int] | None) -> Path:
    from PIL import Image

    image_path = composition_image(data_root, render_id)
    draft = load_draft(data_root, render_id)
    with Image.open(image_path) as image:
        if line is not None:
            if line < 0 or line >= draft.line_count:
                raise CompositionError("行号超出原文范围")
            items = [item for item in draft.placements if item["line"] == line]
            if not items:
                raise CompositionError("这行没有可预览的字形")
            box = (max(0, min(item["x"] for item in items) - 16),
                   max(0, min(item["y"] for item in items) - 16),
                   min(image.width, max(item["x"] + item["width"] for item in items) + 16),
                   min(image.height, max(item["y"] + item["height"] for item in items) + 16))
            name = f"line-{line}-r{draft.revision}.png"
        else:
            assert region is not None
            x, y, width, height = region
            if width <= 0 or height <= 0 or x < 0 or y < 0 or x >= image.width or y >= image.height:
                raise CompositionError("预览区域必须在图片内，宽高须大于零")
            box = (x, y, min(image.width, x + width), min(image.height, y + height))
            name = f"region-{x}-{y}-{width}-{height}-r{draft.revision}.png"
        output = image_path.parent / "previews" / name
        output.parent.mkdir(exist_ok=True)
        image.crop(box).save(output)
    return output.resolve()


async def _execute(args: argparse.Namespace) -> dict:
    data_root = args.data_root.resolve()
    if args.command == "fonts":
        return {"fonts": list_libraries(data_root)}
    if args.command == "compose":
        request = CompositionRequest(
            font_id=args.font, text=_read_text(args.text_file),
            cell_height_px=args.cell_height, spacing_jitter=args.spacing_jitter,
            line_height=args.line_height, background=args.background, seed=args.seed,
        )
        result = await create_composition(data_root, request)
        image = composition_image(data_root, result.id).resolve()
        return {"id": result.id, "font": result.font_id, "revision": 0,
                "image": str(image), "width": result.width, "height": result.height,
                "line_count": result.line_count, "seed": result.seed}
    if args.command == "inspect":
        draft = load_draft(data_root, args.id)
        font_root = library_root(data_root, draft.font_id)
        if args.line is not None and not 0 <= args.line < draft.line_count:
            raise CompositionError("行号超出原文范围")
        lines = (range(draft.line_count) if args.line is None else [args.line])
        result = {
            "id": draft.id, "font": draft.font_id, "revision": draft.revision,
            "image": str(composition_image(data_root, draft.id).resolve()),
            "width": draft.width, "height": draft.height, "text": draft.text,
            "lines": [_line_summary(draft, line) for line in lines],
            "variants": [
                {**variant,
                 "image_path": str((font_root / variant["sample_file"]).resolve())}
                for variant in draft.variants
            ],
        }
        if args.line is not None or args.region is not None:
            result["preview"] = str(_preview(data_root, args.id,
                                              line=args.line, region=args.region))
        return result
    if args.command == "apply":
        operations = json.loads(args.ops.read_text(encoding="utf-8-sig"))
        if not isinstance(operations, list):
            raise CompositionError("操作文件必须是 JSON 数组")
        draft = load_draft(data_root, args.id)
        request = DraftTransformRequest(
            revision=args.revision, placements=_edit_payload(draft.placements),
            operations=operations,
        )
        transformed = await transform_draft(data_root, args.id, request)
        saved = await save_draft(data_root, args.id, DraftUpdate(
            revision=transformed.revision,
            placements=_edit_payload(transformed.placements),
        ))
        return {"id": args.id, "revision": saved.revision,
                "image": str(composition_image(data_root, args.id).resolve()),
                "width": saved.width, "height": saved.height,
                "operation_count": len(operations)}
    if args.command == "align-baselines":
        before = load_draft(data_root, args.id)
        saved = await align_draft_baselines(data_root, args.id, AlignBaselinesRequest(
            revision=args.revision, line=args.line,
        ))
        moved = sum(old["y"] != new["y"] for old, new in
                    zip(before.placements, saved.placements))
        return {"id": args.id, "revision": saved.revision,
                "image": str(composition_image(data_root, args.id).resolve()),
                "width": saved.width, "height": saved.height,
                "moved_count": moved}
    if args.command == "word-candidates":
        draft = load_draft(data_root, args.id)
        candidates = list_word_candidates(data_root, args.id)
        root = composition_image(data_root, args.id).parent / "previews" / "words"
        root.mkdir(parents=True, exist_ok=True)
        for item in candidates:
            path = root / f"{item['key']}-r{draft.revision}.png"
            path.write_bytes(preview_word(data_root, args.id, item["key"]))
            item["preview"] = str(path.resolve())
        return {"id": args.id, "revision": draft.revision, "candidates": candidates}
    if args.command == "save-words":
        saved = save_words(data_root, args.id, args.revision, args.keys)
        draft = load_draft(data_root, args.id)
        font_root = library_root(data_root, draft.font_id)
        return {"id": args.id, "revision": draft.revision,
                "saved": [{**item, "path": str((font_root / item["file"]).resolve())}
                          for item in saved]}
    if args.command == "export":
        source = composition_image(data_root, args.id).resolve()
        draft = load_draft(data_root, args.id)
        if args.output is None:
            return {"id": args.id, "revision": draft.revision, "image": str(source)}
        target = args.output.resolve()
        if target.suffix.lower() != ".png":
            raise CompositionError("导出路径须以 .png 结尾")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target != source:
            shutil.copy2(source, target)
        return {"id": args.id, "revision": draft.revision, "image": str(target)}
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_execute(args))
    except (CompositionError, ImportErrorMessage, LibraryError, EditConflict,
            WordConflict, FileNotFoundError, OSError, UnicodeError,
            json.JSONDecodeError, ValidationError) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        if isinstance(exc, MissingGlyphs):
            error["missing"] = exc.missing
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
