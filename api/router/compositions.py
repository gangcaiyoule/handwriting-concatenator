"""Render and retrieve handwritten text compositions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from handwriting_concat.composition import CompositionError, MissingGlyphs

from api.handler.compositions import (
    composition_image,
    create_composition,
    load_composition,
)
from api.handler.imports import ImportErrorMessage
from api.model.compositions import CompositionRequest, CompositionResponse


router = APIRouter(prefix="/api/compositions")


@router.post("", response_model=CompositionResponse, status_code=201)
async def render_text(request: Request,
                      payload: CompositionRequest) -> CompositionResponse:
    try:
        return await create_composition(request.app.state.data_root, payload)
    except MissingGlyphs as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "存在没有可用字形的字符，无法拼接", "missing": exc.missing},
        ) from exc
    except (CompositionError, ImportErrorMessage) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{render_id}", response_model=CompositionResponse)
def get_composition(request: Request, render_id: str) -> CompositionResponse:
    try:
        return load_composition(request.app.state.data_root, render_id)
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{render_id}/image")
def get_image(request: Request, render_id: str) -> FileResponse:
    try:
        return FileResponse(composition_image(request.app.state.data_root, render_id),
                            media_type="image/png")
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{render_id}/download")
def download_image(request: Request, render_id: str) -> FileResponse:
    try:
        return FileResponse(
            composition_image(request.app.state.data_root, render_id),
            media_type="image/png",
            filename=f"handwriting-{render_id}.png",
        )
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
