"""The FastAPI app: JSON API under /api, static pages for everything else."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from studydesk import __version__
from studydesk.config import Config, ConfigError, load_config
from studydesk.courses import CatalogFile, Course
from studydesk.db import Database

WEB_DIR = Path(__file__).parent / "web"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _hhmm(value) -> str | None:
    return value.strftime("%H:%M") if value else None


def create_app(config: Config | None = None, now: Callable[[], datetime] | None = None) -> FastAPI:
    config = config or load_config()
    db = Database(config.database_path)
    db.migrate()
    catalog_file = CatalogFile(config.data_root)

    app = FastAPI(title="study-desk", version=__version__)
    app.state.config = config
    app.state.db = db
    app.state.catalog = catalog_file

    def clock() -> datetime:
        return now() if now else datetime.now(catalog_file.get().timezone)

    def has_syllabus(course: Course) -> bool:
        return bool(config.data_root and course.syllabus and (config.data_root / course.folder / course.syllabus).exists())

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = exc.detail if isinstance(exc.detail, str) else "error"
        return _error(exc.status_code, code, code.replace("_", " "))

    @app.exception_handler(ConfigError)
    async def config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return _error(422, "config_invalid", str(exc))

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "data_root_configured": config.data_root is not None,
        }

    @app.get("/api/courses")
    def courses() -> dict:
        catalog = catalog_file.get()
        return {
            "configured": catalog_file.path is not None and catalog_file.path.exists(),
            "courses": [
                {
                    "code": c.code,
                    "name": c.name,
                    "aliases": list(c.aliases),
                    "folder": c.folder,
                    "language": c.language,
                    "has_syllabus": has_syllabus(c),
                }
                for c in catalog.courses
            ],
        }

    @app.get("/api/today")
    def today(day: date | None = None) -> dict:
        catalog = catalog_file.get()
        moment = clock().astimezone(catalog.timezone)
        day = day or moment.date()
        current = catalog.current(moment) if day == moment.date() else None
        classes = []
        for occ in catalog.occurrences(day):
            topic = occ.course.topic_for(day)
            classes.append(
                {
                    "code": occ.course.code,
                    "name": occ.course.name,
                    "kind": occ.slot.kind,
                    "start": _hhmm(occ.start),
                    "end": _hhmm(occ.end),
                    "location": occ.slot.location,
                    "topic": topic.title if topic else None,
                }
            )
        exams = [
            {
                "code": c.code,
                "name": c.name,
                "title": e.title,
                "date": e.date.isoformat(),
                "start": _hhmm(e.start),
                "days_left": (e.date - day).days,
            }
            for c, e in catalog.upcoming_exams(day)
        ]
        return {
            "date": day.isoformat(),
            "configured": bool(catalog.courses),
            "classes": classes,
            "exams": exams,
            "current": (
                {"code": current.course.code, "name": current.course.name, "start": _hhmm(current.start), "end": _hhmm(current.end)}
                if current
                else None
            ),
        }

    # Unknown API paths answer in the API's error shape, not as a missing page.
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail="not_found")

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
