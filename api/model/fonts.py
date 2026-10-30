"""HTTP models for named font libraries."""

from __future__ import annotations

from pydantic import BaseModel


class FontCreate(BaseModel):
    name: str


class FontListItem(BaseModel):
    name: str
    upload_count: int
    glyph_count: int
