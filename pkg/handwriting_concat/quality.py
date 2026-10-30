"""Explain which samples need attention after mechanical extraction."""

from __future__ import annotations

from .types import InkResult


def review_flags(ink: InkResult) -> list[str]:
    flags: list[str] = []
    if ink.rgba is None:
        return ["empty"]
    if ink.touches_border:
        flags.append("touches_border")
    if ink.peak_contrast < 80:
        flags.append("low_contrast")
    return flags
