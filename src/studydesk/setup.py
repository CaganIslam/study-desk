"""First-run setup and settings: what is configured, and the steps that write it.

The files stay the source of truth. `config.toml` (app directory) and `courses.toml`
(data root) are rewritten here with every other key kept; the Moodle token only ever
goes to the Keychain. The server reads `config.toml` once at start, so a change to it
needs a restart; `courses.toml` is re-read whenever it changes.
"""

from __future__ import annotations

import json
import re
import shutil
import time as clock
import tomllib
import urllib.parse
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pypdfium2 as pdfium

from studydesk import decks
from studydesk.ai.runner import ClaudeCall, ClaudeError, Runner
from studydesk.ai.tutor import LANGUAGES, _prompt, _schema, language_name
from studydesk.config import ConfigError
from studydesk.courses import DAYS, load_catalog
from studydesk.ingest import moodle, transcribe

CONFIG_HEADER = "# study-desk settings. The setup page writes this file; editing it by hand is fine too.\n"
COURSES_HEADER = "# Courses and schedule, format in docs/courses-toml.md. The setup page writes this file; editing it by hand is fine too.\n"
SUGGESTED_DATA_ROOT = "~/Documents/Dersler"
SYLLABUS_HINTS = ("syllab", "izlence", "outline", "course info", "course-info")
COURSE_KEYS = ("code", "name", "folder", "aliases", "language", "moodle_id", "syllabus")


class SetupError(Exception):
    """A setup step failed for a reason the student can act on. `code` maps to a UI string."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


# --- TOML ------------------------------------------------------------------------

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(name: str) -> str:
    return name if _BARE_KEY.fullmatch(name) else json.dumps(name, ensure_ascii=False)


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, (date, time)):  # datetime is a date
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"cannot write {type(value).__name__} to TOML")


def _is_tables(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def dumps(data: dict) -> str:
    """TOML for the plain data tomllib returns: scalars first, then tables and arrays of tables."""
    lines: list[str] = []

    def table(current: dict, path: list[str]) -> None:
        indent = "  " * max(len(path) - 1, 0)
        for name, value in current.items():
            if not isinstance(value, dict) and not _is_tables(value):
                lines.append(f"{indent}{_key(name)} = {_value(value)}")
        for name, value in current.items():
            sub = [*path, name]
            header = ".".join(_key(p) for p in sub)
            sub_indent = "  " * (len(sub) - 1)
            if isinstance(value, dict):
                lines.extend(["", f"{sub_indent}[{header}]"])
                table(value, sub)
            elif _is_tables(value):
                for item in value:
                    lines.extend(["", f"{sub_indent}[[{header}]]"])
                    table(item, sub)

    table(data, [])
    return "\n".join(lines).lstrip("\n") + "\n"


def read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _write(path: Path, text: str, check=None) -> None:
    """Write through a temporary file; `check(tmp)` may reject the new content before it replaces the old."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        if check:
            check(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)


def write_config(home: Path, raw: dict) -> None:
    _write(home / "config.toml", CONFIG_HEADER + "\n" + dumps(raw), lambda tmp: tomllib.loads(tmp.read_text(encoding="utf-8")))


def write_courses(data_root: Path, raw: dict) -> None:
    _write(data_root / "courses.toml", COURSES_HEADER + "\n" + dumps(raw), load_catalog)


# --- status ----------------------------------------------------------------------


def _display_path(path: Path) -> str:
    """~/... for paths in the home folder, as people write them."""
    try:
        rel = path.relative_to(Path.home())
    except ValueError:
        return str(path)
    return "~" if rel == Path(".") else f"~/{rel}"


def local_timezone() -> str:
    """The Mac's timezone name (from /etc/localtime), UTC when it cannot be read."""
    try:
        name = str(Path("/etc/localtime").resolve()).split("zoneinfo/", 1)[1]
        ZoneInfo(name)
        return name
    except (IndexError, OSError, ValueError, KeyError):
        return "UTC"


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value


