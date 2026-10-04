"""Explanations of slides, made by Claude once and then served from the database."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from studydesk import decks
from studydesk.ai.runner import Runner
from studydesk.ai.tutor import LEVELS, VARIANTS, SlideContext, explain_call
from studydesk.courses import Catalog
from studydesk.db import Database
from studydesk.study import sessions, terms
from studydesk.study.prefetch import InFlight


class NotFound(LookupError):
    pass


@dataclass(frozen=True)
class Explanation:
    deck_id: int
    idx: int
    level: str
    variant: str | None
    explanation_md: str
    summary: str
    terms: list[dict]
    exam_notes: list[str]
    cached: bool

    def as_dict(self) -> dict:
        return {
            "idx": self.idx,
            "level": self.level,
            "variant": self.variant,
            "explanation_md": self.explanation_md,
            "summary": self.summary,
            "terms": self.terms,
            "exam_notes": self.exam_notes,
            "cached": self.cached,
        }


def _row_to_explanation(row, cached: bool) -> Explanation:
    return Explanation(
        deck_id=row["deck_id"],
        idx=row["idx"],
        level=row["level"],
        variant=row["variant"] or None,
        explanation_md=row["explanation_md"],
        summary=row["summary"],
        terms=json.loads(row["terms_json"]),
        exam_notes=json.loads(row["exam_notes_json"]),
        cached=cached,
    )


class Explainer:
    def __init__(
        self,
        db: Database,
        catalog: Catalog,
        runner: Runner,
        cache_dir: Path,
        language: str,
        model: str | None = None,
        inflight: InFlight | None = None,
    ) -> None:
        self.inflight = inflight or InFlight()
        self.db = db
        self.catalog = catalog
        self.runner = runner
        self.cache_dir = cache_dir
        self.language = language
        self.model = model

    def cached(self, deck_id: int, idx: int, level: str, variant: str | None = None) -> Explanation | None:
        deck = decks.get_deck(self.db, deck_id)
        if deck is None:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM explanations WHERE deck_id = ? AND idx = ? AND level = ? AND variant = ? AND language = ? AND deck_sha = ?",
                (deck_id, idx, level, variant or "", self.language, deck["sha256"]),
            ).fetchone()
        return _row_to_explanation(row, cached=True) if row else None

    def _previous_summary(self, deck_id: int, idx: int) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT summary FROM explanations WHERE deck_id = ? AND idx = ? AND language = ? AND variant = ''"
                " ORDER BY created_at DESC LIMIT 1",
                (deck_id, idx - 1, self.language),
            ).fetchone()
        return row["summary"] if row else None

    def known_terms(self, course_code: str) -> tuple[str, ...]:
        return terms.known_list(self.db, course_code)

    def context(self, deck_id: int, idx: int, today: date | None = None) -> SlideContext:
        deck = decks.get_deck(self.db, deck_id)
        slide = decks.get_slide(self.db, deck_id, idx) if deck else None
        if deck is None or slide is None:
            raise NotFound("slide_not_found")
        course = self.catalog.by_code(deck["course_code"])
        total = len(decks.get_slides(self.db, deck_id))
        topic = course.topic_for(today or date.today()) if course else None
        return SlideContext(
            course_code=deck["course_code"],
            course_name=course.name if course else deck["course_code"],
            deck=Path(deck["path"]).name,
            label=slide["label"],
            idx=idx,
            total=total,
            title=slide["title"],
            text=slide["text"],
            image=decks.render(deck, slide, "ai", self.cache_dir),
            week_topic=topic.title if topic else None,
            previous_summary=self._previous_summary(deck_id, idx),
            known_terms=self.known_terms(deck["course_code"]),
        )

    def explain(
        self, deck_id: int, idx: int, level: str = "normal", variant: str | None = None, refresh: bool = False
    ) -> Explanation:
        if level not in LEVELS or (variant is not None and variant not in VARIANTS):
            raise ValueError("bad_level_or_variant")
        if not refresh:
            hit = self.cached(deck_id, idx, level, variant)
            if hit:
                return hit
        key = f"{deck_id}:{idx}:{level}:{variant or ''}:{self.language}"
        for _ in range(2):
            ran, result = self.inflight.run_once(key, lambda: self._generate(deck_id, idx, level, variant))
            if ran:
                return result
            hit = self.cached(deck_id, idx, level, variant)  # another thread just made it
            if hit:
                return hit
        return self._generate(deck_id, idx, level, variant)  # the other thread failed; try ourselves

    def _generate(self, deck_id: int, idx: int, level: str, variant: str | None) -> Explanation:
        ctx = self.context(deck_id, idx)
        if variant == "different":
            base = self.cached(deck_id, idx, level) or self.cached(deck_id, idx, "normal")
            if base:
                ctx = SlideContext(**{**ctx.__dict__, "previous_explanation": base.explanation_md})
        result = self.runner.run(explain_call(ctx, level=level, variant=variant, language=self.language, model=self.model))
        data = result.data
        deck = decks.get_deck(self.db, deck_id)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO explanations (deck_id, idx, level, variant, language, deck_sha, explanation_md, summary, terms_json, exam_notes_json, duration_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (deck_id, idx, level, variant, language) DO UPDATE SET deck_sha = excluded.deck_sha,"
                " explanation_md = excluded.explanation_md, summary = excluded.summary, terms_json = excluded.terms_json,"
                " exam_notes_json = excluded.exam_notes_json, duration_ms = excluded.duration_ms, created_at = datetime('now')",
                (
                    deck_id,
                    idx,
                    level,
                    variant or "",
                    self.language,
                    deck["sha256"],
                    str(data.get("explanation_md", "")),
                    str(data.get("summary", "")),
                    json.dumps(data.get("terms", []), ensure_ascii=False),
                    json.dumps(data.get("exam_notes", []), ensure_ascii=False),
                    result.duration_ms,
                ),
            )
        terms.capture(self.db, deck["course_code"], list(data.get("terms", [])), deck_id, idx, "explanation")
        notes = " ".join(data.get("exam_notes", []))
        words = " ".join(f"{t.get('term', '')} {t.get('meaning', '')}" for t in data.get("terms", []))
        sessions.index(
            self.db, "explanation", deck_id, idx, deck["course_code"], ctx.title,
            f"{data.get('explanation_md', '')}\n{notes}\n{words}",
        )  # fmt: skip
        return Explanation(
            deck_id=deck_id,
            idx=idx,
            level=level,
            variant=variant,
            explanation_md=str(data.get("explanation_md", "")),
            summary=str(data.get("summary", "")),
            terms=list(data.get("terms", [])),
            exam_notes=list(data.get("exam_notes", [])),
            cached=False,
        )


def set_mark(db: Database, deck_id: int, idx: int, mark: str, on: bool = True) -> None:
    with db.connect() as conn:
        if on:
            conn.execute("INSERT OR IGNORE INTO slide_marks (deck_id, idx, mark) VALUES (?, ?, ?)", (deck_id, idx, mark))
        else:
            conn.execute("DELETE FROM slide_marks WHERE deck_id = ? AND idx = ? AND mark = ?", (deck_id, idx, mark))


def marks(db: Database, deck_id: int) -> dict[int, list[str]]:
    with db.connect() as conn:
        rows = conn.execute("SELECT idx, mark FROM slide_marks WHERE deck_id = ? ORDER BY idx", (deck_id,)).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(row["idx"], []).append(row["mark"])
    return result


def explained(db: Database, deck_id: int) -> set[int]:
    with db.connect() as conn:
        return {row["idx"] for row in conn.execute("SELECT DISTINCT idx FROM explanations WHERE deck_id = ?", (deck_id,))}
