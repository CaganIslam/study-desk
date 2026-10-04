import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from studydesk.ai.runner import FakeRunner
from studydesk.config import Config
from studydesk.courses import Catalog, Course
from studydesk.ingest import moodle
from studydesk.server import create_app
from studydesk.study.commands import parse
from tests.fake_moodle import TOKEN, FakeMoodle
from tests.pdfgen import make_pdf
from tests.test_study_api import explained

IST = ZoneInfo("Europe/Istanbul")
IN_CLASS = datetime(2026, 10, 6, 9, 30, tzinfo=IST)  # a Tuesday, CS 101 runs 09:00-11:00
COURSES = """timezone = "Europe/Istanbul"
[[courses]]
code = "CS 101"
name = "Algorithms"
folder = "CS101"
moodle_id = 1
  [[courses.slots]]
  day = "tue"
  start = "09:00"
  end = "11:00"
[[courses]]
code = "CS 202"
name = "Systems"
folder = "CS202"
"""


@pytest.fixture
def live_env(home, tmp_path):
    data = tmp_path / "data"
    slides = data / "CS101" / "slides"
    slides.mkdir(parents=True)
    (slides / "Lec1.pdf").write_bytes(make_pdf([["Old", "A 1"], ["Old 2", "A 2"]]))
    (slides / "Lec2.pdf").write_bytes(make_pdf([["New", "A 1"], ["New 2", "A 2"]]))
    old = (slides / "Lec1.pdf").stat()
    os.utime(slides / "Lec1.pdf", (old.st_atime, old.st_mtime - 3600))
    (data / "courses.toml").write_text(COURSES)
    clock = {"now": IN_CLASS}
    fake = FakeMoodle()
    runner = FakeRunner(results=[explained] * 20)
    app = create_app(
        Config(home=home, data_root=data, moodle_url="https://moodle.test"),
        now=lambda: clock["now"],
        runner=runner,
        moodle_client=lambda: moodle.MoodleClient("https://moodle.test", TOKEN, opener=fake),
    )
    return TestClient(app), app, clock, runner


def test_live_opens_the_newest_deck_of_the_class_running_now(live_env):
    client, app, clock, _ = live_env
    target = client.get("/api/live").json()
    assert set(target) == {"current", "course", "deck_id", "idx"}
    assert target["course"] == "CS 101" and target["current"]["code"] == "CS 101"
    deck = client.get(f"/api/decks/{target['deck_id']}/slides").json()["deck"]
    assert deck["filename"] == "Lec2.pdf" and target["idx"] == 1

    clock["now"] = IN_CLASS + timedelta(hours=5)
    assert client.get("/api/live").json() == {"current": None, "course": None, "deck_id": None, "idx": None}
    assert client.get("/api/live", params={"course": "CS 202"}).json()["deck_id"] is None


def test_live_explanations_use_the_faster_model(live_env):
    client, _, _, runner = live_env
    deck_id = client.get("/api/live").json()["deck_id"]
    client.post(f"/api/decks/{deck_id}/slides/1/explain", json={"level": "short", "live": True})
    client.post(f"/api/decks/{deck_id}/slides/2/explain", json={"level": "normal"})
    models = {c.text.split("Slide title: ")[1].split("\n")[0]: c.model for c in runner.calls}
    assert models["New"] == "sonnet" and models["New 2"] is None


def test_deckless_questions_are_kept_with_the_course(live_env):
    client, app, clock, _ = live_env
    clock["now"] = datetime.now(IST)  # stored rows carry the real time; list "today" in real time too
    app.state.runner = runner = FakeRunner(
        results=[{"kind": "answer", "answer_md": "Kısaca: bir sıralama.", "terms": [], "action": {"type": "none"}}]
    )
    body = client.post("/api/command", json={"text": "heap sort ne", "course_code": "CS 202", "live": True}).json()
    assert body["kind"] == "answer" and "id" in body["answer"]
    assert "CS 202 Systems" in runner.calls[0].text and runner.calls[0].model == "sonnet"
    listed = client.get("/api/courses/CS 202/deckless").json()["questions"]
    assert [q["question"] for q in listed] == ["heap sort ne"]


def test_live_syncs_moodle_more_often(live_env):
    client, app, _, _ = live_env
    with app.state.db.connect() as conn:
        five_minutes_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        conn.execute("INSERT INTO app_meta (key, value) VALUES ('moodle.last_sync', ?)", (five_minutes_ago,))
    assert client.post("/api/sync/moodle").json()["started"] is False
    assert client.post("/api/sync/moodle", params={"live": True}).json()["started"] is True
    app.state.jobs.join()


def test_live_command():
    catalog = Catalog(courses=(Course(code="CS 101", name="A", folder="x"),))
    assert parse("canlı", catalog).type == "live"
    assert parse("canlı moda geç", catalog).type == "live"
