"""Geometry edits shared by the browser editor and the local agent CLI."""

from __future__ import annotations

from copy import deepcopy
from statistics import median

from .composition import CompositionError


def align_baselines_exact(placements: list[dict], line: int | None = None) -> list[dict]:
    """Align eligible letter bottoms in one step using the editor's median rule.

    The browser's light alignment uses the same eligible letters, but moves
    toward this median gradually. A taller glyph can require a nonnegative
    baseline so its top remains on the canvas.
    """
    items = deepcopy(placements)
    lines = {item["line"] for item in items} if line is None else {line}
    for current_line in lines:
        eligible = [item for item in items
                    if item["line"] == current_line
                    and item.get("kind", "glyph") == "glyph"
                    and len(item["character"]) == 1
                    and item["character"].isascii()
                    and item["character"].isalpha()
                    and item["character"] not in "gjpqy"]
        if not eligible:
            continue
        target = max(int(median(item["y"] + item["height"] for item in eligible) + 0.5),
                     max(item["height"] for item in eligible))
        for item in eligible:
            item["y"] = target - item["height"]
    _check_positions(items)
    return items


def _target(items: list[dict], line: int, column: int) -> int:
    for index, item in enumerate(items):
        if item["line"] == line and item["column"] == column:
            return index
    raise CompositionError(f"第 {line + 1} 行第 {column + 1} 位没有可编辑的字形")


def _shift_following(items: list[dict], index: int, dx: int) -> None:
    line = items[index]["line"]
    for item in items[index:]:
        if item["line"] != line:
            break
        item["x"] += dx


def _required(op: dict, *fields: str) -> None:
    missing = [field for field in fields if op.get(field) is None]
    if missing:
        raise CompositionError(f"{op['type']} 缺少参数：{', '.join(missing)}")


def _check_positions(items: list[dict]) -> None:
    for item in items:
        if (item["x"] < 0 or item["y"] < 0 or
                item["x"] + item["width"] > 12000 or
                item["y"] + item["height"] > 12000):
            raise CompositionError("编辑后的字形超出 12000 px 画布范围")


