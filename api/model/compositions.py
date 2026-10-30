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


class PlacementEdit(BaseModel):
    index: int = Field(ge=0)
    sample_file: str
    x: int = Field(ge=0, le=12000)
    y: int = Field(ge=0, le=12000)
    scale: float = Field(ge=0.5, le=1.5)
    kind: Literal["glyph", "word"] | None = None
    character: str | None = None
    line: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)


class DraftUpdate(BaseModel):
    revision: int = Field(ge=0)
    placements: list[PlacementEdit] = Field(max_length=2000)


class DraftResponse(BaseModel):
    id: str
    font_id: str
    text: str
    revision: int
    width: int
    height: int
    line_count: int
    background: Literal["white", "transparent"]
    cell_height_px: int
    placements: list[dict]
    variants: list[dict]


class WordCandidate(BaseModel):
    key: str
    word: str
    line: int
    column: int
    saved: bool
    preview_url: str


class SaveWordsRequest(BaseModel):
    revision: int = Field(ge=0)
    keys: list[str] = Field(max_length=2000)


class SavedWord(BaseModel):
    word: str
    file: str
