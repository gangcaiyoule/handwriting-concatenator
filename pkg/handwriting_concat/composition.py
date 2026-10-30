"""Arrange extracted glyph images into user-specified lines of text."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
import secrets

from PIL import Image


MAX_TEXT_LENGTH = 2000
MAX_LINES = 40
MAX_CANVAS_EDGE = 12000
CLOSING_PUNCTUATION = set(".,!?;:)]}")
OPENING_PUNCTUATION = set("([{")


class CompositionError(ValueError):
    """The requested text or font set cannot be rendered."""


class MissingGlyphs(CompositionError):
    def __init__(self, missing: list[dict[str, int | str]]) -> None:
        super().__init__("Some characters have no glyph samples")
        self.missing = missing


@dataclass(frozen=True)
class CompositionOptions:
    cell_height_px: int = 72
    spacing_jitter: float = 0.05
    line_height: float = 1.55
    background: str = "white"
    seed: int | None = None

    def __post_init__(self) -> None:
        if not 32 <= self.cell_height_px <= 140:
            raise CompositionError("Character size must be 32–140 pixels")
        if not 0 <= self.spacing_jitter <= 0.2:
            raise CompositionError("Spacing jitter must be 0–0.2")
        if not 1.1 <= self.line_height <= 2.5:
            raise CompositionError("Line height must be 1.1–2.5")
        if self.background not in {"white", "transparent"}:
            raise CompositionError("Background must be white or transparent")
        if self.seed is not None and not 0 <= self.seed < 2**32:
            raise CompositionError("Seed must be a 32-bit unsigned integer")


@dataclass
class Composition:
    image: Image.Image
    seed: int
    text: str
    line_count: int
    placements: list[dict]


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _glyph_path(font_dir: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.startswith("glyphs/"):
        raise CompositionError("Font manifest contains an invalid glyph path")
    path = (font_dir / relative).resolve()
    if font_dir not in path.parents or path.suffix.lower() != ".png":
        raise CompositionError("Font manifest contains an unsafe glyph path")
    return path


def load_library(font_dir: str | Path) -> dict[str, list[dict]]:
    root = Path(font_dir).resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositionError("Font manifest could not be read") from exc
    library: dict[str, list[dict]] = {}
    seen_files: set[Path] = set()
    for sample in manifest.get("samples", []):
        relative = sample.get("glyph_file")
        if not relative or sample.get("accepted") is False:
            continue
        path = _glyph_path(root, relative)
        if path in seen_files or not path.is_file():
            continue
        seen_files.add(path)
        character = sample.get("character")
        if not isinstance(character, str) or len(character) != 1:
            continue
        if not sample.get("crop_size_px") or not sample.get("ink_bbox_in_crop_px"):
            continue
        library.setdefault(character, []).append(sample)
    return library


def missing_for(text: str, library: dict[str, list[dict]]) -> list[dict[str, int | str]]:
    required = Counter(char for char in text if char not in {" ", "\n"})
    return [
        {"character": char, "required": count, "available": len(library.get(char, []))}
        for char, count in required.items()
        if not library.get(char)
    ]


def _load_scaled_glyph(sample: dict, font_dir: Path,
                       cell_height: int) -> tuple[Image.Image, tuple[int, int, int]]:
    glyph_path = _glyph_path(font_dir, sample["glyph_file"])
    with Image.open(glyph_path) as opened:
        original = opened.convert("RGBA")
    crop_height = int(sample["crop_size_px"][1])
    if crop_height < 1:
        raise CompositionError("Font manifest contains an invalid crop size")
    scale = cell_height / crop_height
    width = max(1, round(original.width * scale))
    height = max(1, round(original.height * scale))
    scaled = original.resize((width, height), Image.Resampling.LANCZOS)
    # The source bbox was measured at alpha >= 32. Recover the position of
    # the cropped PNG within its original cell, including detached dots.
    strong_alpha = original.getchannel("A").point(
        lambda value: 255 if value >= 32 else 0
    )
    strong_bbox = strong_alpha.getbbox()
    if strong_bbox is None:
        raise CompositionError("Font image contains no visible ink")
    source_bbox = sample["ink_bbox_in_crop_px"]
    origin_y = int(source_bbox[1]) - strong_bbox[1]
    ink_width = int(source_bbox[2]) - int(source_bbox[0])
    return scaled, (round(origin_y * scale),
                    max(1, round(ink_width * scale)), round(strong_bbox[0] * scale))


def compose_text(text: str, font_dir: str | Path,
                 options: CompositionOptions | None = None) -> Composition:
    settings = options or CompositionOptions()
    normalized = normalize_text(text)
    if not normalized or not normalized.strip():
        raise CompositionError("请输入要拼接的文字")
    if len(normalized) > MAX_TEXT_LENGTH:
        raise CompositionError(f"文字不能超过 {MAX_TEXT_LENGTH} 个字符")
    lines = normalized.split("\n")
    if len(lines) > MAX_LINES:
        raise CompositionError(f"不能超过 {MAX_LINES} 行")

    root = Path(font_dir).resolve()
    library = load_library(root)
    missing = missing_for(normalized, library)
    if missing:
        raise MissingGlyphs(missing)

    seed = settings.seed if settings.seed is not None else secrets.randbits(32)
    rng = random.Random(seed)
    pools = {char: variants.copy() for char, variants in library.items()}
    for variants in pools.values():
        rng.shuffle(variants)
    last_used: dict[str, str] = {}

    def next_sample(character: str) -> dict:
        pool = pools[character]
        if not pool:
            pool.extend(library[character])
            rng.shuffle(pool)
            # A new round starts only after every version has been used.
            # Avoid repeating the same image at the round boundary when possible.
            if len(pool) > 1 and pool[-1]["glyph_file"] == last_used[character]:
                pool[0], pool[-1] = pool[-1], pool[0]
        sample = pool.pop()
        last_used[character] = sample["glyph_file"]
        return sample

    size = settings.cell_height_px
    padding = max(20, round(size * 0.55))
    line_step = size * settings.line_height
    placements: list[dict] = []
    prepared: list[tuple[Image.Image, int, int]] = []
    widest_line = 0.0
    for line_index, line in enumerate(lines):
        cursor = float(padding)
        previous: str | None = None
        for character_index, character in enumerate(line):
            if character == " ":
                cursor += size * 0.55
                previous = " "
                continue

            gap = 0.0
            if previous is not None and previous != " ":
                gap = max(0.0, size * (
                    0.09 + rng.uniform(-settings.spacing_jitter,
                                       settings.spacing_jitter)
                ))
                if character in CLOSING_PUNCTUATION or previous in OPENING_PUNCTUATION:
                    gap *= 0.2
                cursor += gap

            sample = next_sample(character)
            glyph, (origin_y, ink_width, alpha_left) = _load_scaled_glyph(
                sample, root, size
            )
            x = round(cursor - alpha_left)
            y = round(padding + line_index * line_step + origin_y)
            prepared.append((glyph, x, y))
            placements.append({
                "character": character,
                "line": line_index,
                "column": character_index,
                "sample_file": sample["glyph_file"],
                "sample_row": sample.get("row"),
                "sample_column": sample.get("column"),
                "x": x,
                "y": y,
                "width": glyph.width,
                "height": glyph.height,
                "gap_before_px": round(gap, 2),
            })
            cursor += ink_width
            previous = character
        widest_line = max(widest_line, cursor)

    width = max(1, math.ceil(widest_line + padding))
    height = max(1, math.ceil(padding * 2 + size + (len(lines) - 1) * line_step))
    if width > MAX_CANVAS_EDGE or height > MAX_CANVAS_EDGE:
        raise CompositionError("拼接结果过大，请缩短单行或减小字大小")
    background = ((255, 255, 255, 255) if settings.background == "white"
                  else (0, 0, 0, 0))
    canvas = Image.new("RGBA", (width, height), background)
    for glyph, x, y in prepared:
        canvas.alpha_composite(glyph, (x, y))
    return Composition(canvas, seed, normalized, len(lines), placements)
