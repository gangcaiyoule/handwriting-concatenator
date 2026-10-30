"""List and create named font libraries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.handler.imports import load_result
from api.handler.libraries import (
    LibraryError, claim_legacy, ensure_library, list_libraries,
)
from api.model.fonts import FontCreate, FontListItem
from api.model.imports import ImportResponse


router = APIRouter(prefix="/api/fonts")


@router.get("", response_model=list[FontListItem])
def get_fonts(request: Request) -> list[FontListItem]:
    return [FontListItem(**item) for item in list_libraries(request.app.state.data_root)]


@router.post("", response_model=ImportResponse, status_code=201)
def create_font(request: Request, payload: FontCreate) -> ImportResponse:
    try:
        ensure_library(request.app.state.data_root, payload.name)
        return load_result(request.app.state.data_root, payload.name.strip())
    except LibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{font_name}/claim/{upload_id}", response_model=ImportResponse)
def claim_old_import(request: Request, font_name: str,
                     upload_id: str) -> ImportResponse:
    try:
        claim_legacy(request.app.state.data_root, font_name, upload_id)
        return load_result(request.app.state.data_root, font_name)
    except LibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