def apply_edit_operations(placements: list[dict], variants: list[dict],
                          cell_height_px: int, operations: list[dict]) -> list[dict]:
    """Apply operations located by original text line/column, never array index.

    Range endpoints are zero-based columns, with end_column excluded. A range
    must include whole placements; a saved word is one indivisible placement.
    """
    items = deepcopy(placements)
    by_file = {variant["sample_file"]: variant for variant in variants}
    for op in operations:
        kind = op["type"]
        if kind == "move":
            _required(op, "line", "column", "dx", "dy")
            line, start = op["line"], op["column"]
            index = _target(items, line, start)
            end = op.get("end_column")
            if end is None:
                selected = [items[index]]
            else:
                if end <= start:
                    raise CompositionError("end_column 必须大于 column")
                selected = [item for item in items if item["line"] == line and
                            start <= item["column"] < end]
                if any(item["column"] + len(item["character"]) > end
                       for item in selected):
                    raise CompositionError("移动范围不能只包含整词的一部分")
            for item in selected:
                item["x"] += op["dx"]
                item["y"] += op["dy"]
        elif kind == "move_line":
            _required(op, "line", "dx", "dy")
            selected = [item for item in items if item["line"] == op["line"]]
            if not selected:
                raise CompositionError(f"第 {op['line'] + 1} 行没有可移动的字形")
            for item in selected:
                item["x"] += op["dx"]
                item["y"] += op["dy"]
        elif kind == "set_gap":
            _required(op, "line", "column", "gap_px")
            index = _target(items, op["line"], op["column"])
            previous = next((item for item in reversed(items[:index])
                             if item["line"] == op["line"]), None)
            if previous is None:
                raise CompositionError("行首字形没有字前间距")
            current = items[index]["x"] - previous["x"] - previous["width"]
            _shift_following(items, index, op["gap_px"] - current)
        elif kind == "replace_variant":
            _required(op, "line", "column", "sample_file")
            index = _target(items, op["line"], op["column"])
            item = items[index]
            variant = by_file.get(op["sample_file"])
            if (variant is None or variant["kind"] != item.get("kind", "glyph") or
                    variant["character"] != item["character"] or
                    not variant["accepted"]):
                raise CompositionError("替换版本不存在、已停用或与文字不匹配")
            old_width, old_height = item["width"], item["height"]
            item["sample_file"] = variant["sample_file"]
            item["width"] = max(1, round(variant["width"] * item.get("scale", 1)))
            item["height"] = max(1, round(variant["height"] * item.get("scale", 1)))
            item["y"] += round((old_height - item["height"]) / 2)
            if index + 1 < len(items) and items[index + 1]["line"] == item["line"]:
                _shift_following(items, index + 1, item["width"] - old_width)
        elif kind == "replace_unavailable":
            usage: dict[str, int] = {}
            for item in items:
                variant = by_file.get(item["sample_file"])
                if variant and variant["accepted"]:
                    usage[item["sample_file"]] = usage.get(item["sample_file"], 0) + 1
            for index, item in enumerate(items):
                current = by_file.get(item["sample_file"])
                if item.get("kind", "glyph") == "word" or (current and current["accepted"]):
                    continue
                alternatives = [variant for variant in variants
                                if variant["kind"] == "glyph" and
                                variant["character"] == item["character"] and
                                variant["accepted"]]
                if not alternatives:
                    continue
                choice = min(alternatives, key=lambda variant: usage.get(variant["sample_file"], 0))
                old_width, old_height = item["width"], item["height"]
                item["sample_file"] = choice["sample_file"]
                item["width"] = max(1, round(choice["width"] * item.get("scale", 1)))
                item["height"] = max(1, round(choice["height"] * item.get("scale", 1)))
                item["y"] = max(0, item["y"] + round((old_height - item["height"]) / 2))
                if index + 1 < len(items) and items[index + 1]["line"] == item["line"]:
                    _shift_following(items, index + 1, item["width"] - old_width)
                usage[choice["sample_file"]] = usage.get(choice["sample_file"], 0) + 1
        elif kind == "split_word":
            _required(op, "line", "column")
            index = _target(items, op["line"], op["column"])
            item = items[index]
            if item.get("kind") != "word":
                raise CompositionError("目标不是整词")
            letters = list(item["character"])
            choices = [next((variant for variant in variants
                             if variant["kind"] == "glyph" and
                             variant["character"] == character and variant["accepted"]), None)
                       for character in letters]
            if any(choice is None for choice in choices):
                raise CompositionError("这个词有字母缺少可用字形，无法拆开")
            side = round(cell_height_px * 0.05 * item.get("scale", 1))
            usable = max(1, item["width"] - side * 2)
            natural = sum(choice["width"] for choice in choices)
            scale = max(0.5, min(1.5, usable / natural))
            widths = [max(1, round(choice["width"] * scale)) for choice in choices]
            gap = (max(-cell_height_px * 0.2,
                       min(cell_height_px * 0.3,
                           (usable - sum(widths)) / (len(letters) - 1)))
                   if len(letters) > 1 else 0)
            cursor = item["x"] + side
            replacements = []
            for offset, (character, choice, width) in enumerate(zip(letters, choices, widths)):
                height = max(1, round(choice["height"] * scale))
                replacements.append({
                    "kind": "glyph", "character": character, "line": item["line"],
                    "column": item["column"] + offset, "sample_file": choice["sample_file"],
                    "x": max(0, round(cursor)),
                    "y": max(0, round(item["y"] + (item["height"] - height) / 2)),
                    "width": width, "height": height, "scale": scale,
                })
                cursor += width + gap
            difference = (replacements[-1]["x"] + replacements[-1]["width"] -
                          item["x"] - item["width"])
            items[index:index + 1] = replacements
            next_index = index + len(replacements)
            if next_index < len(items) and items[next_index]["line"] == item["line"]:
                _shift_following(items, next_index, difference)
        else:
            raise CompositionError(f"未知编辑操作：{kind}")
        _check_positions(items)
    for index, item in enumerate(items):
        item["index"] = index
    return items
