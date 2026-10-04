"""Lecture recordings: import, match to a course by recording time, transcribe, check, save.

The course comes from the file's own `creation_time`, so recordings dragged in from
Voice Memos need no library access. The transcript goes to `<course>/transcripts/`.
Audio that the app copied for itself is deleted once the transcript is saved; files
the user points the importer at are only read.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from studydesk.courses import Catalog
from studydesk.db import Database
from studydesk.ingest import transcribe as tr

AUDIO_SUFFIXES = {".qta", ".m4a", ".mp3", ".wav", ".aac", ".mp4", ".mov"}


class RecordingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def probe(path: Path) -> tuple[datetime, float]:
    """Recording start (UTC) and duration in seconds, from the file's own metadata."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=creation_time", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RecordingError("unreadable", f"{path.name} is not a readable audio file")
    info = json.loads(proc.stdout).get("format", {})
    created = (info.get("tags") or {}).get("creation_time")
    started = (
        datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created
        else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) - timedelta(seconds=float(info.get("duration", 0)))
    )
    return started.astimezone(timezone.utc), float(info.get("duration", 0))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def add(
    db: Database,
    catalog: Catalog,
    path: Path,
    keep_audio_at: Path | None = None,
    probe_fn: Callable[[Path], tuple[datetime, float]] | None = None,
) -> tuple[int, bool]:
    """Register a recording. Returns (id, is_new). `keep_audio_at` is the app's own copy, deleted after transcription."""
    sha = _sha256(path)
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM recordings WHERE sha256 = ?", (sha,)).fetchone()
    if row:
        return row["id"], False
    started, duration = (probe_fn or probe)(path)
    course = catalog.match(started, timedelta(seconds=duration))
    with db.connect() as conn:
        new_id = conn.execute(
            "INSERT INTO recordings (sha256, source_name, started_at, duration_s, course_code, status, audio_path)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sha,
                path.name,
                started.isoformat(timespec="seconds"),
                duration,
                course.code if course else None,
                "queued" if course else "needs_course",
                str(keep_audio_at or path),
            ),
        ).lastrowid
    return new_id, True


def get(db: Database, rec_id: int):
    with db.connect() as conn:
        return conn.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,)).fetchone()


def _set(db: Database, rec_id: int, **fields) -> None:
    columns = ", ".join(f"{k} = ?" for k in fields)
    with db.connect() as conn:
        conn.execute(f"UPDATE recordings SET {columns}, updated_at = datetime('now') WHERE id = ?", (*fields.values(), rec_id))


def set_course(db: Database, rec_id: int, course_code: str) -> None:
    _set(db, rec_id, course_code=course_code, status="queued")


def process(
    db: Database,
    catalog: Catalog,
    data_root: Path,
    rec_id: int,
    model: str = "turbo",
    owned_audio: bool = True,
    transcribe_fn: Callable[..., tr.Transcript] | None = None,
) -> str:
    """Transcribe one queued recording and check it. Returns the new status."""
    rec = get(db, rec_id)
    course = catalog.by_code(rec["course_code"] or "")
    if course is None:
        _set(db, rec_id, status="needs_course")
        return "needs_course"
    audio = Path(rec["audio_path"] or "")
    if not audio.exists():
        _set(db, rec_id, status="failed", error="the audio file is gone")
        return "failed"
    _set(db, rec_id, status="transcribing", error=None)
    try:
        transcript = (transcribe_fn or tr.transcribe)(audio, language=course.language, model=model)
    except tr.TranscriptionError as exc:
        _set(db, rec_id, status="failed", error=f"{exc.code}: {exc}")
        return "failed"
    quality = tr.check(transcript, rec["duration_s"])

    started = datetime.fromisoformat(rec["started_at"]).astimezone(catalog.timezone)
    title = f"{course.code} {course.name} - {started:%Y-%m-%d %H:%M} ({round(rec['duration_s'] / 60)} dk)"
    path = data_root / course.folder / "transcripts" / f"{started:%Y-%m-%d-%H%M}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tr.markdown(transcript, title), encoding="utf-8")
    with db.connect() as conn:
        conn.execute("DELETE FROM transcript_segments WHERE recording_id = ?", (rec_id,))
        conn.executemany(
            "INSERT INTO transcript_segments (recording_id, start_s, end_s, text) VALUES (?, ?, ?, ?)",
            [(rec_id, s.start, s.end, s.text) for s in transcript.segments if s.text],
        )
    status = "done" if quality.ok else "bad_quality"
    fields = dict(status=status, transcript_path=str(path), model=transcript.model, quality_json=json.dumps(asdict(quality)))
    if status == "done" and owned_audio:
        audio.unlink(missing_ok=True)  # the transcript is saved: the app's copy of the audio goes
        fields["audio_path"] = None
    _set(db, rec_id, **fields)
    return status


def discard(db: Database, rec_id: int, owned_audio: bool = True) -> None:
    """Forget a recording the student does not want (e.g. a broken one); deletes the app's audio copy."""
    rec = get(db, rec_id)
    if rec and owned_audio and rec["audio_path"]:
        Path(rec["audio_path"]).unlink(missing_ok=True)
    with db.connect() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))


def listing(db: Database, catalog: Catalog) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM recordings ORDER BY started_at DESC").fetchall()
    result = []
    for r in rows:
        started = datetime.fromisoformat(r["started_at"]).astimezone(catalog.timezone)
        quality = json.loads(r["quality_json"]) if r["quality_json"] else None
        result.append(
            {
                "id": r["id"],
                "name": r["source_name"],
                "started": started.isoformat(timespec="minutes"),
                "minutes": round(r["duration_s"] / 60),
                "course": r["course_code"],
                "status": r["status"],
                "model": r["model"],
                "reasons": quality["reasons"] if quality else [],
                "error": r["error"],
                "has_audio": bool(r["audio_path"]) and Path(r["audio_path"]).exists(),
            }
        )
    return result


def transcript(db: Database, rec_id: int) -> str | None:
    rec = get(db, rec_id)
    if rec is None or not rec["transcript_path"] or not Path(rec["transcript_path"]).exists():
        return None
    return Path(rec["transcript_path"]).read_text(encoding="utf-8")
