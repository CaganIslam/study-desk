"""Match a lecture transcript to slides, and pull out what the lecturer stressed.

One Claude call per recording (prompt `align_system.md`, schema `align.json`). The
result is stored as time sections per slide; the words spoken during a slide's
sections become that slide's "lecturer notes" for its explanation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from studydesk import decks
from studydesk.ai.runner import ClaudeCall, Runner
from studydesk.ai.tutor import _prompt, _schema
from studydesk.courses import Catalog
from studydesk.db import Database

# Files in a course's slides folder that are not lecture decks.
NOT_A_DECK = re.compile(r"syllabus|quiz|grade|lab plan|lab sections|sections|component|card", re.IGNORECASE)
NOTES_WORDS = 350  # how much of the lecturer's words go with one slide's explanation


def mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def seconds_of(text: str) -> float | None:
    parts = [p for p in str(text).strip().split(":") if p != ""]
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if len(values) == 2:
        return values[0] * 60 + values[1]
    if len(values) == 3:
        return values[0] * 3600 + values[1] * 60 + values[2]
    return None


def lecture_decks(db: Database, course_code: str) -> list[dict]:
    return [d for d in decks.list_decks(db, course_code) if not NOT_A_DECK.search(d["filename"])]


def _transcript_lines(db: Database, rec_id: int) -> list[str]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT start_s, text FROM transcript_segments WHERE recording_id = ? ORDER BY start_s", (rec_id,)
        ).fetchall()
    return [f"[{mmss(r['start_s'])}] {r['text']}" for r in rows]


def _slide_listing(db: Database, deck_rows: list[dict]) -> str:
    out = []
    for deck in deck_rows:
        out.append(f"Deck: {deck['filename']}")
        for slide in decks.get_slides(db, deck["id"]):
            body = " ".join(slide["text"].split())[len(slide["title"]) :][:90].strip()
            out.append(f"  {slide['label']}: {slide['title'][:80]}" + (f" | {body}" if body else ""))
    return "\n".join(out)


def align_call(db: Database, rec, course_name: str, model: str | None) -> ClaudeCall:
    deck_rows = lecture_decks(db, rec["course_code"])
    text = "\n\n".join(
        [
            f"Course: {rec['course_code']} {course_name}",
            f"Recording: {rec['source_name']}, {round(rec['duration_s'] / 60)} minutes",
            "Slides:\n" + (_slide_listing(db, deck_rows) or "(no decks yet)"),
            "Transcript:\n" + "\n".join(_transcript_lines(db, rec["id"])),
        ]
    )
    return ClaudeCall(
        system=_prompt("align_system"), text=text, schema=_schema("align"), model=model, effort="medium", timeout=900
    )


def apply(db: Database, rec, data: dict) -> dict:
    """Store sections and emphasis from Claude's answer. Unknown decks or slide numbers become topic-only parts."""
    by_name = {d["filename"]: d["id"] for d in lecture_decks(db, rec["course_code"])}
    labels = {deck_id: {s["label"]: s["idx"] for s in decks.get_slides(db, deck_id)} for deck_id in by_name.values()}
    sections, matched = [], 0
    for part in data.get("sections", []):
        start, end = seconds_of(part.get("start", "")), seconds_of(part.get("end", ""))
        if start is None or end is None or end <= start:
            continue
        end = min(end, rec["duration_s"])
        deck_id = by_name.get(str(part.get("deck", "")).strip())
        idx = labels.get(deck_id, {}).get(str(part.get("label", "")).strip()) if deck_id else None
        if idx is None:
            deck_id = None
        matched += idx is not None
        sections.append((rec["id"], deck_id, idx, start, end, str(part.get("topic", ""))[:200]))
    emphasis = [
        (rec["id"], rec["course_code"], seconds_of(e.get("at", "")) or 0.0, e.get("kind", "important"), str(e.get("quote", ""))[:400])
        for e in data.get("emphasis", [])
        if e.get("quote")
    ]
    with db.connect() as conn:
        conn.execute("DELETE FROM recording_sections WHERE recording_id = ?", (rec["id"],))
        conn.execute("DELETE FROM emphasis WHERE recording_id = ?", (rec["id"],))
        conn.executemany(
            "INSERT INTO recording_sections (recording_id, deck_id, idx, start_s, end_s, topic) VALUES (?, ?, ?, ?, ?, ?)",
            sections,
        )
        conn.executemany(
            "INSERT INTO emphasis (recording_id, course_code, at_s, kind, quote) VALUES (?, ?, ?, ?, ?)", emphasis
        )
        conn.execute(
            "UPDATE recordings SET aligned_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), rec["id"]),
        )
    return {"sections": len(sections), "slides": matched, "emphasis": len(emphasis)}


