"""The FastAPI app: JSON API under /api, static pages for everything else."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from studydesk import __version__
from studydesk.config import Config, load_config
from studydesk.db import Database

WEB_DIR = Path(__file__).parent / "web"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    db = Database(config.database_path)
    db.migrate()

    app = FastAPI(title="study-desk", version=__version__)
    app.state.config = config
    app.state.db = db

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = exc.detail if isinstance(exc.detail, str) else "error"
        return _error(exc.status_code, code, code.replace("_", " "))

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "data_root_configured": config.data_root is not None,
        }

    # Unknown API paths answer in the API's error shape, not as a missing page.
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail="not_found")

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
