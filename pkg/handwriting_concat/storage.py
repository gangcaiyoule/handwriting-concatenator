"""Persist an extraction run as images plus a reviewable manifest."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image


class OutputStore:
    def __init__(self, output_dir: str | Path) -> None:
        self.root = Path(output_dir).resolve()
        if self.root.exists() and any(self.root.iterdir()):
            raise FileExistsError(f"Output directory is not empty: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)

    def copy_source(self, source: Path) -> str:
        destination = self.root / f"source{source.suffix.lower()}"
        shutil.copy2(source, destination)
        return destination.name

    def save_rgb(self, relative: str, rgb: np.ndarray) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgb).save(path)
        return path.relative_to(self.root).as_posix()

    def save_rgba(self, relative: str, rgba: np.ndarray) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgba).save(path)
        return path.relative_to(self.root).as_posix()

    def write_manifest(self, data: dict) -> Path:
        path = self.root / "manifest.json"
        temporary = self.root / "manifest.json.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(path)
        return path
