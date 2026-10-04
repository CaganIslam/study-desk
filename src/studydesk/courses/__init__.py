"""Courses, the weekly schedule, exams and time-to-course matching.

The source of truth is `courses.toml` in the data root, written by hand or
generated once. It is re-read when the file changes.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from studydesk.config import ConfigError

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TOLERANCE = timedelta(minutes=15)


@dataclass(frozen=True)
class Slot:
    day: int  # 0 = Monday
    start: time
    end: time
    kind: str = "lecture"
    location: str | None = None
    first: date | None = None
    skip: frozenset[date] = frozenset()
    attending: bool = True


@dataclass(frozen=True)
class Exam:
    date: date
    title: str
    start: time | None = None
    end: time | None = None


@dataclass(frozen=True)
class Topic:
    week_of: date
    title: str


@dataclass(frozen=True)
class Course:
    code: str
    name: str
    folder: str
    aliases: tuple[str, ...] = ()
    moodle_id: int | None = None
    language: str = "en"
    syllabus: str | None = None
    slots: tuple[Slot, ...] = ()
    exams: tuple[Exam, ...] = ()
    topics: tuple[Topic, ...] = ()

    def topic_for(self, day: date) -> Topic | None:
        """The syllabus topic of the week containing `day`, if any."""
        current = None
        for topic in sorted(self.topics, key=lambda t: t.week_of):
            if topic.week_of <= day:
                current = topic
        if current and day - current.week_of < timedelta(days=7):
            return current
        return None


@dataclass(frozen=True)
class Closure:
    date: date
    start: time | None = None  # None = whole day
    end: time | None = None


@dataclass(frozen=True)
class Occurrence:
    course: Course
    slot: Slot
    start: datetime
    end: datetime


@dataclass
class Catalog:
    courses: tuple[Course, ...] = ()
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    term_end: date | None = None
    closures: tuple[Closure, ...] = ()

    def by_code(self, code: str) -> Course | None:
        return next((c for c in self.courses if c.code == code), None)

    def _closed(self, day: date, start: time, end: time) -> bool:
        for closure in self.closures:
            if closure.date != day:
                continue
            c_start = closure.start or time.min
            c_end = closure.end or time.max
            if start < c_end and c_start < end:
                return True
        return False

    def occurrences(self, day: date, include_not_attending: bool = False) -> list[Occurrence]:
        """Classes held on `day`, in time order."""
        result = []
        if self.term_end and day > self.term_end:
            return result
        for course in self.courses:
            for slot in course.slots:
                if slot.day != day.weekday() or (slot.first and day < slot.first):
                    continue
                if day in slot.skip or self._closed(day, slot.start, slot.end):
                    continue
                if not slot.attending and not include_not_attending:
                    continue
                result.append(
                    Occurrence(
                        course,
                        slot,
                        datetime.combine(day, slot.start, self.timezone),
                        datetime.combine(day, slot.end, self.timezone),
                    )
                )
        return sorted(result, key=lambda o: o.start)

    def match(self, start: datetime, duration: timedelta) -> Course | None:
        """The attended course whose class overlaps [start, start + duration] the most.

        Classes are widened by 15 minutes on each side, because lecturers start late
        and recordings start early. Naive datetimes are read in the catalog's timezone.
        """
        if start.tzinfo is None:
            start = start.replace(tzinfo=self.timezone)
        start = start.astimezone(self.timezone)
        end = start + duration
        best, best_overlap = None, timedelta(0)
        day = start.date()
        while day <= end.date():
            for occ in self.occurrences(day):
                overlap = min(end, occ.end + TOLERANCE) - max(start, occ.start - TOLERANCE)
                if overlap > best_overlap:
                    best, best_overlap = occ.course, overlap
            day += timedelta(days=1)
        return best

    def current(self, now: datetime) -> Occurrence | None:
        """The attended class running at `now`, if any (no tolerance)."""
        now = now.astimezone(self.timezone)
        return next((o for o in self.occurrences(now.date()) if o.start <= now < o.end), None)

    def upcoming_exams(self, today: date, days: int = 30) -> list[tuple[Course, Exam]]:
        found = [
            (course, exam)
            for course in self.courses
            for exam in course.exams
            if today <= exam.date <= today + timedelta(days=days)
        ]
        return sorted(found, key=lambda pair: (pair[1].date, pair[1].start or time.min))


# --- loading -------------------------------------------------------------------


def _time(value: str, where: str) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where}: bad time {value!r}, expected HH:MM") from exc


def _date(value, where: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where}: bad date {value!r}, expected YYYY-MM-DD") from exc


def _slot(raw: dict, where: str) -> Slot:
    day = str(raw.get("day", "")).lower()[:3]
    if day not in DAYS:
        raise ConfigError(f"{where}: day must be one of {', '.join(DAYS)}")
    start, end = _time(raw.get("start"), where), _time(raw.get("end"), where)
    if end <= start:
        raise ConfigError(f"{where}: end must be after start")
    return Slot(
        day=DAYS.index(day),
        start=start,
        end=end,
        kind=raw.get("kind", "lecture"),
        location=raw.get("location"),
        first=_date(raw["first"], where) if raw.get("first") else None,
        skip=frozenset(_date(d, where) for d in raw.get("skip", [])),
        attending=bool(raw.get("attending", True)),
    )


def _course(raw: dict, index: int) -> Course:
    where = f"courses[{index}]"
    for key in ("code", "name", "folder"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ConfigError(f"{where}: '{key}' is required")
    exams = []
    for j, e in enumerate(raw.get("exams", [])):
        w = f"{where}.exams[{j}]"
        exams.append(
            Exam(
                date=_date(e.get("date"), w),
                title=str(e.get("title", "Exam")),
                start=_time(e["start"], w) if e.get("start") else None,
                end=_time(e["end"], w) if e.get("end") else None,
            )
        )
    topics = [
        Topic(_date(t.get("week_of"), f"{where}.topics[{j}]"), str(t.get("title", "")))
        for j, t in enumerate(raw.get("topics", []))
    ]
    return Course(
        code=raw["code"].strip(),
        name=raw["name"].strip(),
        folder=raw["folder"].strip(),
        aliases=tuple(str(a).lower() for a in raw.get("aliases", [])),
        moodle_id=raw.get("moodle_id"),
        language=raw.get("language", "en"),
        syllabus=raw.get("syllabus"),
        slots=tuple(_slot(s, f"{where}.slots[{j}]") for j, s in enumerate(raw.get("slots", []))),
        exams=tuple(exams),
        topics=tuple(topics),
    )


def load_catalog(path: Path) -> Catalog:
    """Parse courses.toml. A missing file is an empty catalog."""
    if not path.exists():
        return Catalog()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    closures = []
    for j, c in enumerate(raw.get("closures", [])):
        w = f"closures[{j}]"
        closures.append(
            Closure(
                date=_date(c.get("date"), w),
                start=_time(c["start"], w) if c.get("start") else None,
                end=_time(c["end"], w) if c.get("end") else None,
            )
        )
    try:
        tz = ZoneInfo(raw.get("timezone", "UTC"))
    except Exception as exc:  # zoneinfo raises several types for unknown keys
        raise ConfigError(f"unknown timezone {raw.get('timezone')!r}") from exc
    return Catalog(
        courses=tuple(_course(c, i) for i, c in enumerate(raw.get("courses", []))),
        timezone=tz,
        term_end=_date(raw["term_end"], "term_end") if raw.get("term_end") else None,
        closures=tuple(closures),
    )


class CatalogFile:
    """courses.toml in the data root, re-read when it changes on disk."""

    def __init__(self, data_root: Path | None) -> None:
        self.path = data_root / "courses.toml" if data_root else None
        self._mtime: float | None = None
        self._catalog = Catalog()

    def get(self) -> Catalog:
        if self.path is None or not self.path.exists():
            self._mtime, self._catalog = None, Catalog()
            return self._catalog
        mtime = self.path.stat().st_mtime
        if mtime != self._mtime:
            self._catalog = load_catalog(self.path)
            self._mtime = mtime
        return self._catalog
