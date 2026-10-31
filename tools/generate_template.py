"""Generate a one-page A4 handwriting collection sheet and cell map."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import json
import string
from pathlib import Path

import cv2
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from handwriting_concat.marks import STRIKE_DIAGONAL, STRIKE_HORIZONTAL


ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "手写字母采集模板_A4.pdf"
LAYOUT_PATH = ROOT / "pkg" / "handwriting_concat" / "assets" / "template_v2.json"

PAGE_W, PAGE_H = A4
pdfmetrics.registerFont(TTFont("SimHei", r"C:\Windows\Fonts\simhei.ttf"))

# All geometry is in millimetres from the top-left of one A4 page.
GRID_X = 17.5
GRID_TOP = 50.5
CELL_W = 7.5
BOX_H = 7.3
BOX_OFFSET = 3.4
ROW_STEP = 11.35
COLS = 24
MAX_ROWS = 20

ARUCO_DICTIONARY_NAME = "DICT_4X4_50"
ARUCO_DICTIONARY = cv2.aruco.getPredefinedDictionary(
    cv2.aruco.DICT_4X4_50
)
MARKER_SIZE_MM = 9.0
# Each marker has at least 1.5 mm of unprinted white space around it.
REGISTRATION_MARKERS = [
    {"corner": "top_left", "id": 11, "bbox_mm": [7.5, 7.5, 16.5, 16.5]},
    {"corner": "top_right", "id": 17, "bbox_mm": [193.5, 7.5, 202.5, 16.5]},
    {"corner": "bottom_left", "id": 23, "bbox_mm": [7.5, 281.5, 16.5, 290.5]},
    {"corner": "bottom_right", "id": 29, "bbox_mm": [193.5, 281.5, 202.5, 290.5]},
]

INK = colors.HexColor("#192832")
MUTED = colors.HexColor("#536977")
PROMPT = colors.HexColor("#667E8D")
GRID = colors.HexColor("#B5C9D4")
EMPTY = colors.HexColor("#F0F4F6")
SEPARATOR = colors.HexColor("#8FAFBE")

PASSAGE = (
    "A structural hazard occurs when pipeline stages need the same hardware "
    "resource at the same time. For example, instruction fetch and data "
    "access conflict if they share one single-port memory. Solutions include "
    "stalling a stage or providing separate or additional resources."
)
LETTER_TARGET = 3
COMMON_PUNCTUATION = ".,!?;:'\"()-"


def y(top_mm: float) -> float:
    return PAGE_H - top_mm * mm


def draw_text(c: canvas.Canvas, x_mm: float, top_mm: float, value: str,
              size: float, color: colors.Color = INK) -> None:
    c.setFont("SimHei", size)
    c.setFillColor(color)
    c.drawString(x_mm * mm, y(top_mm), value)


def wrap_words(value: str, limit: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in value.split(" "):
        candidate = f"{current} {word}" if current else word
        if len(candidate) > limit and current:
            lines.append(current)
            current = word
        else:
            current = candidate
        if len(current) > limit:
            raise ValueError(f"Word too long for a {limit}-cell line: {word}")
    if current:
        lines.append(current)
    return lines


def wrap_display(value: str, max_width_pt: float, size: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in value.split(" "):
        candidate = f"{current} {word}" if current else word
        if pdfmetrics.stringWidth(candidate, "Helvetica", size) > max_width_pt and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_rows() -> tuple[list[dict], dict[str, int]]:
    main_lines = wrap_words(PASSAGE, COLS)
    counts = Counter("".join(main_lines).replace(" ", ""))
    deficits: dict[str, int] = {}

    for char in string.ascii_lowercase + string.ascii_uppercase:
        deficits[char] = max(0, LETTER_TARGET - counts[char])
    for char in string.punctuation:
        target = 3 if char in COMMON_PUNCTUATION else 1
        deficits[char] = max(0, target - counts[char])
    for char in string.digits:
        deficits[char] = max(0, 1 - counts[char])

    # Interleave characters by rounds so repeated samples are not adjacent.
    supplement = ""
    while any(deficits.values()):
        for char in deficits:
            if deficits[char] > 0:
                supplement += char
                deficits[char] -= 1

    extra_lines = [supplement[i:i + COLS]
                   for i in range(0, len(supplement), COLS)]
    # The final supplement line has room for four arrows and four wider
    # handwritten strike samples without adding an A4 row.
    if len(extra_lines[-1]) > 10:
        raise ValueError("Last supplement row has no room for editing marks")
    extra_lines[-1] += "→" * 4
    rows = ([{"section": "passage", "prompt": line} for line in main_lines]
            + [{"section": "supplement", "prompt": line}
               for line in extra_lines])
    if len(rows) > MAX_ROWS:
        raise ValueError(f"{len(rows)} rows exceed one A4 page")

    final_counts = Counter("".join(row["prompt"] for row in rows).replace(" ", ""))
    final_counts[STRIKE_HORIZONTAL] = 2
    final_counts[STRIKE_DIAGONAL] = 2
    assert all(final_counts[ch] >= LETTER_TARGET
               for ch in string.ascii_letters)
    assert all(final_counts[ch] >= 1 for ch in string.punctuation + string.digits)
    return rows, dict(final_counts)


def draw_registration_marks(c: canvas.Canvas) -> None:
    for marker in REGISTRATION_MARKERS:
        marker_image = cv2.aruco.generateImageMarker(
            ARUCO_DICTIONARY, marker["id"], 600
        )
        success, png = cv2.imencode(".png", marker_image)
        if not success:
            raise RuntimeError(f"Could not encode ArUco marker {marker['id']}")
        left, top, right, bottom = marker["bbox_mm"]
        c.drawImage(
            ImageReader(BytesIO(png.tobytes())),
            left * mm,
            y(bottom),
            width=(right - left) * mm,
            height=(bottom - top) * mm,
            mask="auto",
        )


def main() -> None:
    rows, final_counts = build_rows()
    c = canvas.Canvas(str(PDF_PATH), pagesize=A4, pageCompression=1)
    c.setTitle("手写字母采集模板 A4 单页版")
    c.setAuthor("手写字拼接器")
    draw_registration_marks(c)

    draw_text(c, 20.5, 19.5, "手写字母采集模板", 16.5)
    c.setFont("SimHei", 8.5)
    c.setFillColor(MUTED)
    c.drawRightString(190 * mm, y(19.5), "单页 A4  ·  大小写字母各至少 3 次")
    draw_text(c, 14, 25, "例文", 8.5)
    display_lines = wrap_display(PASSAGE, 183.5 * mm, 7.8)
    if len(display_lines) > 3:
        raise ValueError("Reference passage needs more than three display lines")
    c.setFont("Helvetica", 7.8)
    c.setFillColor(INK)
    for i, line in enumerate(display_lines):
        c.drawString(14 * mm, y(29.5 + 4 * i), line)
    draw_text(c, 14, 42, "按格上方字符抄写；末行的宽格请分别手写横线、斜线，笔迹尽量横贯宽格。", 8.1)
    draw_text(c, 14, 46.5, "黑色细笔、不碰边框；箭头写在小格。按 100% 打印并保留四角定位码。", 8.1, MUTED)

    cells = []
    occurrences: Counter[str] = Counter()
    previous_section = None
    for row_idx, row in enumerate(rows):
        row_top = GRID_TOP + row_idx * ROW_STEP
        section = row["section"]
        if section != previous_section and section == "supplement":
            c.setStrokeColor(SEPARATOR)
            c.setLineWidth(1.0)
            c.line(GRID_X * mm, y(row_top - 0.25),
                   (GRID_X + COLS * CELL_W) * mm, y(row_top - 0.25))
        previous_section = section

        c.setFont("SimHei", 6.8)
        c.setFillColor(MUTED)
        c.drawRightString(16.1 * mm, y(row_top + BOX_OFFSET + 4.9),
                          f"{row_idx + 1:02d}")

        for col_idx in range(COLS):
            if row_idx == len(rows) - 1 and col_idx >= 14:
                break
            char = row["prompt"][col_idx] if col_idx < len(row["prompt"]) else None
            box_left = GRID_X + col_idx * CELL_W
            box_top = row_top + BOX_OFFSET
            should_write = char is not None and char != " "

            c.setFillColor(colors.white if should_write else EMPTY)
            c.setStrokeColor(GRID)
            c.setLineWidth(0.42)
            c.rect(box_left * mm, y(box_top + BOX_H), CELL_W * mm,
                   BOX_H * mm, fill=1, stroke=1)
            if should_write:
                c.setFont("SimHei" if char == "→" else "Courier-Bold", 8.5)
                c.setFillColor(PROMPT)
                c.drawCentredString((box_left + CELL_W / 2) * mm,
                                    y(row_top + 2.7), char)
                occurrences[char] += 1

            cells.append({
                "row": row_idx,
                "column": col_idx,
                "section": section,
                "character": char,
                "write": should_write,
                "occurrence": occurrences[char] if should_write else None,
                "cell_bbox_mm": [round(box_left, 3), round(box_top, 3),
                                 round(box_left + CELL_W, 3),
                                 round(box_top + BOX_H, 3)],
                "safe_bbox_mm": [round(box_left + 0.55, 3),
                                 round(box_top + 0.55, 3),
                                 round(box_left + CELL_W - 0.55, 3),
                                 round(box_top + BOX_H - 0.55, 3)],
            })

        if row_idx == len(rows) - 1:
            # Ten regular cells remain after the arrow samples. Divide their
            # width into four larger boxes so a real pen stroke can be drawn.
            start_x = GRID_X + 14 * CELL_W
            stroke_width = (COLS - 14) * CELL_W / 4
            for stroke_index, (character, label) in enumerate((
                (STRIKE_HORIZONTAL, "横线 1"), (STRIKE_HORIZONTAL, "横线 2"),
                (STRIKE_DIAGONAL, "斜线 1"), (STRIKE_DIAGONAL, "斜线 2"),
            )):
                box_left = start_x + stroke_index * stroke_width
                box_top = row_top + BOX_OFFSET
                c.setFillColor(colors.white)
                c.setStrokeColor(GRID)
                c.setLineWidth(0.42)
                c.rect(box_left * mm, y(box_top + BOX_H), stroke_width * mm,
                       BOX_H * mm, fill=1, stroke=1)
                c.setFont("SimHei", 7.5)
                c.setFillColor(PROMPT)
                c.drawCentredString((box_left + stroke_width / 2) * mm,
                                    y(row_top + 2.7), label)
                occurrences[character] += 1
                cells.append({
                    "row": row_idx, "column": 14 + stroke_index,
                    "section": "strike", "character": character,
                    "write": True, "occurrence": occurrences[character],
                    "cell_bbox_mm": [round(box_left, 3), round(box_top, 3),
                                     round(box_left + stroke_width, 3),
                                     round(box_top + BOX_H, 3)],
                    "safe_bbox_mm": [round(box_left + 0.8, 3),
                                     round(box_top + 0.55, 3),
                                     round(box_left + stroke_width - 0.8, 3),
                                     round(box_top + BOX_H - 0.55, 3)],
                })

    draw_text(c, 20.5, 281.1,
              f"前 {sum(r['section'] == 'passage' for r in rows)} 行抄短文，末行补箭头与手写删除线。", 7.5, MUTED)
    c.setFont("SimHei", 7.5)
    c.setFillColor(MUTED)
    c.drawRightString(190 * mm, y(281.1), "请勿裁边、缩放或双面打印")
    c.showPage()
    c.save()

    layout = {
        "format": "A4 portrait",
        "template_version": 2,
        "page_size_mm": [210, 297],
        "coordinate_origin": "top-left",
        "print_scale": "100% / actual size",
        "letter_target_per_case": LETTER_TARGET,
        "source_passage": PASSAGE,
        "registration_marker_type": "ArUco",
        "registration_dictionary": ARUCO_DICTIONARY_NAME,
        "registration_marker_size_mm": MARKER_SIZE_MM,
        "registration_markers": REGISTRATION_MARKERS,
        "registration_mark_boxes_mm": [
            marker["bbox_mm"] for marker in REGISTRATION_MARKERS
        ],
        "rows": rows,
        "final_character_counts": final_counts,
        "cells": cells,
    }
    LAYOUT_PATH.write_text(json.dumps(layout, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"PDF: {PDF_PATH}")
    print(f"Layout: {LAYOUT_PATH}")
    print(f"Rows: {len(rows)}; glyph samples: {sum(final_counts.values())}")


if __name__ == "__main__":
    main()
