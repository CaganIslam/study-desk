"""The glossary: terms captured from explanations and answers, with a status.

- new: seen in an explanation
- hard: the student asked about it (it came up in an answer)
- known: the student said "I know this" on a slide where it came up, or marked it
Known terms are passed to Claude so they are not explained again.
"""

from __future__ import annotations

import re
from pathlib import Path

from studydesk.db import Database
from studydesk.study.commands import fold

STATUSES = ("new", "hard", "known")
KNOWN_LIMIT = 40  # most recent known terms sent with each explanation


def normalise(term: str) -> str:
    """'PLA (Perceptron Learning Algorithm)' and 'pla' share a key; 'valuations' and 'valuation' too."""
    text = re.sub(r"\([^)]*\)", " ", fold(term))
    words = re.findall(r"[a-z0-9]+", text)
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]
    return " ".join(words)


def upsert(db: Database, course_code: str, item: dict, deck_id: int, idx: int, source: str, hard: bool = False) -> int | None:
    name = str(item.get("term", "")).strip()
    key = normalise(name)
    if not key:
        return None
    with db.connect() as conn:
        row = conn.execute("SELECT id, status FROM terms WHERE key = ?", (key,)).fetchone()
        if row is None:
            term_id = conn.execute(
                "INSERT INTO terms (key, term, meaning, definition_en, example, status) VALUES (?, ?, ?, ?, ?, ?)",
                (key, name, item.get("meaning", ""), item.get("definition_en", ""), item.get("example", ""), "hard" if hard else "new"),
            ).lastrowid
        else:
            term_id = row["id"]
            # Fill in what is missing; a question makes a term hard unless the student already knows it.
            conn.execute(
                "UPDATE terms SET meaning = CASE WHEN meaning = '' THEN ? ELSE meaning END,"
                " definition_en = CASE WHEN definition_en = '' THEN ? ELSE definition_en END,"
                " example = CASE WHEN example = '' THEN ? ELSE example END,"
                " status = CASE WHEN ? AND status = 'new' THEN 'hard' ELSE status END, updated_at = datetime('now')"
                " WHERE id = ?",
                (item.get("meaning", ""), item.get("definition_en", ""), item.get("example", ""), int(hard), term_id),
            )
        conn.execute("INSERT OR IGNORE INTO term_courses (term_id, course_code) VALUES (?, ?)", (term_id, course_code))
        conn.execute(
            "INSERT OR IGNORE INTO term_occurrences (term_id, deck_id, idx, source) VALUES (?, ?, ?, ?)",
            (term_id, deck_id, idx, source),
        )
    return term_id


def capture(db: Database, course_code: str, items: list[dict], deck_id: int, idx: int, source: str) -> None:
    for item in items:
        upsert(db, course_code, item, deck_id, idx, source, hard=source == "question")


def mark_slide_known(db: Database, deck_id: int, idx: int) -> int:
    """'I know this' on a slide: its new terms become known. Hard terms stay hard."""
    with db.connect() as conn:
        return conn.execute(
            "UPDATE terms SET status = 'known', updated_at = datetime('now') WHERE status = 'new' AND id IN"
            " (SELECT term_id FROM term_occurrences WHERE deck_id = ? AND idx = ?)",
            (deck_id, idx),
        ).rowcount


def known_list(db: Database, course_code: str, limit: int = KNOWN_LIMIT) -> tuple[str, ...]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.term FROM terms t JOIN term_courses c ON c.term_id = t.id"
            " WHERE c.course_code = ? AND t.status = 'known' ORDER BY t.updated_at DESC LIMIT ?",
            (course_code, limit),
        ).fetchall()
    return tuple(r["term"] for r in rows)


def _courses(conn, term_id: int) -> list[str]:
    return [r["course_code"] for r in conn.execute("SELECT course_code FROM term_courses WHERE term_id = ? ORDER BY course_code", (term_id,))]


def _public(row, courses: list[str]) -> dict:
    return {
        "id": row["id"],
        "term": row["term"],
        "meaning": row["meaning"],
        "definition_en": row["definition_en"],
        "example": row["example"],
        "status": row["status"],
        "courses": courses,
    }


def list_terms(db: Database, course: str | None = None, status: str | None = None, query: str | None = None) -> list[dict]:
    sql = "SELECT DISTINCT t.* FROM terms t JOIN term_courses c ON c.term_id = t.id WHERE 1 = 1"
    params: list = []
    if course:
        sql += " AND c.course_code = ?"
        params.append(course)
    if status:
        sql += " AND t.status = ?"
        params.append(status)
    if query:
        sql += " AND (t.key LIKE ? OR t.meaning LIKE ?)"
        params += [f"%{normalise(query)}%", f"%{query}%"]
    with db.connect() as conn:
        rows = conn.execute(sql + " ORDER BY t.term COLLATE NOCASE", params).fetchall()
        return [_public(r, _courses(conn, r["id"])) for r in rows]


def card(db: Database, term_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM terms WHERE id = ?", (term_id,)).fetchone()
        if row is None:
            return None
        seen = conn.execute(
            "SELECT o.deck_id, o.idx, o.source, s.label, s.title, d.path, d.course_code FROM term_occurrences o"
            " JOIN slides s ON s.deck_id = o.deck_id AND s.idx = o.idx JOIN decks d ON d.id = o.deck_id"
            " WHERE o.term_id = ? ORDER BY d.course_code, d.path, o.idx",
            (term_id,),
        ).fetchall()
        result = _public(row, _courses(conn, term_id))
    result["seen"] = [
        {
            "course": r["course_code"],
            "deck_id": r["deck_id"],
            "deck": Path(r["path"]).stem,
            "idx": r["idx"],
            "label": r["label"],
            "title": r["title"],
            "source": r["source"],
        }
        for r in seen
    ]
    return result


def backfill(db: Database) -> int:
    """Capture terms of explanations and answers made before the glossary existed (startup, once)."""
    import json

    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]:
            return 0
        rows = conn.execute(
            "SELECT e.deck_id, e.idx, e.terms_json, 'explanation' AS source, d.course_code FROM explanations e"
            " JOIN decks d ON d.id = e.deck_id WHERE e.variant = ''"
            " UNION ALL SELECT q.deck_id, q.idx, q.terms_json, 'question', d.course_code FROM questions q"
            " JOIN decks d ON d.id = q.deck_id"
        ).fetchall()
    for row in rows:
        capture(db, row["course_code"], json.loads(row["terms_json"]), row["deck_id"], row["idx"], row["source"])
    return len(rows)


def lookup(db: Database, name: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM terms WHERE key = ?", (normalise(name),)).fetchone()
    return card(db, row["id"]) if row else None


def set_status(db: Database, term_id: int, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError("bad_status")
    with db.connect() as conn:
        return conn.execute(
            "UPDATE terms SET status = ?, updated_at = datetime('now') WHERE id = ?", (status, term_id)
        ).rowcount == 1
