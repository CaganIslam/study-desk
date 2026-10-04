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
from studydesk.study import commands, explanations, questions, sessions, terms
from studydesk.study.prefetch import InFlight, Prefetcher

WEB_DIR = Path(__file__).parent / "web"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _hhmm(value) -> str | None:
    return value.strftime("%H:%M") if value else None


MOODLE_SYNC_INTERVAL = timedelta(minutes=30)
MOODLE_SYNC_INTERVAL_LIVE = timedelta(minutes=3)  # a lecturer may upload the deck during the class
LIVE_MODEL = "sonnet"  # used in live mode when config.toml sets no [models] live
MARKS = {"known"}


class CommandRequest(BaseModel):
    text: str
    deck_id: int | None = None
    idx: int | None = None
    level: str = "normal"
    course_code: str | None = None  # live mode without a deck
    live: bool = False


class TermUpdate(BaseModel):
    status: str


class ActivityRequest(BaseModel):
    deck_id: int
    idx: int


class ExplainRequest(BaseModel):
    level: str = "normal"
    variant: str | None = None
    refresh: bool = False
    live: bool = False


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
    sessions.backfill_index(db)
    terms.backfill(db)
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
    def moodle_sync(force: bool = False, live: bool = False) -> dict:
        """Start a sync in the background when the last one is older than 30 minutes (3 in live mode)."""
        schedule_notes()  # opening the app is a good moment to write notes of finished sessions
        state = moodle_status()
        started = False
        if state["configured"] and not state["running"]:
            last = datetime.fromisoformat(state["last_sync"]) if state["last_sync"] else None
            interval = MOODLE_SYNC_INTERVAL_LIVE if live else MOODLE_SYNC_INTERVAL
            if force or last is None or datetime.now(timezone.utc) - last >= interval:

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

    def explainer(live: bool = False) -> explanations.Explainer:
        model = (config.model_live or LIVE_MODEL) if live else config.model_default
        return explanations.Explainer(db, catalog_file.get(), app.state.runner, slide_cache, config.language, model, inflight)

    prefetcher = Prefetcher(jobs, explainer)
    app.state.prefetcher = prefetcher

    @app.post("/api/decks/{deck_id}/slides/{idx}/explain")
    def explain(deck_id: int, idx: int, request: ExplainRequest) -> dict:
        deck_or_404(deck_id)
        slide_or_404(deck_id, idx)
        try:
            result = explainer(request.live).explain(deck_id, idx, request.level, request.variant, request.refresh)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad_level_or_variant") from None
        if request.variant is None and idx < len(decks.get_slides(db, deck_id)):
            prefetcher.want(deck_id, idx + 1, request.level, request.live)
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
        if mark == "known" and on:
            terms.mark_slide_known(db, deck_id, idx)
        return {"idx": idx, "marks": explanations.marks(db, deck_id).get(idx, [])}

    def sessions_of_day(day: date | None) -> list[dict]:
        catalog = catalog_file.get()
        day = day or clock().astimezone(catalog.timezone).date()
        start = datetime.combine(day, datetime.min.time(), catalog.timezone)
        found = sessions.sessions(db, since=start.astimezone(timezone.utc), until=(start + timedelta(days=1)).astimezone(timezone.utc))
        return [sessions.describe(db, s) for s in found]

    def schedule_notes() -> None:
        if config.data_root:
            jobs.submit("session-notes", lambda: sessions.write_due_notes(db, catalog_file.get(), config.data_root))

    app.state.schedule_notes = schedule_notes

    @app.post("/api/activity")
    def activity(request: ActivityRequest) -> dict:
        deck_or_404(request.deck_id)
        slide_or_404(request.deck_id, request.idx)
        sessions.record_view(db, request.deck_id, request.idx)
        return {"ok": True}

    @app.get("/api/resume")
    def resume_point(course: str | None = None) -> dict:
        return {"resume": sessions.resume(db, course)}

    @app.get("/api/sessions")
    def day_sessions(day: date | None = None) -> dict:
        schedule_notes()
        return {"day": (day or clock().astimezone(catalog_file.get().timezone).date()).isoformat(), "sessions": sessions_of_day(day)}

    def live_target(course_code: str | None) -> dict:
        """What live mode should open: the class running now (or a chosen course), its newest deck."""
        catalog = catalog_file.get()
        current = catalog.current(clock())
        course = catalog.by_code(course_code) if course_code else (current.course if current else None)
        if course is None:
            return {"current": None, "course": None, "deck_id": None, "idx": None}
        if config.data_root:
            decks.scan(db, catalog, config.data_root, course.code)
        with db.connect() as conn:
            newest = conn.execute(
                "SELECT id FROM decks WHERE course_code = ? AND path NOT LIKE '%yllabus%' ORDER BY mtime DESC LIMIT 1",
                (course.code,),
            ).fetchone()
        deck_id, idx = (newest["id"], 1) if newest else (None, None)
        last = sessions.resume(db, course.code)
        if newest and last and last["deck_id"] == deck_id:
            idx = last["idx"]
        return {
            "current": {"code": current.course.code, "start": _hhmm(current.start), "end": _hhmm(current.end)} if current else None,
            "course": course.code,
            "deck_id": deck_id,
            "idx": idx,
        }

    @app.get("/api/live")
    def live(course: str | None = None) -> dict:
        return live_target(course)

    @app.get("/api/courses/{code}/deckless")
    def deckless_questions(code: str) -> dict:
        course_or_404(code)
        catalog = catalog_file.get()
        start = datetime.combine(clock().astimezone(catalog.timezone).date(), datetime.min.time(), catalog.timezone)
        since = start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return {"code": code, "questions": questions.deckless(db, code, since)}

    @app.get("/api/overview")
    def overview() -> dict:
        today_sessions = sessions_of_day(None)
        return {
            "courses": sessions.course_overview(db, catalog_file.get()),
            "resume": sessions.resume(db),
            "studied_minutes_today": sum(s["minutes"] for s in today_sessions),
        }

    @app.get("/api/search")
    def search(q: str) -> dict:
        return {"q": q, "results": sessions.search(db, q)}

    @app.get("/api/terms")
    def term_list(course: str | None = None, status: str | None = None, q: str | None = None) -> dict:
        if status and status not in terms.STATUSES:
            raise HTTPException(status_code=400, detail="bad_status")
        return {"terms": terms.list_terms(db, course, status, q)}

    @app.get("/api/terms/lookup")
    def term_lookup(term: str) -> dict:
        found = terms.lookup(db, term)
        if found is None:
            raise HTTPException(status_code=404, detail="term_not_found")
        return found

    @app.get("/api/terms/{term_id}")
    def term_card(term_id: int) -> dict:
        found = terms.card(db, term_id)
        if found is None:
            raise HTTPException(status_code=404, detail="term_not_found")
        return found

    @app.patch("/api/terms/{term_id}")
    def term_update(term_id: int, update: TermUpdate) -> dict:
        try:
            changed = terms.set_status(db, term_id, update.status)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad_status") from None
        if not changed:
            raise HTTPException(status_code=404, detail="term_not_found")
        return terms.card(db, term_id)

    @app.get("/api/decks/{deck_id}/slides/{idx}/questions")
    def slide_questions(deck_id: int, idx: int) -> dict:
        deck_or_404(deck_id)
        slide_or_404(deck_id, idx)
        return {"idx": idx, "questions": questions.for_slide(db, deck_id, idx)}

    def resolve_action(action: dict) -> dict:
        """Turn a parsed or Claude-chosen action into something the page can do directly."""
        kind = action.get("type")
        if kind == "resume":
            last = sessions.resume(db)
            return {"type": "open", "course": last["course"], "deck_id": last["deck_id"], "idx": last["idx"]} if last else {"type": "none"}
        if kind == "today_summary":
            return {"type": "today_summary", "sessions": sessions_of_day(None)}
        if kind == "search":
            query = (action.get("query") or "").strip()
            return {"type": "search", "query": query, "results": sessions.search(db, query)}
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
                    last = sessions.resume(db, course.code)
                    if last and last["deck_id"] == deck["id"]:
                        resolved["idx"] = last["idx"]
            elif not action.get("lecture"):
                last = sessions.resume(db, course.code)
                if last:
                    resolved.update(deck_id=last["deck_id"], idx=last["idx"])
            return resolved
        allowed = {"next", "prev", "goto_slide", "set_level", "variant", "know_skip", "home", "live"}
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
        live_course = catalog.by_code(request.course_code) if request.course_code and not deck else None
        course_line = (
            f"Course: {live_course.code} {live_course.name}. The student is in the lecture right now; its slides are not available."
            if live_course
            else None
        )
        model = (config.model_live or LIVE_MODEL) if request.live else config.model_default
        data = app.state.runner.run(
            bar_call(ctx, question, course_list, thread, level=level, language=config.language, model=model, course_line=course_line)
        ).data

        action = data.get("action") or {}
        if data.get("kind") == "action" and action.get("type") not in (None, "none"):
            return {"kind": "action", "action": resolve_action(action), "source": "claude"}
        answer = {"question": question, "answer_md": str(data.get("answer_md", "")), "terms": list(data.get("terms", []))}
        if ctx:
            answer["id"] = questions.add(
                db, deck["id"], idx, question, answer["answer_md"], answer["terms"], deck["course_code"]
            )
            terms.capture(db, deck["course_code"], answer["terms"], deck["id"], idx, "question")
        elif live_course:
            answer["id"] = questions.add_deckless(db, live_course.code, question, answer["answer_md"], answer["terms"])
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
