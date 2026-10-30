"""Command-line entry point for running and inspecting an extraction."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import extract_page


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract handwriting from the version-2 A4 collection sheet"
    )
    parser.add_argument("input", type=Path, help="Scan/photo (PNG, JPEG, TIFF or PDF)")
    parser.add_argument("-o", "--output", type=Path,
                        help="New output directory (default: <input-stem>_glyphs)")
    parser.add_argument("--layout", type=Path,
                        help="Override the bundled template_v2.json")
    parser.add_argument("--dpi", type=int,
                        help="Output DPI; default follows source marker resolution, capped at 600")
    parser.add_argument("--pdf-dpi", type=int, default=600,
                        help="PDF render DPI before registration (default: 600)")
    args = parser.parse_args()
    output = args.output or args.input.with_name(f"{args.input.stem}_glyphs")
    try:
        report = extract_page(args.input, output, layout_path=args.layout,
                              output_dpi=args.dpi, pdf_dpi=args.pdf_dpi)
    except (ValueError, FileExistsError, OSError) as exc:
        parser.exit(2, f"Extraction failed: {exc}\n")
    print(f"Output: {report.output_dir}")
    print(f"Samples: {report.sample_count}; glyphs: {report.glyph_count}; "
          f"needs review: {report.review_count}")
    print(f"Manifest: {report.manifest_path}")
