"""Arrange extracted glyph images into user-specified lines of text."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
import re
import secrets
from statistics import median

from PIL import Image


MAX_TEXT_LENGTH = 2000
MAX_LINES = 40
MAX_CANVAS_EDGE = 12000
CLOSING_PUNCTUATION = set(".,!?;:)]}")
OPENING_PUNCTUATION = set("([{")
WORD_PATTERN = re.compile(r"[A-Za-z]+")
WORD_BASE_SIZE = 72
# Every saved word PNG uses the same line box. Transparent top padding encodes
# the baseline without a separate positions file.
WORD_CANVAS_HEIGHT = 112
WORD_TOP_OFFSET = 18


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


def word_spans(line: str) -> list[tuple[int, int, str]]:
    return [(match.start(), match.end(), match.group())
            for match in WORD_PATTERN.finditer(line)]


def load_word_library(font_dir: str | Path) -> dict[str, list[str]]:
    root = Path(font_dir).resolve() / "words"
    if not root.is_dir():
        return {}
    result: dict[str, list[str]] = {}
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        word = folder.name.split("~", 1)[0]
        if not WORD_PATTERN.fullmatch(word):
            continue
        for image in folder.glob("*.png"):
            if image.is_file():
                result.setdefault(word, []).append(image.relative_to(root.parent).as_posix())
    for files in result.values():
        files.sort()
    return result


def _word_path(font_dir: Path, word: str, relative: str) -> Path:
    if not WORD_PATTERN.fullmatch(word) or not isinstance(relative, str):
        raise CompositionError("无效的词图片")
    parts = Path(relative).parts
    if (len(parts) != 3 or parts[0] != "words" or
            parts[1].split("~", 1)[0] != word or
            not parts[2].lower().endswith(".png")):
        raise CompositionError("词图片与文字不匹配")
    path = (font_dir / relative).resolve()
    if font_dir not in path.parents or not path.is_file():
        raise CompositionError("找不到词图片")
    return path


def _load_scaled_word(font_dir: Path, word: str, relative: str,
                      cell_height: int) -> Image.Image:
    with Image.open(_word_path(font_dir, word, relative)) as opened:
        original = opened.convert("RGBA")
    ratio = cell_height / WORD_BASE_SIZE
    size = (max(1, round(original.width * ratio)),
            max(1, round(original.height * ratio)))
    return original.resize(size, Image.Resampling.LANCZOS)


def load_library(font_dir: str | Path, *, include_disabled: bool = False) -> dict[str, list[dict]]:
    root = Path(font_dir).resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositionError("Font manifest could not be read") from exc
    library: dict[str, list[dict]] = {}
    seen_files: set[Path] = set()
    for sample in manifest.get("samples", []):
        relative = sample.get("glyph_file")
        if not relative or (sample.get("accepted") is False and not include_disabled):
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


def render_edited(font_dir: str | Path, placements: list[dict],
                  cell_height_px: int, background: str,
                  minimum_size: tuple[int, int]) -> Image.Image:
    """Render saved instance positions using samples from the same character."""
    root = Path(font_dir).resolve()
    library = load_library(root, include_disabled=True)
    allowed = {
        sample["glyph_file"]: character
        for character, samples in library.items()
        for sample in samples
    }
    samples = {
        sample["glyph_file"]: sample
        for variants in library.values()
        for sample in variants
    }
    prepared: list[tuple[Image.Image, int, int]] = []
    right = bottom = 0
    for placement in placements:
        relative = placement["sample_file"]
        if placement.get("kind", "glyph") == "word":
            base = _load_scaled_word(root, placement["character"], relative,
                                     cell_height_px)
        else:
            if allowed.get(relative) != placement["character"]:
                raise CompositionError("字形版本与字符不匹配")
            base, _ = _load_scaled_glyph(samples[relative], root, cell_height_px)
        scale = float(placement.get("scale", 1))
        if not 0.5 <= scale <= 1.5:
            raise CompositionError("字形缩放必须在 50% 到 150% 之间")
        size = (max(1, round(base.width * scale)),
                max(1, round(base.height * scale)))
        glyph = base if scale == 1 else base.resize(size, Image.Resampling.LANCZOS)
        x, y = int(placement["x"]), int(placement["y"])
        if x < 0 or y < 0:
            raise CompositionError("字形不能移出画布左侧或上侧")
        placement["width"], placement["height"] = glyph.size
        prepared.append((glyph, x, y))
        right = max(right, x + glyph.width)
        bottom = max(bottom, y + glyph.height)
    width = max(minimum_size[0], right + 20)
    height = max(minimum_size[1], bottom + 20)
    if width > MAX_CANVAS_EDGE or height > MAX_CANVAS_EDGE:
        raise CompositionError("编辑后的画布超过 12000 px，请缩小字距或字形")
    color = (255, 255, 255, 255) if background == "white" else (0, 0, 0, 0)
    image = Image.new("RGBA", (width, height), color)
    for glyph, x, y in prepared:
        image.alpha_composite(glyph, (x, y))
    return image


def missing_for(text: str, library: dict[str, list[dict]],
                words: dict[str, list[str]] | None = None) -> list[dict[str, int | str]]:
    required: Counter[str] = Counter()
    available_words = words or {}
    for line in text.split("\n"):
        covered = set()
        for start, end, word in word_spans(line):
            if available_words.get(word):
                covered.update(range(start, end))
        required.update(char for index, char in enumerate(line)
                        if index not in covered and char != " ")
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


def render_word_sample(font_dir: str | Path, word: str,
                       placements: list[dict], cell_height_px: int) -> Image.Image:
    """Rasterize edited letters into a canonical, baseline-aligned word PNG."""
    if not WORD_PATTERN.fullmatch(word) or len(placements) != len(word):
        raise CompositionError("词与字母位置不匹配")
    root = Path(font_dir).resolve()
    library = load_library(root, include_disabled=True)
    samples = {sample["glyph_file"]: sample
               for variants in library.values() for sample in variants}
    prepared = []
    bases = []
    for character, placement in zip(word, placements):
        if (placement.get("kind", "glyph") != "glyph" or
                placement["character"] != character):
            raise CompositionError("只能保存由单个字母拼出的词")
        sample = samples.get(placement["sample_file"])
        if sample is None or sample["character"] != character:
            raise CompositionError("词中有无效的字形版本")
        glyph, (origin_y, _, _) = _load_scaled_glyph(sample, root, cell_height_px)
        scale = float(placement.get("scale", 1))
        if not 0.5 <= scale <= 1.5:
            raise CompositionError("词中字母的大小无效")
        if scale != 1:
            glyph = glyph.resize((max(1, round(glyph.width * scale)),
                                  max(1, round(glyph.height * scale))),
                                 Image.Resampling.LANCZOS)
        x, y = int(placement["x"]), int(placement["y"])
        prepared.append((glyph, x, y))
        bases.append(y - origin_y)
    line_base = median(bases)
    left = min(x for _, x, _ in prepared)
    right = max(x + glyph.width for glyph, x, _ in prepared)
    ratio = WORD_BASE_SIZE / cell_height_px
    side = round(cell_height_px * 0.05)
    width = max(1, math.ceil((right - left + 2 * side) * ratio))
    if width > MAX_CANVAS_EDGE:
        raise CompositionError("词图片过宽")
    image = Image.new("RGBA", (width, WORD_CANVAS_HEIGHT), (0, 0, 0, 0))
    for glyph, x, y in prepared:
        target_x = round((x - left + side) * ratio)
        target_y = round((y - line_base) * ratio + WORD_TOP_OFFSET)
        target_size = (max(1, round(glyph.width * ratio)),
                       max(1, round(glyph.height * ratio)))
        resized = glyph.resize(target_size, Image.Resampling.LANCZOS)
        if target_y < 0 or target_y + resized.height > image.height:
            raise CompositionError("词中字母偏离基线过远，请先调整位置")
        image.alpha_composite(resized, (target_x, target_y))
    return image


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
    words = load_word_library(root)
    missing = missing_for(normalized, library, words)
    if missing:
        raise MissingGlyphs(missing)

    seed = settings.seed if settings.seed is not None else secrets.randbits(32)
    rng = random.Random(seed)
    pools = {char: variants.copy() for char, variants in library.items()}
    for variants in pools.values():
        rng.shuffle(variants)
    last_used: dict[str, str] = {}
    word_pools = {word: files.copy() for word, files in words.items()}
    for files in word_pools.values():
        rng.shuffle(files)
    last_word_used: dict[str, str] = {}

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

    def next_word(word: str) -> str:
        pool = word_pools[word]
        if not pool:
            pool.extend(words[word])
            rng.shuffle(pool)
            if len(pool) > 1 and pool[-1] == last_word_used[word]:
                pool[0], pool[-1] = pool[-1], pool[0]
        relative = pool.pop()
        last_word_used[word] = relative
        return relative

    size = settings.cell_height_px
    padding = max(20, round(size * 0.55))
    line_step = size * settings.line_height
    placements: list[dict] = []
    prepared: list[tuple[Image.Image, int, int]] = []
    widest_line = 0.0
    for line_index, line in enumerate(lines):
        cursor = float(padding)
        previous: str | None = None
        spans = {start: (end, word) for start, end, word in word_spans(line)
                 if words.get(word)}
        character_index = 0
        while character_index < len(line):
            word_match = spans.get(character_index)
            character = word_match[1] if word_match else line[character_index]
            if character == " ":
                cursor += size * 0.55
                previous = " "
                character_index += 1
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

            if word_match:
                relative = next_word(character)
                glyph = _load_scaled_word(root, character, relative, size)
                x = round(cursor)
                y = round(padding + line_index * line_step -
                          size * WORD_TOP_OFFSET / WORD_BASE_SIZE)
                advance = glyph.width
                placement = {
                    "kind": "word", "character": character,
                    "line": line_index, "column": character_index,
                    "sample_file": relative,
                }
                character_index = word_match[0]
            else:
                sample = next_sample(character)
                glyph, (origin_y, ink_width, alpha_left) = _load_scaled_glyph(
                    sample, root, size
                )
                x = round(cursor - alpha_left)
                y = round(padding + line_index * line_step + origin_y)
                advance = ink_width
                placement = {
                    "kind": "glyph", "character": character,
                    "line": line_index, "column": character_index,
                    "sample_file": sample["glyph_file"],
                    "sample_row": sample.get("row"),
                    "sample_column": sample.get("column"),
                }
                character_index += 1
            prepared.append((glyph, x, y))
            placements.append({**placement,
                "x": x,
                "y": y,
                "width": glyph.width,
                "height": glyph.height,
                "gap_before_px": round(gap, 2),
            })
            cursor += advance
            previous = character[-1]
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
