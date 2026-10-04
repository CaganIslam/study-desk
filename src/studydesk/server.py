"""The FastAPI app: JSON API under /api, static pages for everything else."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from studydesk import __version__
from studydesk.config import Config, ConfigError, load_config
from studydesk.courses import CatalogFile, Course
from studydesk.db import Database
from studydesk.ingest import moodle
from studydesk.jobs import JobQueue

WEB_DIR = Path(__file__).parent / "web"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _hhmm(value) -> str | None:
    return value.strftime("%H:%M") if value else None


MOODLE_SYNC_INTERVAL = timedelta(minutes=30)


def _default_moodle_client(config: Config) -> moodle.MoodleClient | None:
    if not config.moodle_url:
        return None
    token = moodle.get_token(config.moodle_url)
    return moodle.MoodleClient(config.moodle_url, token) if token else None


def create_app(
    config: Config | None = None,
    now: Callable[[], datetime] | None = None,
    moodle_client: Callable[[], moodle.MoodleClient | None] | None = None,
) -> FastAPI:
    config = config or load_config()
    db = Database(config.database_path)
    db.migrate()
    catalog_file = CatalogFile(config.data_root)
    jobs = JobQueue()
    make_moodle_client = moodle_client or (lambda: _default_moodle_client(config))

    app = FastAPI(title="study-desk", version=__version__)
    app.state.config = config
    app.state.db = db
    app.state.catalog = catalog_file
    app.state.jobs = jobs

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

    def moodle_status() -> dict:
        last_sync, last_result = moodle.status(db)
        return {
            "configured": bool(config.moodle_url and config.data_root),
            "running": jobs.busy("moodle-sync"),
            "last_sync": last_sync,
            "last_result": last_result,
        }

    @app.get("/api/sync/moodle")
    def moodle_sync_status() -> dict:
        return moodle_status()

    @app.post("/api/sync/moodle")
    def moodle_sync(force: bool = False) -> dict:
        """Start a sync in the background when the last one is older than 30 minutes."""
        state = moodle_status()
        started = False
        if state["configured"] and not state["running"]:
            last = datetime.fromisoformat(state["last_sync"]) if state["last_sync"] else None
            if force or last is None or datetime.now(timezone.utc) - last >= MOODLE_SYNC_INTERVAL:

                def run() -> None:
                    client = make_moodle_client()
                    if client is None:
                        result = moodle.SyncResult(errors=["moodle_token_missing"])
                    else:
                        result = moodle.sync(db, catalog_file.get(), config.data_root, client)
                    moodle.record(db, result)

                started = jobs.submit("moodle-sync", run)
        return {**moodle_status(), "started": started}

    # Unknown API paths answer in the API's error shape, not as a missing page.
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail="not_found")

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