def align(db: Database, catalog: Catalog, runner: Runner, rec_id: int, model: str | None = None) -> dict:
    with db.connect() as conn:
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,)).fetchone()
    if rec is None or rec["status"] not in ("done", "bad_quality") or not rec["course_code"]:
        return {"skipped": True}
    course = catalog.by_code(rec["course_code"])
    result = runner.run(align_call(db, rec, course.name if course else rec["course_code"], model))
    return apply(db, rec, result.data)


def lecturer_notes(db: Database, deck_id: int, idx: int, max_words: int = NOTES_WORDS) -> str | None:
    """The lecturer's words while this slide was on, from every recording that covered it."""
    with db.connect() as conn:
        parts = conn.execute(
            "SELECT recording_id, start_s, end_s FROM recording_sections WHERE deck_id = ? AND idx = ? ORDER BY recording_id, start_s",
            (deck_id, idx),
        ).fetchall()
        chunks = []
        for part in parts:
            words = [
                r["text"]
                for r in conn.execute(
                    "SELECT text FROM transcript_segments WHERE recording_id = ? AND start_s >= ? AND start_s < ? ORDER BY start_s",
                    (part["recording_id"], part["start_s"], part["end_s"]),
                )
            ]
            if words:
                chunks.append(" ".join(words))
    if not chunks:
        return None
    text = " … ".join(chunks).split()
    return " ".join(text[:max_words]) + (" …" if len(text) > max_words else "")


def emphasis_for_slide(db: Database, deck_id: int, idx: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT e.kind, e.quote, e.at_s, e.recording_id FROM emphasis e JOIN recording_sections s"
            " ON s.recording_id = e.recording_id AND e.at_s >= s.start_s AND e.at_s < s.end_s"
            " WHERE s.deck_id = ? AND s.idx = ? ORDER BY e.recording_id, e.at_s",
            (deck_id, idx),
        ).fetchall()
    return [{"kind": r["kind"], "quote": r["quote"], "at": mmss(r["at_s"]), "recording_id": r["recording_id"]} for r in rows]


def emphasis_counts(db: Database, deck_id: int) -> dict[int, int]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.idx, COUNT(DISTINCT e.id) AS n FROM emphasis e JOIN recording_sections s"
            " ON s.recording_id = e.recording_id AND e.at_s >= s.start_s AND e.at_s < s.end_s"
            " WHERE s.deck_id = ? GROUP BY s.idx",
            (deck_id,),
        ).fetchall()
    return {r["idx"]: r["n"] for r in rows}


def slide_recordings(db: Database, deck_id: int, idx: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.recording_id, MIN(s.start_s) AS start_s, r.started_at FROM recording_sections s"
            " JOIN recordings r ON r.id = s.recording_id WHERE s.deck_id = ? AND s.idx = ? GROUP BY s.recording_id",
            (deck_id, idx),
        ).fetchall()
    return [{"id": r["recording_id"], "at": mmss(r["start_s"]), "started": r["started_at"]} for r in rows]


def recent_emphasis(db: Database, kinds: tuple[str, ...] = ("exam", "homework", "admin"), limit: int = 12) -> list[dict]:
    marks = ",".join("?" * len(kinds))
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT e.course_code, e.kind, e.quote, e.at_s, e.recording_id, r.started_at FROM emphasis e"
            f" JOIN recordings r ON r.id = e.recording_id WHERE e.kind IN ({marks}) ORDER BY r.started_at DESC, e.at_s LIMIT ?",
            (*kinds, limit),
        ).fetchall()
    return [
        {"course": r["course_code"], "kind": r["kind"], "quote": r["quote"], "at": mmss(r["at_s"]), "recording_id": r["recording_id"], "started": r["started_at"]}
        for r in rows
    ]


def needing_realign(db: Database, course_code: str) -> list[int]:
    """Recordings of a course with parts that matched no slide: worth another try when a deck arrives."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT r.id FROM recordings r JOIN recording_sections s ON s.recording_id = r.id"
            " WHERE r.course_code = ? AND s.deck_id IS NULL",
            (course_code,),
        ).fetchall()
    return [r["id"] for r in rows]


def unaligned(db: Database) -> list[int]:
    with db.connect() as conn:
        return [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM recordings WHERE status = 'done' AND aligned_at IS NULL AND course_code IS NOT NULL ORDER BY started_at"
            )
        ]


def transcript_path(db: Database, rec_id: int) -> Path | None:
    with db.connect() as conn:
        row = conn.execute("SELECT transcript_path FROM recordings WHERE id = ?", (rec_id,)).fetchone()
    return Path(row["transcript_path"]) if row and row["transcript_path"] else None
