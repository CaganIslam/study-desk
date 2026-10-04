"""Study activity: resume points, sessions, session notes and search.

Sessions are not opened and closed by the browser; they are derived from slide
views: views of one course with gaps shorter than 30 minutes form a session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from studydesk import decks
from studydesk.courses import Catalog
from studydesk.db import Database
from studydesk.study.commands import fold

SESSION_GAP = timedelta(minutes=30)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def record_view(db: Database, deck_id: int, idx: int, at: datetime | None = None) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO activity (deck_id, idx, kind, at) VALUES (?, ?, 'view', ?)",
            (deck_id, idx, (at or now_utc()).isoformat(timespec="seconds")),
        )


def resume(db: Database, course_code: str | None = None) -> dict | None:
    """The last slide viewed, in one course or anywhere."""
    query = (
        "SELECT a.deck_id, a.idx, a.at, d.course_code, d.path, s.label, s.title FROM activity a"
        " JOIN decks d ON d.id = a.deck_id JOIN slides s ON s.deck_id = a.deck_id AND s.idx = a.idx"
    )
    params: tuple = ()
    if course_code:
        query += " WHERE d.course_code = ?"
        params = (course_code,)
    with db.connect() as conn:
        row = conn.execute(query + " ORDER BY a.at DESC, a.id DESC LIMIT 1", params).fetchone()
    if row is None:
        return None
    return {
        "course": row["course_code"],
        "deck_id": row["deck_id"],
        "deck": Path(row["path"]).stem,
        "idx": row["idx"],
        "label": row["label"],
        "title": row["title"],
        "at": row["at"],
    }


@dataclass
class Session:
    course: str
    start: datetime
    end: datetime
    views: list[tuple[int, int]] = field(default_factory=list)  # (deck_id, idx) in order

    @property
    def minutes(self) -> int:
        return max(1, round((self.end - self.start).total_seconds() / 60))


def sessions(db: Database, since: datetime | None = None, until: datetime | None = None) -> list[Session]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT a.deck_id, a.idx, a.at, d.course_code FROM activity a JOIN decks d ON d.id = a.deck_id"
            " WHERE a.at >= ? AND a.at < ? ORDER BY a.at, a.id",
            (
                (since or datetime(1970, 1, 1, tzinfo=timezone.utc)).isoformat(timespec="seconds"),
                (until or datetime(9999, 1, 1, tzinfo=timezone.utc)).isoformat(timespec="seconds"),
            ),
        ).fetchall()
    result: list[Session] = []
    for row in rows:
        at = datetime.fromisoformat(row["at"])
        last = result[-1] if result else None
        if last and last.course == row["course_code"] and at - last.end < SESSION_GAP:
            last.end = at
        else:
            last = Session(row["course_code"], at, at)
            result.append(last)
        if not last.views or last.views[-1] != (row["deck_id"], row["idx"]):
            last.views.append((row["deck_id"], row["idx"]))
    return result


def describe(db: Database, session: Session) -> dict:
    """Slides, known marks, questions and exam notes of one session, for the notes file and the API."""
    deck_ids = sorted({d for d, _ in session.views})
    slides, known, asked, exam_notes, terms = [], [], [], [], {}
    lo, hi = session.start.isoformat(timespec="seconds"), (session.end + timedelta(seconds=1)).isoformat(timespec="seconds")
    with db.connect() as conn:
        for deck_id, idx in session.views:
            row = conn.execute("SELECT label, title FROM slides WHERE deck_id = ? AND idx = ?", (deck_id, idx)).fetchone()
            if row and (deck_id, row["label"], row["title"]) not in [(s["deck_id"], s["label"], s["title"]) for s in slides]:
                slides.append({"deck_id": deck_id, "label": row["label"], "title": row["title"]})
            explanation = conn.execute(
                "SELECT terms_json, exam_notes_json FROM explanations WHERE deck_id = ? AND idx = ? AND variant = ''"
                " ORDER BY created_at DESC LIMIT 1",
                (deck_id, idx),
            ).fetchone()
            if explanation:
                for note in json.loads(explanation["exam_notes_json"]):
                    if note not in exam_notes:
                        exam_notes.append(note)
                for term in json.loads(explanation["terms_json"]):
                    terms.setdefault(term["term"], term)
        for deck_id in deck_ids:
            known += [
                r["label"]
                for r in conn.execute(
                    "SELECT s.label FROM slide_marks m JOIN slides s ON s.deck_id = m.deck_id AND s.idx = m.idx"
                    " WHERE m.deck_id = ? AND m.mark = 'known' AND m.created_at BETWEEN datetime(?) AND datetime(?)",
                    (deck_id, lo, hi),
                )
            ]
            asked += [
                {"label": r["label"], "question": r["question"], "answer_md": r["answer_md"]}
                for r in conn.execute(
                    "SELECT s.label, q.question, q.answer_md FROM questions q JOIN slides s ON s.deck_id = q.deck_id AND s.idx = q.idx"
                    " WHERE q.deck_id = ? AND q.created_at BETWEEN datetime(?) AND datetime(?) ORDER BY q.id",
                    (deck_id, lo, hi),
                )
            ]
    deck_names = []
    for deck_id in deck_ids:
        deck = decks.get_deck(db, deck_id)
        if deck:
            deck_names.append(Path(deck["path"]).stem)
    return {
        "course": session.course,
        "start": session.start.isoformat(timespec="seconds"),
        "end": session.end.isoformat(timespec="seconds"),
        "minutes": session.minutes,
        "decks": deck_names,
        "slides": slides,
        "known": known,
        "questions": asked,
        "exam_notes": exam_notes,
        "terms": list(terms.values()),
    }


def _first_sentence(markdown: str) -> str:
    text = " ".join(markdown.split())
    for end in (". ", "? ", "! "):
        if end in text:
            return text[: text.index(end) + 1]
    return text[:240]


def note_markdown(info: dict, course_name: str, tz) -> str:
    start = datetime.fromisoformat(info["start"]).astimezone(tz)
    end = datetime.fromisoformat(info["end"]).astimezone(tz)
    lines = [
        f"# {info['course']} {course_name} - {start:%Y-%m-%d}",
        "",
        f"{start:%H:%M}-{end:%H:%M} ({info['minutes']} dk) · {', '.join(info['decks'])}",
        "",
        "## Slaytlar",
        "",
    ]
    lines += [f"- {s['label']}. {s['title']}" + (" ✓" if s["label"] in info["known"] else "") for s in info["slides"]]
    if info["questions"]:
        lines += ["", "## Sorular", ""]
        lines += [f"- **{q['question']}** ({q['label']}. slayt) {_first_sentence(q['answer_md'])}" for q in info["questions"]]
    if info["exam_notes"]:
        lines += ["", "## Sınav notları", ""] + [f"- {n}" for n in info["exam_notes"]]
    if info["terms"]:
        lines += ["", "## Terimler", ""] + [f"- **{t['term']}** - {t['meaning']}: {t['definition_en']}" for t in info["terms"]]
    return "\n".join(lines) + "\n"


def course_overview(db: Database, catalog: Catalog) -> list[dict]:
    """Per course: when it was last studied, how many slides were viewed, and the glossary counts."""
    with db.connect() as conn:
        last = {
            r["course_code"]: r["at"]
            for r in conn.execute(
                "SELECT d.course_code, MAX(a.at) AS at FROM activity a JOIN decks d ON d.id = a.deck_id GROUP BY d.course_code"
            )
        }
        viewed = {
            r["course_code"]: r["n"]
            for r in conn.execute(
                "SELECT d.course_code, COUNT(DISTINCT a.deck_id || ':' || a.idx) AS n FROM activity a"
                " JOIN decks d ON d.id = a.deck_id GROUP BY d.course_code"
            )
        }
        counts: dict[str, dict[str, int]] = {}
        for r in conn.execute(
            "SELECT c.course_code, t.status, COUNT(*) AS n FROM terms t JOIN term_courses c ON c.term_id = t.id"
            " GROUP BY c.course_code, t.status"
        ):
            counts.setdefault(r["course_code"], {})[r["status"]] = r["n"]
    return [
        {
            "code": c.code,
            "name": c.name,
            "last_studied": last.get(c.code),
            "slides_viewed": viewed.get(c.code, 0),
            "hard_terms": counts.get(c.code, {}).get("hard", 0),
            "known_terms": counts.get(c.code, {}).get("known", 0),
        }
        for c in catalog.courses
    ]


def write_due_notes(db: Database, catalog: Catalog, data_root: Path, now: datetime | None = None) -> list[Path]:
    """Write a notes file for every finished session (no activity for 30 minutes) that has none yet."""
    now = now or now_utc()
    written = []
    for session in sessions(db):
        if now - session.end < SESSION_GAP:
            continue
        key = (session.course, session.start.isoformat(timespec="seconds"))
        with db.connect() as conn:
            if conn.execute("SELECT 1 FROM session_notes WHERE course_code = ? AND started_at = ?", key).fetchone():
                continue
        course = catalog.by_code(session.course)
        if course is None:
            continue
        local_start = session.start.astimezone(catalog.timezone)
        path = data_root / course.folder / "notes" / f"{local_start:%Y-%m-%d-%H%M}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note_markdown(describe(db, session), course.name, catalog.timezone), encoding="utf-8")
        with db.connect() as conn:
            conn.execute("INSERT INTO session_notes (course_code, started_at, path) VALUES (?, ?, ?)", (*key, str(path)))
        written.append(path)
    return written


# --- search ----------------------------------------------------------------------


def index(db: Database, kind: str, deck_id: int, idx: int, course_code: str, title: str, body: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM search_index WHERE kind = ? AND deck_id = ? AND idx = ? AND title = ?",
            (kind, deck_id, idx, title),
        )
        conn.execute(
            "INSERT INTO search_index (kind, deck_id, idx, course_code, title, body) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, deck_id, idx, course_code, title, fold(f"{title}\n{body}")),
        )


def backfill_index(db: Database) -> int:
    """Index explanations and questions made before search existed. Runs at startup; cheap when nothing is missing."""
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM search_index").fetchone()[0]:
            return 0
        explanations = conn.execute(
            "SELECT e.deck_id, e.idx, e.explanation_md, e.exam_notes_json, e.terms_json, d.course_code, s.title"
            " FROM explanations e JOIN decks d ON d.id = e.deck_id JOIN slides s ON s.deck_id = e.deck_id AND s.idx = e.idx"
            " WHERE e.variant = ''"
        ).fetchall()
        asked = conn.execute(
            "SELECT q.deck_id, q.idx, q.question, q.answer_md, d.course_code FROM questions q JOIN decks d ON d.id = q.deck_id"
        ).fetchall()
    for row in explanations:
        notes = " ".join(json.loads(row["exam_notes_json"]))
        terms = " ".join(f"{t.get('term', '')} {t.get('meaning', '')}" for t in json.loads(row["terms_json"]))
        index(db, "explanation", row["deck_id"], row["idx"], row["course_code"], row["title"], f"{row['explanation_md']}\n{notes}\n{terms}")
    for row in asked:
        index(db, "question", row["deck_id"], row["idx"], row["course_code"], row["question"], row["answer_md"])
    return len(explanations) + len(asked)


def search(db: Database, query: str, limit: int = 20) -> list[dict]:
    words = [w for w in fold(query).replace('"', " ").split() if w]
    if not words:
        return []
    match = " ".join(f'"{w}"*' for w in words)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT si.kind, si.deck_id, si.idx, si.course_code, si.title,"
            " snippet(search_index, 5, '[', ']', '…', 12) AS snippet, s.label"
            " FROM search_index si JOIN slides s ON s.deck_id = si.deck_id AND s.idx = si.idx"
            " WHERE search_index MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        ).fetchall()
    return [dict(r) for r in rows]
