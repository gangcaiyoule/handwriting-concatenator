"""Upload and review endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from api.handler.imports import (
    ImportErrorMessage,
    load_result,
    resolve_original,
    resolve_result_image,
    save_and_extract,
)
from api.model.imports import ImportResponse


router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/template")
def template(request: Request) -> FileResponse:
    return FileResponse(
        request.app.state.project_root / "手写字母采集模板_A4.pdf",
        filename="手写字母采集模板_A4.pdf",
        media_type="application/pdf",
    )


@router.post("/imports", response_model=ImportResponse, status_code=201)
async def upload_page(request: Request, file: UploadFile = File(...)) -> ImportResponse:
    try:
        return await save_and_extract(file, request.app.state.data_root)
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/imports/{run_id}", response_model=ImportResponse)
def get_import(request: Request, run_id: str) -> ImportResponse:
    try:
        return load_result(request.app.state.data_root, run_id)
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{run_id}/original")
def get_original(request: Request, run_id: str) -> FileResponse:
    try:
        return FileResponse(resolve_original(request.app.state.data_root, run_id))
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imports/{run_id}/manifest")
def get_manifest(request: Request, run_id: str) -> FileResponse:
    try:
        result = load_result(request.app.state.data_root, run_id)
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    manifest = Path(request.app.state.data_root) / "fonts" / "english" / result.id / "manifest.json"
    return FileResponse(manifest, media_type="application/json")


@router.get("/imports/{run_id}/images/{image_path:path}")
def get_image(request: Request, run_id: str, image_path: str) -> FileResponse:
    try:
        return FileResponse(resolve_result_image(
            request.app.state.data_root, run_id, image_path
        ))
    except ImportErrorMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