def status(home: Path) -> dict:
    """Everything the setup page shows, read fresh from disk."""
    raw = read_toml(home / "config.toml")
    data_root = Path(raw["data_root"]).expanduser() if isinstance(raw.get("data_root"), str) and raw["data_root"] else None
    language = raw.get("language") if isinstance(raw.get("language"), str) else "tr"
    moodle_url = (raw.get("moodle") or {}).get("url") if isinstance(raw.get("moodle"), dict) else None
    folder_ok = bool(data_root and data_root.is_dir())

    courses, catalog, catalog_error = [], {"timezone": local_timezone(), "term_end": None}, None
    if folder_ok:
        try:
            catalog_raw = read_toml(data_root / "courses.toml")
            load_catalog(data_root / "courses.toml")  # the app must be able to read what we show
        except ConfigError as exc:
            catalog_raw, catalog_error = {}, str(exc)
        has_file = (data_root / "courses.toml").exists()
        catalog = {
            # what the app uses: UTC when an existing file names no timezone, this Mac's zone for a new file
            "timezone": catalog_raw.get("timezone") or ("UTC" if has_file else local_timezone()),
            "term_end": _jsonable(catalog_raw.get("term_end")),
        }
        for c in catalog_raw.get("courses", []):
            courses.append(
                {
                    "code": c.get("code"),
                    "name": c.get("name"),
                    "folder": c.get("folder"),
                    "aliases": list(c.get("aliases", [])),
                    "language": c.get("language", "en"),
                    "moodle_id": c.get("moodle_id"),
                    "syllabus": c.get("syllabus"),
                    "folder_exists": bool(c.get("folder")) and (data_root / str(c.get("folder"))).is_dir(),
                    "slots": _jsonable(c.get("slots", [])),
                    "exams": _jsonable(c.get("exams", [])),
                    "topics": _jsonable(c.get("topics", [])),
                }
            )

    return {
        "complete": folder_ok and bool(courses) and catalog_error is None,
        "folder": {
            "data_root": _display_path(data_root) if data_root else None,
            "exists": folder_ok,
            "icloud": bool(data_root) and "Mobile Documents" in str(data_root),
            "suggested": SUGGESTED_DATA_ROOT,
            "language": language,
            "languages": [{"code": k, "name": v} for k, v in LANGUAGES.items()],
        },
        "moodle": {"url": moodle_url, "token_saved": bool(moodle_url and moodle.get_token(moodle_url))},
        "courses": courses,
        "catalog": catalog,
        "catalog_error": catalog_error,
    }


# --- data folder -------------------------------------------------------------------


