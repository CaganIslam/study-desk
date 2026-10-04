"""Import study history from earlier tools (format: docs/import-format.md).

Each session becomes slide views at its date (so resume points and sessions
exist), questions kept with the course, and glossary entries. Importing the
same session twice changes nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from studydesk import decks
from studydesk.courses import Catalog
from studydesk.db import Database
from studydesk.study import sessions, terms


@dataclass
class ImportReport:
    sessions: int = 0
    skipped: int = 0
    views: int = 0
    questions: int = 0
    terms: int = 0
    warnings: list[str] = field(default_factory=list)


def _deck_slides(db: Database, course_code: str, filename: str):
    for deck in decks.list_decks(db, course_code):
        if deck["filename"] == filename:
            return deck["id"], decks.get_slides(db, deck["id"])
    return None, []


def _covered(entry: dict) -> list[tuple[str, list]]:
    """[(deck filename, [labels])] from either a list (one deck) or a {filename: labels} map."""
    covered = entry.get("slides_covered") or []
    if isinstance(covered, dict):
        return list(covered.items())
    deck = entry.get("deck")
    return [(deck, covered)] if deck and covered else []


def import_history(db: Database, catalog: Catalog, data_root: Path, payload: dict) -> ImportReport:
    report = ImportReport()
    decks.scan(db, catalog, data_root)
    for entry in payload.get("sessions", []):
        digest = hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with db.connect() as conn:
            if conn.execute("SELECT 1 FROM app_meta WHERE key = ?", (f"import.{digest}",)).fetchone():
                report.skipped += 1
                continue
        course = catalog.by_code(entry.get("course", ""))
        if course is None:
            report.warnings.append(f"unknown course {entry.get('course')!r}, session skipped")
            continue

        start_text = (entry.get("time") or "09:00").split("-")[0]
        start = datetime.combine(date.fromisoformat(entry["date"]), time.fromisoformat(start_text), catalog.timezone)
        moment = start

        for filename, labels in _covered(entry):
            deck_id, slides = _deck_slides(db, course.code, filename)
            if deck_id is None:
                report.warnings.append(f"{course.code}: deck {filename!r} not found, its slides were skipped")
                continue
            by_label = {s["label"]: s["idx"] for s in slides}
            last = entry.get("last_slide")
            last = last.get(filename) if isinstance(last, dict) else last
            ordered = [str(l) for l in labels]
            if last is not None and str(last) not in ordered:
                ordered.append(str(last))
            for label in ordered:
                idx = by_label.get(label)
                if idx is None:
                    continue
                sessions.record_view(db, deck_id, idx, moment.astimezone(sessions.now_utc().tzinfo))
                moment += timedelta(minutes=1)
                report.views += 1

        with db.connect() as conn:
            for i, question in enumerate(entry.get("questions") or []):
                conn.execute(
                    "INSERT INTO deckless_questions (course_code, question, answer_md, terms_json, created_at)"
                    " VALUES (?, ?, '', '[]', datetime(?))",
                    (course.code, str(question), (start + timedelta(minutes=i)).isoformat()),
                )
                report.questions += 1

        known = {terms.normalise(k) for k in entry.get("known") or []}
        for item in entry.get("terms") or []:
            name = item.get("en") or item.get("term") or ""
            term_id = terms.upsert(db, course.code, {"term": name}, None, None, "import", hard=bool(item.get("asked")))
            if term_id is None:
                continue
            report.terms += 1
            if terms.normalise(name) in known:
                terms.set_status(db, term_id, "known")

        with db.connect() as conn:
            conn.execute("INSERT INTO app_meta (key, value) VALUES (?, datetime('now'))", (f"import.{digest}",))
        report.sessions += 1
    return report
