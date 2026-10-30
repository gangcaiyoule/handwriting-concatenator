"""The import workflow shared by a CLI and any future HTTP adapter."""

from __future__ import annotations

from pathlib import Path

from .cells import crop_cell
from .image_io import load_image
from .ink import extract_ink
from .quality import review_flags
from .registration import register_page
from .storage import OutputStore
from .template import load_template
from .types import ExtractionReport


def extract_page(image_path: str | Path, output_dir: str | Path, *,
                 layout_path: str | Path | None = None,
                 output_dpi: int | None = None,
                 pdf_dpi: int = 600) -> ExtractionReport:
    """Extract all writable cells from one version-2 collection sheet.

    The output directory must not contain existing files; original input and
    raw cell crops are retained so users can revisit segmentation decisions.
    """
    source = Path(image_path).resolve()
    layout = load_template(layout_path)
    input_rgb = load_image(source, pdf_dpi=pdf_dpi)
    registration = register_page(input_rgb, layout, output_dpi=output_dpi)

    store = OutputStore(output_dir)
    source_file = store.copy_source(source)
    registered_file = store.save_rgb("registered_page.png", registration.rgb)
    samples: list[dict] = []
    glyph_count = 0
    review_count = 0

    for cell in layout.cells:
        if not cell.write:
            continue
        assert cell.character is not None and cell.occurrence is not None
        crop, safe_bbox_px = crop_cell(registration.rgb, cell, layout)
        crop_file = store.save_rgb(
            f"cells/r{cell.row + 1:02d}_c{cell.column + 1:02d}.png", crop
        )
        ink = extract_ink(crop)
        flags = review_flags(ink)
        glyph_file = None
        if ink.rgba is not None:
            codepoint = f"U+{ord(cell.character):04X}"
            glyph_file = store.save_rgba(
                f"glyphs/{codepoint}/{cell.occurrence:03d}.png", ink.rgba
            )
            glyph_count += 1
        if flags:
            review_count += 1

        samples.append({
            "character": cell.character,
            "codepoint": f"U+{ord(cell.character):04X}",
            "occurrence": cell.occurrence,
            "row": cell.row,
            "column": cell.column,
            "cell_bbox_mm": list(cell.cell_bbox_mm),
            "safe_bbox_mm": list(cell.safe_bbox_mm),
            "safe_bbox_px": list(safe_bbox_px),
            "ink_bbox_in_crop_px": (list(ink.ink_bbox_px)
                                     if ink.ink_bbox_px else None),
            "ink_bottom_offset_in_crop_px": (
                int(crop.shape[0] - ink.ink_bbox_px[3])
                if ink.ink_bbox_px else None
            ),
            "crop_size_px": [int(crop.shape[1]), int(crop.shape[0])],
            "foreground_pixels": ink.foreground_pixels,
            "peak_contrast": round(ink.peak_contrast, 2),
            "flags": flags,
            "accepted": None,
            "original_crop": crop_file,
            "glyph_file": glyph_file,
        })

    manifest = {
        "schema_version": 1,
        "template_version": layout.version,
        "source_file": source_file,
        "registered_page": registered_file,
        "registration": {
            "detected_ids": list(registration.detected_ids),
            "input_size_px": list(registration.input_size_px),
            "output_size_px": [int(registration.rgb.shape[1]),
                               int(registration.rgb.shape[0])],
            "output_dpi": registration.output_dpi,
            "reprojection_rms_px": round(registration.reprojection_rms_px, 3),
            "homography": registration.homography.tolist(),
        },
        "summary": {
            "sample_count": len(samples),
            "glyph_count": glyph_count,
            "review_count": review_count,
        },
        "samples": samples,
    }
    manifest_path = store.write_manifest(manifest)
    return ExtractionReport(store.root, len(samples), glyph_count,
                            review_count, manifest_path)
