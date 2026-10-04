from datetime import date, datetime, timedelta, timezone

import pytest

from studydesk.config import ConfigError
from studydesk.courses import CatalogFile, load_catalog
from tests.fixtures_courses import COURSES_TOML


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "courses.toml"
    path.write_text(COURSES_TOML)
    return load_catalog(path)


def at(day: str, hhmm: str, catalog):
    return datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=catalog.timezone)


def code(course):
    return course.code if course else None


def test_recording_inside_a_class(catalog):
    assert code(catalog.match(at("2026-10-06", "09:05", catalog), timedelta(minutes=50))) == "CS 101"


def test_back_to_back_classes_pick_the_larger_overlap(catalog):
    # 10:50-11:40 overlaps CS 101 (widened to 11:15) by 25 min and CS 202 (from 10:45) by 50 min.
    assert code(catalog.match(at("2026-10-06", "10:50", catalog), timedelta(minutes=50))) == "CS 202"


def test_tolerance_catches_an_early_start(catalog):
    assert code(catalog.match(at("2026-10-06", "08:50", catalog), timedelta(minutes=8))) == "CS 101"


def test_nothing_outside_the_tolerance(catalog):
    assert catalog.match(at("2026-10-06", "08:20", catalog), timedelta(minutes=20)) is None


def test_slot_not_attended_is_ignored_on_a_clash(catalog):
    # Thursday 13:00-15:00 has CS 202 (attended) and IE 303 (not attended).
    assert code(catalog.match(at("2026-10-01", "14:50", catalog), timedelta(minutes=50))) == "CS 202"


def test_skipped_date_and_closures(catalog):
    assert catalog.match(at("2026-11-03", "09:10", catalog), timedelta(minutes=30)) is None  # skip
    assert catalog.match(at("2026-10-29", "13:10", catalog), timedelta(minutes=30)) is None  # whole day
    assert catalog.match(at("2026-10-28", "13:10", catalog), timedelta(minutes=30)) is None  # afternoon


def test_first_date_and_term_end(catalog):
    assert catalog.match(at("2026-09-22", "09:10", catalog), timedelta(minutes=30)) is None
    assert catalog.occurrences(date(2026, 12, 15)) == []


def test_utc_timestamps_are_converted(catalog):
    # 06:05 UTC is 09:05 in Istanbul (UTC+3).
    start = datetime(2026, 10, 6, 6, 5, tzinfo=timezone.utc)
    assert code(catalog.match(start, timedelta(minutes=50))) == "CS 101"


def test_naive_timestamps_use_the_catalog_timezone(catalog):
    assert code(catalog.match(datetime(2026, 10, 6, 9, 5), timedelta(minutes=50))) == "CS 101"


def test_current_class(catalog):
    assert code(catalog.current(at("2026-10-02", "14:30", catalog)).course) == "IE 303"
    assert catalog.current(at("2026-10-02", "15:30", catalog)) is None


def test_topic_of_the_week(catalog):
    course = catalog.by_code("CS 101")
    assert course.topic_for(date(2026, 10, 7)).title == "Sorting"
    assert course.topic_for(date(2026, 10, 13)) is None


def test_upcoming_exams(catalog):
    exams = catalog.upcoming_exams(date(2026, 10, 20))
    assert [(c.code, e.title) for c, e in exams] == [("CS 101", "Midterm")]


@pytest.mark.parametrize(
    "bad, message",
    [
        ('[[courses]]\nname = "x"\nfolder = "x"\n', "code"),
        ('[[courses]]\ncode = "A"\nname = "x"\nfolder = "x"\n[[courses.slots]]\nday = "xyz"\nstart = "09:00"\nend = "10:00"\n', "day"),
        ('[[courses]]\ncode = "A"\nname = "x"\nfolder = "x"\n[[courses.slots]]\nday = "mon"\nstart = "10:00"\nend = "09:00"\n', "end"),
        ('timezone = "Mars/Olympus"\n', "timezone"),
    ],
)
def test_invalid_files_are_reported(tmp_path, bad, message):
    path = tmp_path / "courses.toml"
    path.write_text(bad)
    with pytest.raises(ConfigError, match=message):
        load_catalog(path)


def test_catalog_file_reloads_on_change(tmp_path):
    holder = CatalogFile(tmp_path)
    assert holder.get().courses == ()
    path = tmp_path / "courses.toml"
    path.write_text(COURSES_TOML)
    assert len(holder.get().courses) == 3
    path.write_text('[[courses]]\ncode = "Z"\nname = "z"\nfolder = "z"\n')
    import os

    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    assert [c.code for c in holder.get().courses] == ["Z"]
