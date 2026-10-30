"""HTTP models for line-preserving handwriting composition."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CompositionRequest(BaseModel):
    font_id: str
    text: str = Field(min_length=1, max_length=2000)
    cell_height_px: int = Field(default=72, ge=32, le=140)
    spacing_jitter: float = Field(default=0.05, ge=0, le=0.2)
    line_height: float = Field(default=1.55, ge=1.1, le=2.5)
    background: Literal["white", "transparent"] = "white"
    seed: int | None = Field(default=None, ge=0, lt=2**32)


class CompositionResponse(BaseModel):
    id: str
    font_id: str
    text: str
    seed: int
    width: int
    height: int
    line_count: int
    background: Literal["white", "transparent"]
    image_url: str
    download_url: str
