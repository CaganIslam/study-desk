import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from studydesk.config import Config
from studydesk.courses import Catalog, Course
from studydesk.db import Database
from studydesk.ingest import moodle
from studydesk.jobs import JobQueue
from studydesk.server import create_app
from tests.fake_moodle import TOKEN, FakeMoodle

COURSES = (
    Course(code="CS 101", name="Algorithms", folder="CS101 Algorithms", moodle_id=1),
    Course(code="CS 202", name="Systems", folder="CS202 Systems", moodle_id=2),
    Course(code="CS 303", name="No Moodle", folder="CS303"),
)


@pytest.fixture
def env(tmp_path):
    fake = FakeMoodle()
    db = Database(tmp_path / "study.db")
    db.migrate()
    data = tmp_path / "data"
    client = moodle.MoodleClient("https://moodle.test", TOKEN, opener=fake)
    return fake, db, data, client


def run(env):
    fake, db, data, client = env
    return moodle.sync(db, Catalog(courses=COURSES), data, client)


def test_new_pdfs_are_downloaded(env):
    fake, _, data, _ = env
    fake.add_file(1, "Lec01.pdf", b"%PDF one")
    fake.add_file(1, "notes.zip", b"zip")
    result = run(env)
    assert result.new == ["CS 101/Lec01.pdf"]
    assert (data / "CS101 Algorithms" / "slides" / "Lec01.pdf").read_bytes() == b"%PDF one"
    assert not (data / "CS101 Algorithms" / "slides" / "notes.zip").exists()


def test_unchanged_files_are_not_downloaded_again(env):
    fake, *_ = env
    fake.add_file(1, "Lec01.pdf", b"%PDF one")
    run(env)
    fake.downloads.clear()
    result = run(env)
    assert result.new == [] and result.updated == [] and fake.downloads == []


def test_changed_file_is_updated(env):
    fake, _, data, _ = env
    fake.add_file(1, "Lec01.pdf", b"%PDF one", timemodified=1000)
    run(env)
    fake.add_file(1, "Lec01.pdf", b"%PDF one, fixed typo", timemodified=2000)
    result = run(env)
    assert result.updated == ["CS 101/Lec01.pdf"]
    assert (data / "CS101 Algorithms" / "slides" / "Lec01.pdf").read_bytes() == b"%PDF one, fixed typo"


def test_existing_identical_file_is_adopted(env):
    fake, _, data, _ = env
    slides = data / "CS101 Algorithms" / "slides"
    slides.mkdir(parents=True)
    (slides / "Lec01.pdf").write_bytes(b"%PDF one")
    fake.add_file(1, "Lec01.pdf", b"%PDF one")
    result = run(env)
    assert result.new == [] and fake.downloads == []


def test_unrelated_file_with_the_same_name_is_kept(env):
    fake, _, data, _ = env
    slides = data / "CS101 Algorithms" / "slides"
    slides.mkdir(parents=True)
    (slides / "Lec01.pdf").write_bytes(b"my own annotated copy")
    fake.add_file(1, "Lec01.pdf", b"%PDF one")
    result = run(env)
    assert (slides / "Lec01.pdf").read_bytes() == b"my own annotated copy"
    assert (slides / "Lec01 (Moodle).pdf").read_bytes() == b"%PDF one"
    assert result.new == ["CS 101/Lec01 (Moodle).pdf"]


def test_one_course_failing_does_not_stop_the_others(env):
    fake, *_ = env
    fake.down.add(1)
    fake.add_file(2, "Intro.pdf", b"%PDF intro")
    result = run(env)
    assert result.new == ["CS 202/Intro.pdf"]
    assert len(result.errors) == 1 and result.errors[0].startswith("CS 101")


def test_errors_never_contain_the_token(env):
    fake, db, data, _ = env
    bad = moodle.MoodleClient("https://moodle.test", "wrong-token", opener=fake)
    fake.down.add(2)
    result = moodle.sync(db, Catalog(courses=COURSES), data, bad)
    assert result.errors and all(TOKEN not in e and "wrong-token" not in e for e in result.errors)
    assert "Invalid token" in result.errors[0]


def test_token_from_environment(monkeypatch):
    monkeypatch.setenv("MOODLE_TOKEN", "from-env")
    assert moodle.get_token("https://moodle.test") == "from-env"


# --- API -------------------------------------------------------------------


@pytest.fixture
def api(home, tmp_path):
    fake = FakeMoodle()
    fake.add_file(1, "Lec01.pdf", b"%PDF one")
    data = tmp_path / "data"
    data.mkdir()
    (data / "courses.toml").write_text('[[courses]]\ncode = "CS 101"\nname = "A"\nfolder = "CS101"\nmoodle_id = 1\n')
    config = Config(home=home, data_root=data, moodle_url="https://moodle.test")
    app = create_app(config, moodle_client=lambda: moodle.MoodleClient("https://moodle.test", TOKEN, opener=fake))
    return TestClient(app), app, data


def test_sync_runs_in_background_and_reports(api):
    client, app, data = api
    body = client.post("/api/sync/moodle").json()
    assert set(body) == {"configured", "running", "last_sync", "last_result", "started"}
    assert body["started"] is True
    app.state.jobs.join()
    status = client.get("/api/sync/moodle").json()
    assert status["last_result"]["new"] == ["CS 101/Lec01.pdf"]
    assert status["last_sync"] is not None
    assert (data / "CS101" / "slides" / "Lec01.pdf").exists()


def test_recent_sync_is_not_repeated_unless_forced(api):
    client, app, _ = api
    client.post("/api/sync/moodle")
    app.state.jobs.join()
    assert client.post("/api/sync/moodle").json()["started"] is False
    assert client.post("/api/sync/moodle", params={"force": True}).json()["started"] is True
    app.state.jobs.join()


def test_not_configured_without_moodle_url(home):
    client = TestClient(create_app(Config(home=home)))
    body = client.post("/api/sync/moodle").json()
    assert body["configured"] is False and body["started"] is False


def test_missing_token_is_reported(home, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    app = create_app(Config(home=home, data_root=data, moodle_url="https://moodle.test"), moodle_client=lambda: None)
    client = TestClient(app)
    client.post("/api/sync/moodle")
    app.state.jobs.join()
    assert client.get("/api/sync/moodle").json()["last_result"]["errors"] == ["moodle_token_missing"]


# --- job queue ---------------------------------------------------------------


def test_job_queue_skips_duplicates_and_survives_failures():
    jobs = JobQueue()
    gate, ran = threading.Event(), []
    jobs.submit("slow", gate.wait)
    assert jobs.submit("slow", lambda: ran.append("dup")) is False
    jobs.submit("boom", lambda: 1 / 0)
    jobs.submit("after", lambda: ran.append("after"))
    gate.set()
    jobs.join()
    assert ran == ["after"] and not jobs.busy("slow")
