"""The FastAPI app: JSON API under /api, static pages for everything else."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from studydesk import __version__
from studydesk.config import Config, ConfigError, load_config
from studydesk import decks
from studydesk.ai.runner import ClaudeCLI, ClaudeError, Runner
from studydesk.courses import CatalogFile, Course
from studydesk.db import Database
from studydesk.ingest import moodle
from studydesk.jobs import JobQueue
from studydesk.ai.tutor import bar_call
from studydesk.study import commands, explanations, questions
from studydesk.study.prefetch import InFlight, Prefetcher

WEB_DIR = Path(__file__).parent / "web"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _hhmm(value) -> str | None:
    return value.strftime("%H:%M") if value else None


MOODLE_SYNC_INTERVAL = timedelta(minutes=30)
MARKS = {"known"}


class CommandRequest(BaseModel):
    text: str
    deck_id: int | None = None
    idx: int | None = None
    level: str = "normal"


class ExplainRequest(BaseModel):
    level: str = "normal"
    variant: str | None = None
    refresh: bool = False


def _default_moodle_client(config: Config) -> moodle.MoodleClient | None:
    if not config.moodle_url:
        return None
    token = moodle.get_token(config.moodle_url)
    return moodle.MoodleClient(config.moodle_url, token) if token else None


def create_app(
    config: Config | None = None,
    now: Callable[[], datetime] | None = None,
    moodle_client: Callable[[], moodle.MoodleClient | None] | None = None,
    runner: Runner | None = None,
) -> FastAPI:
    config = config or load_config()
    db = Database(config.database_path)
    db.migrate()
    catalog_file = CatalogFile(config.data_root)
    jobs = JobQueue()
    make_moodle_client = moodle_client or (lambda: _default_moodle_client(config))
    runner = runner or ClaudeCLI(cwd=config.app_home)

    app = FastAPI(title="study-desk", version=__version__)
    app.state.config = config
    app.state.db = db
    app.state.catalog = catalog_file
    app.state.jobs = jobs
    app.state.runner = runner

    def clock() -> datetime:
        return now() if now else datetime.now(catalog_file.get().timezone)

    def has_syllabus(course: Course) -> bool:
        return bool(config.data_root and course.syllabus and (config.data_root / course.folder / course.syllabus).exists())

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = exc.detail if isinstance(exc.detail, str) else "error"
        return _error(exc.status_code, code, code.replace("_", " "))

    @app.exception_handler(ClaudeError)
    async def claude_error(_: Request, exc: ClaudeError) -> JSONResponse:
        return _error(503, exc.code, str(exc))

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
                    if result.new or result.updated:
                        decks.scan(db, catalog_file.get(), config.data_root)

                started = jobs.submit("moodle-sync", run)
        return {**moodle_status(), "started": started}

    slide_cache = config.app_home / "cache" / "slides"

    def course_or_404(code: str) -> Course:
        course = catalog_file.get().by_code(code)
        if course is None:
            raise HTTPException(status_code=404, detail="course_not_found")
        return course

    def deck_or_404(deck_id: int):
        deck = decks.get_deck(db, deck_id)
        if deck is None:
            raise HTTPException(status_code=404, detail="deck_not_found")
        return deck

    def slide_or_404(deck_id: int, idx: int):
        slide = decks.get_slide(db, deck_id, idx)
        if slide is None:
            raise HTTPException(status_code=404, detail="slide_not_found")
        return slide

    @app.get("/api/courses/{code}/decks")
    def course_decks(code: str) -> dict:
        course = course_or_404(code)
        if config.data_root:
            decks.scan(db, catalog_file.get(), config.data_root, course.code)
        return {"code": course.code, "decks": decks.list_decks(db, course.code)}

    @app.get("/api/decks/{deck_id}/slides")
    def deck_slides(deck_id: int) -> dict:
        deck = deck_or_404(deck_id)
        marks = explanations.marks(db, deck_id)
        explained = explanations.explained(db, deck_id)
        asked = questions.counts(db, deck_id)
        return {
            "deck": {"id": deck["id"], "code": deck["course_code"], "filename": Path(deck["path"]).name},
            "slides": [
                {
                    "idx": s["idx"],
                    "label": s["label"],
                    "title": s["title"],
                    "marks": marks.get(s["idx"], []),
                    "explained": s["idx"] in explained,
                    "questions": asked.get(s["idx"], 0),
                }
                for s in decks.get_slides(db, deck_id)
            ],
        }

    @app.get("/api/decks/{deck_id}/find")
    def find_slide(deck_id: int, label: str) -> dict:
        """The slide the lecturer calls `label` (the footer number), else the one at that position."""
        deck_or_404(deck_id)
        slides = decks.get_slides(db, deck_id)
        match = next((s for s in slides if s["label"] == label.strip()), None)
        if match is None and label.strip().isdigit():
            match = next((s for s in slides if s["idx"] == int(label)), None)
        if match is None:
            raise HTTPException(status_code=404, detail="slide_not_found")
        return {"idx": match["idx"], "label": match["label"]}

    @app.get("/api/decks/{deck_id}/slides/{idx}")
    def slide_detail(deck_id: int, idx: int) -> dict:
        deck_or_404(deck_id)
        slide = slide_or_404(deck_id, idx)
        total = len(decks.get_slides(db, deck_id))
        return {
            "idx": slide["idx"],
            "label": slide["label"],
            "title": slide["title"],
            "text": slide["text"],
            "pages": [slide["first_page"] + 1, slide["last_page"] + 1],
            "total": total,
            "prev": idx - 1 if idx > 1 else None,
            "next": idx + 1 if idx < total else None,
        }

    @app.get("/api/decks/{deck_id}/slides/{idx}/image")
    def slide_image(deck_id: int, idx: int, size: str = "view") -> FileResponse:
        deck = deck_or_404(deck_id)
        slide = slide_or_404(deck_id, idx)
        if size not in decks.SIZES:
            raise HTTPException(status_code=400, detail="bad_size")
        return FileResponse(decks.render(deck, slide, size, slide_cache), media_type="image/png")

    inflight = InFlight()

    def explainer() -> explanations.Explainer:
        return explanations.Explainer(
            db, catalog_file.get(), app.state.runner, slide_cache, config.language, config.model_default, inflight
        )

    prefetcher = Prefetcher(jobs, explainer)
    app.state.prefetcher = prefetcher

    @app.post("/api/decks/{deck_id}/slides/{idx}/explain")
    def explain(deck_id: int, idx: int, request: ExplainRequest) -> dict:
        deck_or_404(deck_id)
        slide_or_404(deck_id, idx)
        try:
            result = explainer().explain(deck_id, idx, request.level, request.variant, request.refresh)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad_level_or_variant") from None
        if request.variant is None and idx < len(decks.get_slides(db, deck_id)):
            prefetcher.want(deck_id, idx + 1, request.level)
        return result.as_dict()

    @app.put("/api/decks/{deck_id}/slides/{idx}/marks/{mark}")
    def add_mark(deck_id: int, idx: int, mark: str) -> dict:
        return _change_mark(deck_id, idx, mark, True)

    @app.delete("/api/decks/{deck_id}/slides/{idx}/marks/{mark}")
    def remove_mark(deck_id: int, idx: int, mark: str) -> dict:
        return _change_mark(deck_id, idx, mark, False)

    def _change_mark(deck_id: int, idx: int, mark: str, on: bool) -> dict:
        deck_or_404(deck_id)
        slide_or_404(deck_id, idx)
        if mark not in MARKS:
            raise HTTPException(status_code=400, detail="bad_mark")
        explanations.set_mark(db, deck_id, idx, mark, on)
        return {"idx": idx, "marks": explanations.marks(db, deck_id).get(idx, [])}

    @app.get("/api/decks/{deck_id}/slides/{idx}/questions")
    def slide_questions(deck_id: int, idx: int) -> dict:
        deck_or_404(deck_id)
        slide_or_404(deck_id, idx)
        return {"idx": idx, "questions": questions.for_slide(db, deck_id, idx)}

    def resolve_action(action: dict) -> dict:
        """Turn a parsed or Claude-chosen action into something the page can do directly."""
        kind = action.get("type")
        if kind == "open":
            course = catalog_file.get().by_code(action.get("course") or "")
            if course is None:
                return {"type": "none"}
            resolved = {"type": "open", "course": course.code, "deck_id": None, "idx": 1}
            if action.get("lecture") and config.data_root:
                decks.scan(db, catalog_file.get(), config.data_root, course.code)
                deck = commands.resolve_deck(action["lecture"], decks.list_decks(db, course.code), course.code)
                if deck:
                    resolved["deck_id"] = deck["id"]
            return resolved
        allowed = {"next", "prev", "goto_slide", "set_level", "variant", "know_skip", "home"}
        if kind not in allowed:
            return {"type": "none"}
        return {k: v for k, v in action.items() if k in {"type", "label", "level", "variant"} and v}

    @app.post("/api/command")
    def command(request: CommandRequest) -> dict:
        text = request.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="empty")
        catalog = catalog_file.get()
        deck = decks.get_deck(db, request.deck_id) if request.deck_id else None
        current = catalog.by_code(deck["course_code"]) if deck else None

        parsed = commands.parse(text, catalog, current)
        if parsed is not None:
            return {"kind": "action", "action": resolve_action(parsed.as_dict()), "source": "local"}

        # "14. slayttayız, hoca X diyor, ne o?": go to slide 14, then answer about it.
        idx, moved = request.idx, None
        position, question = commands.split_position(text)
        if position and deck:
            slide = next((s for s in decks.get_slides(db, deck["id"]) if s["label"] == position), None)
            if slide:
                idx, moved = slide["idx"], {"type": "goto_slide", "label": position}
        ctx = explainer().context(deck["id"], idx) if deck and idx else None
        thread = questions.thread(db, deck["id"], idx) if ctx else ()
        level = request.level if request.level in {"short", "normal", "detailed"} else "normal"
        course_list = tuple((c.code, c.name, c.aliases) for c in catalog.courses)
        data = app.state.runner.run(
            bar_call(ctx, question, course_list, thread, level=level, language=config.language, model=config.model_default)
        ).data

        action = data.get("action") or {}
        if data.get("kind") == "action" and action.get("type") not in (None, "none"):
            return {"kind": "action", "action": resolve_action(action), "source": "claude"}
        answer = {"question": question, "answer_md": str(data.get("answer_md", "")), "terms": list(data.get("terms", []))}
        if ctx:
            answer["id"] = questions.add(db, deck["id"], idx, question, answer["answer_md"], answer["terms"])
        return {"kind": "answer", "answer": answer, "action": moved, "idx": idx, "source": "claude"}

    # Unknown API paths answer in the API's error shape, not as a missing page.
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail="not_found")

    @app.middleware("http")
    async def revalidate_pages(request: Request, call_next):
        # Pages and scripts are revalidated on every load, so an update is never hidden by the browser cache.
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
