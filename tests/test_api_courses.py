"""Contract tests for /api/courses and /api/today: status, shape, field names."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from studydesk.config import Config
from studydesk.server import create_app
from tests.fixtures_courses import COURSES_TOML

IST = ZoneInfo("Europe/Istanbul")


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "data"
    (root / "CS101 Algorithms" / "slides").mkdir(parents=True)
    (root / "CS101 Algorithms" / "slides" / "syllabus.pdf").write_bytes(b"%PDF-1.4")
    (root / "courses.toml").write_text(COURSES_TOML)
    return root


def make_client(home, data_root, now=None):
    return TestClient(create_app(Config(home=home, data_root=data_root), now=now))


def test_courses_shape(home, data_root):
    body = make_client(home, data_root).get("/api/courses").json()
    assert body["configured"] is True
    course = body["courses"][0]
    assert set(course) == {"code", "name", "aliases", "folder", "language", "has_syllabus"}
    assert isinstance(course["aliases"], list) and isinstance(course["has_syllabus"], bool)
    assert {c["code"]: c["has_syllabus"] for c in body["courses"]}["CS 101"] is True


def test_courses_without_data_root(home):
    body = TestClient(create_app(Config(home=home))).get("/api/courses").json()
    assert body == {"configured": False, "courses": []}


def test_today_shape_and_current_class(home, data_root):
    client = make_client(home, data_root, now=lambda: datetime(2026, 10, 6, 9, 30, tzinfo=IST))
    body = client.get("/api/today").json()
    assert set(body) == {"date", "configured", "classes", "exams", "current"}
    assert set(body["classes"][0]) == {"code", "name", "kind", "start", "end", "location", "topic"}
    assert set(body["current"]) == {"code", "name", "start", "end"}
    assert body["current"]["code"] == "CS 101"
    assert body["classes"][0]["topic"] == "Sorting"


def test_today_for_another_day_has_no_current_class(home, data_root):
    client = make_client(home, data_root, now=lambda: datetime(2026, 10, 6, 9, 30, tzinfo=IST))
    body = client.get("/api/today", params={"day": "2026-10-20"}).json()
    assert body["current"] is None
    assert set(body["exams"][0]) == {"code", "name", "title", "date", "start", "days_left"}


def test_broken_courses_file_uses_error_shape(home, data_root):
    (data_root / "courses.toml").write_text('[[courses]]\nname = "no code"\nfolder = "x"\n')
    response = make_client(home, data_root).get("/api/courses")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "config_invalid"
