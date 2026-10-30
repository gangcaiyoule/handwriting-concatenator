"""Responses returned to the upload and review interface."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    upload_id: str | None = None


class ImportResponse(BaseModel):
    id: str
    original_url: str | None
    registered_url: str | None
    summary: ImportSummary
    samples: list[SampleResponse]
    upload_count: int = 0
    latest_upload_id: str | None = None
    word_counts: dict[str, int] = Field(default_factory=dict)
    legacy_imports: list[str] = Field(default_factory=list)


class SampleAcceptanceUpdate(BaseModel):
    sample_file: str
    accepted: bool
