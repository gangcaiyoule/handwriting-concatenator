"""FastAPI application with a static, same-origin review interface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.router.imports import router
from api.router.compositions import router as compositions_router


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_app(data_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="手写字拼接器", version="0.1.0")
    app.state.project_root = PROJECT_ROOT
    app.state.data_root = (data_root or PROJECT_ROOT / "data").resolve()
    app.include_router(router)
    app.include_router(compositions_router)
    app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "frontend"),
              name="frontend")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "frontend" / "index.html")

    @app.get("/editor", include_in_schema=False)
    def editor() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "frontend" / "editor.html")

    return app


app = create_app()
