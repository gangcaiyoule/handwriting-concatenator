"""Decode uploads while preserving the original image resolution."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


class ImageInputError(ValueError):
    """An input cannot be decoded as a supported, single-page image."""


def load_image(path: str | Path, *, pdf_dpi: int = 600) -> np.ndarray:
    source = Path(path)
    if not source.is_file():
        raise ImageInputError(f"Input file does not exist: {source}")
    if not 100 <= pdf_dpi <= 600:
        raise ImageInputError("PDF render DPI must be between 100 and 600")

    if source.suffix.lower() == ".pdf":
        try:
            info = subprocess.run(
                ["pdfinfo", str(source)], check=True,
                capture_output=True, timeout=30,
            )
            match = re.search(rb"^Pages:\s*(\d+)", info.stdout, re.MULTILINE)
            if match is None or int(match.group(1)) != 1:
                raise ImageInputError("PDF input must contain exactly one page")
            with tempfile.TemporaryDirectory() as temp_dir:
                prefix = Path(temp_dir) / "page"
                subprocess.run(
                    ["pdftoppm", "-f", "1", "-l", "1", "-singlefile",
                     "-png", "-r", str(pdf_dpi), str(source), str(prefix)],
                    check=True, capture_output=True, timeout=120,
                )
                with Image.open(prefix.with_suffix(".png")) as rendered:
                    return np.asarray(rendered.convert("RGB")).copy()
        except (FileNotFoundError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired, OSError) as exc:
            raise ImageInputError(
                "Could not render PDF; install Poppler with pdfinfo and pdftoppm"
            ) from exc

    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            if getattr(image, "n_frames", 1) != 1:
                raise ImageInputError("Image input must contain exactly one frame")
            rgb = image.convert("RGB")
            return np.asarray(rgb).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageInputError(f"Could not decode image: {source}") from exc
