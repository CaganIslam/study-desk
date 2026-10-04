"""Moodle sync through the web service API, without Claude.

New or changed PDFs of every course with a `moodle_id` are downloaded into the
course's `slides/` folder. Nothing is ever deleted. The token is read from the
macOS Keychain (or the MOODLE_TOKEN environment variable) and never logged.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from studydesk.courses import Catalog
from studydesk.db import Database

KEYCHAIN_SERVICE = "study-desk-moodle"
TIMEOUT = 30


class MoodleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def get_token(url: str) -> str | None:
    """MOODLE_TOKEN wins (tests, CI); otherwise the Keychain item for this Moodle URL."""
    if os.environ.get("MOODLE_TOKEN"):
        return os.environ["MOODLE_TOKEN"]
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", url, "-w"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def set_token(url: str, token: str) -> None:
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", url, "-w", token],
        check=True,
        capture_output=True,
    )


@dataclass(frozen=True)
class RemoteFile:
    filename: str
    fileurl: str
    timemodified: int
    filesize: int


class MoodleClient:
    def __init__(self, url: str, token: str, opener: Callable | None = None) -> None:
        self.url = url.rstrip("/")
        self._token = token
        context = ssl.create_default_context()
        self._open = opener or (lambda req: urllib.request.urlopen(req, timeout=TIMEOUT, context=context))

    def call(self, function: str, **params) -> object:
        query = urllib.parse.urlencode(
            {"wstoken": self._token, "wsfunction": function, "moodlewsrestformat": "json", **params}
        )
        try:
            with self._open(f"{self.url}/webservice/rest/server.php?{query}") as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MoodleError("network", f"Moodle unreachable: {exc.__class__.__name__}") from None
        if isinstance(body, dict) and body.get("exception"):
            raise MoodleError(body.get("errorcode", "moodle"), body.get("message", "Moodle error"))
        return body

    def download(self, fileurl: str) -> bytes:
        separator = "&" if "?" in fileurl else "?"
        try:
            with self._open(f"{fileurl}{separator}token={urllib.parse.quote(self._token)}") as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MoodleError("network", f"download failed: {exc.__class__.__name__}") from None

    def course_files(self, course_id: int) -> list[RemoteFile]:
        files = []
        for section in self.call("core_course_get_contents", courseid=course_id):
            for module in section.get("modules", []):
                for item in module.get("contents") or []:
                    if item.get("type") == "file" and item.get("filename", "").lower().endswith(".pdf"):
                        files.append(
                            RemoteFile(
                                filename=item["filename"],
                                fileurl=item["fileurl"],
                                timemodified=int(item.get("timemodified") or 0),
                                filesize=int(item.get("filesize") or 0),
                            )
                        )
        return files


@dataclass
class SyncResult:
    new: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"new": self.new, "updated": self.updated, "errors": self.errors}


def _safe_name(filename: str) -> str:
    name = Path(filename).name.strip()
    return name if name and name not in {".", ".."} else "file.pdf"


def _target(slides: Path, filename: str, tracked_path: str | None) -> Path:
    """Where to write a file. An unrelated file already using the name is never overwritten."""
    path = slides / _safe_name(filename)
    if tracked_path or not path.exists():
        return Path(tracked_path) if tracked_path else path
    alternative = path.with_name(f"{path.stem} (Moodle){path.suffix}")
    return alternative


def sync(db: Database, catalog: Catalog, data_root: Path, client: MoodleClient) -> SyncResult:
    result = SyncResult()
    for course in catalog.courses:
        if not course.moodle_id:
            continue
        try:
            remote = client.course_files(course.moodle_id)
        except MoodleError as exc:
            result.errors.append(f"{course.code}: {exc}")
            continue
        slides = data_root / course.folder / "slides"
        for item in remote:
            with db.connect() as conn:
                row = conn.execute(
                    "SELECT timemodified, local_path FROM moodle_files WHERE course_code = ? AND fileurl = ?",
                    (course.code, item.fileurl),
                ).fetchone()
            if row and row["timemodified"] == item.timemodified and Path(row["local_path"]).exists():
                continue
            path = _target(slides, item.filename, row["local_path"] if row else None)
            # A file put there earlier by hand (same name and size) is adopted, not re-downloaded.
            adopt = row is None and (slides / _safe_name(item.filename)).exists() and (
                slides / _safe_name(item.filename)
            ).stat().st_size == item.filesize
            if adopt:
                path = slides / _safe_name(item.filename)
            else:
                try:
                    content = client.download(item.fileurl)
                except MoodleError as exc:
                    result.errors.append(f"{course.code}: {item.filename}: {exc}")
                    continue
                slides.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".part")
                tmp.write_bytes(content)
                tmp.replace(path)
                (result.updated if row else result.new).append(f"{course.code}/{path.name}")
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO moodle_files (course_code, fileurl, filename, timemodified, filesize, local_path)"
                    " VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (course_code, fileurl) DO UPDATE SET filename = excluded.filename,"
                    " timemodified = excluded.timemodified, filesize = excluded.filesize,"
                    " local_path = excluded.local_path, downloaded_at = datetime('now')",
                    (course.code, item.fileurl, item.filename, item.timemodified, item.filesize, str(path)),
                )
    return result


def record(db: Database, result: SyncResult) -> None:
    with db.connect() as conn:
        for key, value in (
            ("moodle.last_sync", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            ("moodle.last_result", json.dumps(result.as_dict())),
        ):
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def status(db: Database) -> tuple[str | None, dict | None]:
    with db.connect() as conn:
        rows = dict(conn.execute("SELECT key, value FROM app_meta WHERE key LIKE 'moodle.%'").fetchall())
    last = rows.get("moodle.last_result")
    return rows.get("moodle.last_sync"), json.loads(last) if last else None