def save_folder(home: Path, data_root: str, language: str) -> Path:
    path = Path(data_root.strip()).expanduser()
    if not data_root.strip() or not path.is_absolute():
        raise SetupError("folder_not_absolute", "the folder must be a full path, like ~/Documents/Courses")
    if path.exists() and not path.is_dir():
        raise SetupError("folder_is_file", "that path is a file, not a folder")
    if language not in LANGUAGES:
        raise SetupError("bad_language", f"language must be one of {', '.join(LANGUAGES)}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SetupError("folder_not_writable", f"cannot create the folder: {exc.strerror}") from None
    raw = read_toml(home / "config.toml")
    raw["data_root"] = _display_path(path)
    raw["language"] = language
    write_config(home, raw)
    return path


def list_dirs(path: str | None) -> dict:
    """Subfolders of `path` (default: the home folder) for the folder browser on the setup page.

    A path that does not exist yet (a folder about to be created) opens its nearest existing parent.
    """
    base = Path(path).expanduser() if path else Path.home()
    if not base.is_absolute():
        raise SetupError("folder_missing", "that folder does not exist", 404)
    while not base.is_dir() and base.parent != base:
        base = base.parent
    try:
        names = sorted(
            (p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "Library"),
            key=str.casefold,
        )
    except PermissionError:
        names = []
    return {
        "path": _display_path(base),
        "parent": _display_path(base.parent) if base.parent != base else None,
        "dirs": names,
    }


# --- Moodle --------------------------------------------------------------------------

_PAGE_SUFFIXES = ("/login/index.php", "/index.php", "/login", "/my")


def normalise_url(url: str) -> str:
    """https://moodle.school.edu from whatever was pasted (a page of the site, no scheme, a trailing slash)."""
    text = url.strip()
    if not text:
        raise SetupError("moodle_url_missing", "the Moodle address is empty")
    if "://" not in text:
        text = "https://" + text
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SetupError("moodle_url_bad", "that does not look like a web address")
    path = parts.path.rstrip("/")
    for suffix in _PAGE_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
    return f"{parts.scheme}://{parts.netloc}{path.rstrip('/')}"


def _moodle_call(client: moodle.MoodleClient, function: str, **params):
    try:
        return client.call(function, **params)
    except moodle.MoodleError as exc:
        if exc.code == "invalidtoken":
            raise SetupError("moodle_invalid_token", "Moodle did not accept the token") from None
        if exc.code == "network":
            raise SetupError("moodle_unreachable", "Moodle could not be reached at that address") from None
        if exc.code == "not_moodle":
            raise SetupError("moodle_not_found", "there is no Moodle web service at that address") from None
        raise SetupError("moodle_error", f"Moodle said: {exc}") from None


def site_info(client: moodle.MoodleClient) -> dict:
    info = _moodle_call(client, "core_webservice_get_site_info")
    if not isinstance(info, dict) or "userid" not in info:
        raise SetupError("moodle_not_found", "there is no Moodle web service at that address")
    return {"site": info.get("sitename") or "", "user": info.get("fullname") or "", "userid": info["userid"]}


def save_moodle(home: Path, url: str) -> None:
    raw = read_toml(home / "config.toml")
    table = raw.get("moodle") if isinstance(raw.get("moodle"), dict) else {}
    table["url"] = url
    raw["moodle"] = table
    write_config(home, raw)


def remove_moodle(home: Path) -> None:
    raw = read_toml(home / "config.toml")
    table = raw.get("moodle") if isinstance(raw.get("moodle"), dict) else {}
    table.pop("url", None)
    if table:
        raw["moodle"] = table
    else:
        raw.pop("moodle", None)
    write_config(home, raw)


_CODE = re.compile(r"\b([A-Za-z]{2,6})\s*(\d{2,4}[A-Za-z]?)\b")
_SMALL_WORDS = {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "with", "ve", "ile"}


def guess_code(shortname: str, fullname: str) -> str:
    for text in (shortname, fullname):
        match = _CODE.search(text or "")
        if match:
            return f"{match.group(1).upper()} {match.group(2).upper()}"
    return (shortname or fullname or "COURSE").strip()


def guess_name(fullname: str, code: str) -> str:
    name = fullname or code
    for variant in (code, code.replace(" ", "")):
        name = name.replace(variant, "")
    name = re.sub(r"\s+", " ", name).strip(" -:·")
    if name.isupper():
        words = []
        for i, word in enumerate(name.split(" ")):
            lower = word.replace("İ", "i").lower()
            words.append(lower if i and lower in _SMALL_WORDS else lower[:1].upper() + lower[1:])
        name = " ".join(words)
    return name or code


def folder_for(code: str, name: str) -> str:
    return re.sub(r"[/:\\]", "-", f"{code.replace(' ', '')} {name}").strip()


def moodle_courses(client: moodle.MoodleClient) -> list[dict]:
    """The student's Moodle courses with suggested code, name and folder; running courses first."""
    info = site_info(client)
    items = _moodle_call(client, "core_enrol_get_users_courses", userid=info["userid"])
    now = clock.time()
    found = []
    for c in items if isinstance(items, list) else []:
        start, end = int(c.get("startdate") or 0), int(c.get("enddate") or 0)
        code = guess_code(c.get("shortname", ""), c.get("fullname", ""))
        name = guess_name(c.get("fullname", ""), code)
        digits = re.findall(r"\d+", code)
        found.append(
            {
                "id": c["id"],
                "shortname": c.get("shortname", ""),
                "fullname": c.get("fullname", ""),
                "current": start <= now and (end == 0 or now <= end),
                "startdate": start,
                "suggested": {"code": code, "name": name, "folder": folder_for(code, name), "aliases": digits[:1]},
            }
        )
    found.sort(key=lambda c: (not c["current"], -c["startdate"], c["fullname"]))
    return found


# --- courses ---------------------------------------------------------------------


def _clean_folder(folder: str) -> str:
    folder = folder.strip()
    if not folder or folder in {".", ".."} or "/" in folder or "\\" in folder:
        raise SetupError("bad_folder_name", f"bad folder name {folder!r}")
    return folder


def save_courses(data_root: Path, entries: list[dict]) -> None:
    """Replace the course list. Schedules and other settings of courses that stay are kept."""
    path = data_root / "courses.toml"
    raw = read_toml(path)
    old = {c.get("code"): c for c in raw.get("courses", []) if isinstance(c, dict)}
    courses, codes, folders = [], set(), set()
    for entry in entries:
        code = str(entry.get("code", "")).strip()
        name = str(entry.get("name", "")).strip()
        if not code or not name:
            raise SetupError("course_incomplete", "every course needs a code and a name")
        folder = _clean_folder(str(entry.get("folder") or folder_for(code, name)))
        if code in codes or folder in folders:
            raise SetupError("course_duplicate", f"{code} is listed twice or shares a folder")
        codes.add(code)
        folders.add(folder)
        language = str(entry.get("language") or "en")
        aliases = [str(a).strip().lower() for a in entry.get("aliases", []) if str(a).strip()]
        merged = dict(old.get(code, {}))
        merged.update(code=code, name=name, folder=folder, aliases=aliases, language=language)
        if entry.get("moodle_id"):
            merged["moodle_id"] = int(entry["moodle_id"])
        elif "moodle_id" in entry:
            merged.pop("moodle_id", None)
        ordered = {k: merged[k] for k in COURSE_KEYS if k in merged}
        ordered.update({k: v for k, v in merged.items() if k not in ordered})
        courses.append(ordered)
    raw["timezone"] = raw.get("timezone") or local_timezone()
    raw["courses"] = courses
    write_courses(data_root, raw)
    for course in courses:
        (data_root / course["folder"] / "slides").mkdir(parents=True, exist_ok=True)


def _course_raw(raw: dict, code: str) -> dict:
    course = next((c for c in raw.get("courses", []) if c.get("code") == code), None)
    if course is None:
        raise SetupError("course_not_found", f"no course {code}", 404)
    return course


def course_pdfs(data_root: Path, folder: str) -> list[dict]:
    """PDFs of a course, likely syllabi first."""
    base = data_root / folder
    found = []
    for pdf in sorted(base.rglob("*.pdf")) if base.is_dir() else []:
        rel = pdf.relative_to(base).as_posix()
        guess = any(hint in pdf.name.lower() for hint in SYLLABUS_HINTS)
        found.append({"file": rel, "size": pdf.stat().st_size, "syllabus": guess})
    found.sort(key=lambda f: (not f["syllabus"], f["file"].casefold()))
    return found


def save_upload(data_root: Path, folder: str, filename: str, content: bytes) -> str:
    """Store a PDF someone picked on the setup page in the course's slides folder."""
    name = Path(filename or "file.pdf").name.strip() or "file.pdf"
    if not name.lower().endswith(".pdf") or not content.startswith(b"%PDF"):
        raise SetupError("not_pdf", "only PDF files can be added here")
    slides = data_root / folder / "slides"
    slides.mkdir(parents=True, exist_ok=True)
    target, n = slides / name, 2
    while target.exists() and target.read_bytes() != content:
        target = slides / f"{Path(name).stem} ({n}).pdf"
        n += 1
    target.write_bytes(content)
    return target.relative_to(data_root / folder).as_posix()


# --- schedule ----------------------------------------------------------------------

SYLLABUS_PAGES = 12
SYLLABUS_CHARS = 20000


def syllabus_text(path: Path) -> str:
    with decks.PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError:
            raise SetupError("syllabus_unreadable", "the PDF cannot be opened (damaged or password protected)") from None
        try:
            texts = decks.page_texts(pdf)[:SYLLABUS_PAGES]
        finally:
            pdf.close()
    return "\n\n".join(texts)[:SYLLABUS_CHARS]


def schedule_call(code: str, name: str, text: str, today: date, timezone: str, language: str, model: str | None) -> ClaudeCall:
    prompt = (
        f"Course: {code} {name}\n"
        f"Today: {today.isoformat()} ({DAYS[today.weekday()]})\n"
        f"Timezone: {timezone}\n\n"
        f"Syllabus text:\n{text}"
    )
    return ClaudeCall(
        system=_prompt("schedule_system").replace("{language}", language_name(language)),
        text=prompt,
        schema=_schema("schedule"),
        model=model,
        effort="medium",
        timeout=300,
    )


def _ok_time(value) -> bool:
    try:
        time.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def _ok_date(value) -> bool:
    try:
        date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def clean_proposal(data: dict) -> dict:
    """Keep only entries the schedule file can hold; the student reviews the rest on the page."""
    slots = [
        {"day": s["day"], "start": s["start"], "end": s["end"], "kind": s.get("kind") or "lecture", "location": s.get("location") or ""}
        for s in data.get("slots", [])
        if s.get("day") in DAYS and _ok_time(s.get("start")) and _ok_time(s.get("end")) and s["end"] > s["start"]
    ]
    exams = [
        {"date": e["date"], "title": e.get("title") or "Exam", "start": e.get("start") if _ok_time(e.get("start")) else ""}
        for e in data.get("exams", [])
        if _ok_date(e.get("date"))
    ]
    topics = [
        {"week_of": t["week_of"], "title": t.get("title", "")}
        for t in data.get("topics", [])
        if _ok_date(t.get("week_of")) and t.get("title")
    ]
    term_end = data.get("term_end") if _ok_date(data.get("term_end")) else ""
    return {
        "slots": slots,
        "exams": exams,
        "topics": topics,
        "term_end": term_end,
        "hours_inferred": bool(data.get("hours_inferred")),
        "notes": str(data.get("notes") or ""),
    }


def propose_schedule(
    data_root: Path, code: str, file: str, runner: Runner, language: str, model: str | None, today: date
) -> dict:
    raw = read_toml(data_root / "courses.toml")
    course = _course_raw(raw, code)
    base = (data_root / course["folder"]).resolve()
    path = (base / file).resolve()
    if base not in path.parents or not path.is_file() or path.suffix.lower() != ".pdf":
        raise SetupError("syllabus_missing", "that PDF is not in the course folder", 404)
    text = syllabus_text(path)
    if len(text.strip()) < 40:
        raise SetupError("syllabus_no_text", "the PDF has no readable text (a scan?)")
    timezone = raw.get("timezone") or local_timezone()
    result = runner.run(schedule_call(code, course.get("name", ""), text, today, timezone, language, model))
    return clean_proposal(result.data)


def _drop_empty(entry: dict, optional: tuple[str, ...]) -> dict:
    return {k: v for k, v in entry.items() if not (k in optional and (v is None or v == ""))}


def save_schedule(data_root: Path, code: str, slots: list[dict], exams: list[dict], topics: list[dict], syllabus: str | None) -> None:
    """Replace a course's classes, exams and topics. Extra keys of a slot (skip, attending...) are kept."""
    raw = read_toml(data_root / "courses.toml")
    course = _course_raw(raw, code)
    course["slots"] = [_drop_empty(dict(s), ("location", "first")) for s in slots]
    course["exams"] = [_drop_empty(dict(e), ("start", "end")) for e in exams]
    course["topics"] = [dict(t) for t in topics if str(t.get("title", "")).strip()]
    for key in ("slots", "exams", "topics"):
        if not course[key]:
            course.pop(key)
    if syllabus is not None:
        if syllabus:
            course["syllabus"] = syllabus
        else:
            course.pop("syllabus", None)
    write_courses(data_root, raw)


def save_term(data_root: Path, term_end: str | None, timezone: str | None) -> None:
    raw = read_toml(data_root / "courses.toml")
    if term_end:
        raw["term_end"] = term_end
    else:
        raw.pop("term_end", None)
    if timezone:
        raw["timezone"] = timezone
    write_courses(data_root, raw)


# --- checks ------------------------------------------------------------------------

_PING_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def check_claude(runner: Runner) -> dict:
    """One tiny call: is Claude Code installed, logged in and within its limits?"""
    try:
        runner.run(ClaudeCall(system="Set ok to true.", text="ping", schema=_PING_SCHEMA, effort="low", timeout=90))
    except ClaudeError as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
    return {"ok": True, "code": None, "message": None}


def check_tools() -> dict:
    return {
        "ffmpeg": bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")),
        "whisper": bool(shutil.which("mlx_whisper")),
        "whisper_model": transcribe._model_cached(transcribe.MODELS["turbo"]),
    }


def now_date(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()
