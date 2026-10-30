"""Responses returned to the upload and review interface."""

from __future__ import annotations

from pydantic import BaseModel


class ImportSummary(BaseModel):
    sample_count: int
    glyph_count: int
    review_count: int


class SampleResponse(BaseModel):
    character: str
    codepoint: str
    occurrence: int
    row: int
    column: int
    flags: list[str]
    accepted: bool | None
    original_crop_url: str
    glyph_url: str | None


class ImportResponse(BaseModel):
    id: str
    original_url: str
    registered_url: str
    summary: ImportSummary
    samples: list[SampleResponse]
