"""Questions asked about a slide, kept with their answers."""

from __future__ import annotations

import json

from studydesk.ai.tutor import Exchange
from studydesk.db import Database


def add(db: Database, deck_id: int, idx: int, question: str, answer_md: str, terms: list[dict]) -> int:
    with db.connect() as conn:
        return conn.execute(
            "INSERT INTO questions (deck_id, idx, question, answer_md, terms_json) VALUES (?, ?, ?, ?, ?)",
            (deck_id, idx, question, answer_md, json.dumps(terms, ensure_ascii=False)),
        ).lastrowid


def for_slide(db: Database, deck_id: int, idx: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM questions WHERE deck_id = ? AND idx = ? ORDER BY id", (deck_id, idx)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "question": r["question"],
            "answer_md": r["answer_md"],
            "terms": json.loads(r["terms_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def thread(db: Database, deck_id: int, idx: int) -> tuple[Exchange, ...]:
    return tuple(Exchange(q["question"], q["answer_md"]) for q in for_slide(db, deck_id, idx))


def counts(db: Database, deck_id: int) -> dict[int, int]:
    with db.connect() as conn:
        rows = conn.execute("SELECT idx, COUNT(*) AS n FROM questions WHERE deck_id = ? GROUP BY idx", (deck_id,))
        return {r["idx"]: r["n"] for r in rows}
