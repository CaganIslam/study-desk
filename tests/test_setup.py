"""First-run setup: the helpers in setup.py and the /api/setup routes, from an empty app directory."""

import io
import json
import time
import tomllib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from studydesk import setup
from studydesk.ai.runner import ClaudeError, FakeRunner
from studydesk.config import Config, load_config
from studydesk.courses import load_catalog
from studydesk.ingest import moodle
from studydesk.server import create_app
from tests.fake_moodle import TOKEN, FakeMoodle
from tests.pdfgen import make_pdf

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("Europe/Istanbul"))  # a Monday

PROPOSAL = {
    "slots": [
        {"day": "tue", "start": "09:00", "end": "11:00", "kind": "lecture", "location": "A1"},
        {"day": "xyz", "start": "09:00", "end": "11:00", "kind": "lecture", "location": ""},  # dropped
        {"day": "fri", "start": "14:00", "end": "13:00", "kind": "ps", "location": ""},  # dropped: ends first
    ],
    "exams": [{"date": "2026-11-10", "title": "Midterm", "start": "18:00"}, {"date": "10/11", "title": "Bad", "start": ""}],
    "topics": [{"week_of": "2026-10-05", "title": "Sorting"}, {"week_of": "2026-10-12", "title": ""}],
    "term_end": "2026-12-11",
    "hours_inferred": False,
    "notes": "",
}


@pytest.fixture
def keychain(monkeypatch):
    """The Keychain, in memory: tests never touch the real one."""
    saved: dict[str, str] = {}
    monkeypatch.delenv("MOODLE_TOKEN", raising=False)
    monkeypatch.setattr(moodle, "get_token", lambda url: saved.get(url))
    monkeypatch.setattr(moodle, "set_token", lambda url, token: saved.__setitem__(url, token))
    return saved


@pytest.fixture
def fake_moodle():
    fake = FakeMoodle()
    now = int(time.time())
    fake.enrolled = [
        {"id": 11, "shortname": "2025/2026-2 CS201.01", "fullname": "DATA STRUCTURES", "startdate": now - 400 * 86400, "enddate": now - 200 * 86400},
        {"id": 12, "shortname": "2026/2027-1 CS101.01", "fullname": "INTRODUCTION TO ALGORITHMS", "startdate": now - 30 * 86400, "enddate": now + 90 * 86400},
        {"id": 13, "shortname": "2026/2027-1 MATH  210.02", "fullname": "LINEAR ALGEBRA", "startdate": now - 30 * 86400, "enddate": 0},
    ]
    fake.add_file(12, "CS101_Syllabus.pdf", make_pdf([["CS101 Introduction to Algorithms", "Lectures: Tuesday 09:00-11:00, room A1", "Midterm: 10 November 2026"]]))
    fake.add_file(12, "Lecture01.pdf", make_pdf([["Sorting"]]))
    return fake


def make_client(home, fake_moodle, runner=None, restarts=None):
    app = create_app(
        Config(home=home),
        now=lambda: NOW,
        runner=runner or FakeRunner(),
        moodle_factory=lambda url, token: moodle.MoodleClient(url, token, opener=fake_moodle),
    )
    if restarts is not None:
        app.state.on_restart = lambda: restarts.append(1)
    return TestClient(app)


# --- helpers ---------------------------------------------------------------------


def test_toml_round_trip_keeps_every_value():
    data = {
        "timezone": "Europe/Istanbul",
        "term_end": date(2026, 12, 11),
        "note": 'quotes " and \\ and ünicode ğış',
        "courses": [
            {
                "code": "CS 101",
                "aliases": ["101", "algo"],
                "moodle_id": 12,
                "slots": [{"day": "tue", "start": "09:00", "end": "11:00", "skip": ["2026-11-03"], "attending": False}],
                "topics": [{"week_of": "2026-10-05", "title": "Sorting"}],
            },
            {"code": "CS 202", "aliases": []},
        ],
        "moodle": {"url": "https://moodle.test"},
        "weird key": 1.5,
    }
    assert tomllib.loads(setup.dumps(data)) == data


@pytest.mark.parametrize(
    "pasted, expected",
    [
        ("moodle.school.edu", "https://moodle.school.edu"),
        ("https://moodle.school.edu/", "https://moodle.school.edu"),
        ("https://moodle.school.edu/my/", "https://moodle.school.edu"),
        ("https://school.edu/moodle/login/index.php?x=1", "https://school.edu/moodle"),
        ("  http://moodle.local:8080  ", "http://moodle.local:8080"),
    ],
)
def test_moodle_address_is_normalised(pasted, expected):
    assert setup.normalise_url(pasted) == expected


def test_course_code_and_name_are_guessed_from_moodle():
    assert setup.guess_code("2026/2027-1 CS101.01", "INTRODUCTION TO ALGORITHMS") == "CS 101"
    assert setup.guess_code("2026/2027-1 MATH  210.02", "LINEAR ALGEBRA") == "MATH 210"
    assert setup.guess_name("INTRODUCTION TO ALGORITHMS", "CS 101") == "Introduction to Algorithms"
    assert setup.guess_name("CS 101 Algorithms", "CS 101") == "Algorithms"
    assert setup.folder_for("CS 101", "Data/Structures") == "CS101 Data-Structures"


def test_proposal_keeps_only_values_the_schedule_file_can_hold():
    clean = setup.clean_proposal(PROPOSAL)
    assert clean["slots"] == [{"day": "tue", "start": "09:00", "end": "11:00", "kind": "lecture", "location": "A1"}]
    assert [e["title"] for e in clean["exams"]] == ["Midterm"]
    assert [t["title"] for t in clean["topics"]] == ["Sorting"]
    assert clean["term_end"] == "2026-12-11"


def test_saving_courses_keeps_schedules_and_drops_unlisted_courses(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "courses.toml").write_text(
        'timezone = "Europe/Istanbul"\n'
        '[[courses]]\ncode = "CS 101"\nname = "Algorithms"\nfolder = "CS101 Algorithms"\nmoodle_id = 12\n'
        '  [[courses.slots]]\n  day = "tue"\n  start = "09:00"\n  end = "11:00"\n  attending = false\n'
        '[[courses]]\ncode = "OLD 1"\nname = "Old"\nfolder = "OLD1"\n'
    )
    setup.save_courses(
        data,
        [
            {"code": "CS 101", "name": "Algorithms!", "folder": "CS101 Algorithms", "aliases": ["101"], "language": "en", "moodle_id": 12},
            {"code": "MATH 210", "name": "Linear Algebra", "folder": "", "aliases": [], "language": "tr", "moodle_id": None},
        ],
    )
    catalog = load_catalog(data / "courses.toml")
    assert [c.code for c in catalog.courses] == ["CS 101", "MATH 210"]
    cs = catalog.by_code("CS 101")
    assert cs.name == "Algorithms!" and cs.moodle_id == 12 and cs.slots[0].attending is False
    assert catalog.by_code("MATH 210").folder == "MATH210 Linear Algebra"
    assert (data / "MATH210 Linear Algebra" / "slides").is_dir()
    with pytest.raises(setup.SetupError):
        setup.save_courses(data, [{"code": "A 1", "name": "A", "folder": "X"}, {"code": "A 1", "name": "B", "folder": "Y"}])
    with pytest.raises(setup.SetupError):
        setup.save_courses(data, [{"code": "A 1", "name": "A", "folder": "../outside"}])


def test_a_schedule_the_app_cannot_read_is_not_saved(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    setup.save_courses(data, [{"code": "CS 101", "name": "Algorithms", "folder": "CS101"}])
    before = (data / "courses.toml").read_text()
    with pytest.raises(Exception):
        setup.save_schedule(data, "CS 101", [{"day": "tue", "start": "11:00", "end": "09:00"}], [], [], None)
    assert (data / "courses.toml").read_text() == before


# --- API: first run to a working app ----------------------------------------------


def test_first_run_status(home, keychain, fake_moodle):
    client = make_client(home, fake_moodle)
    state = client.get("/api/setup").json()
    assert state["complete"] is False
    assert state["folder"]["data_root"] is None and state["folder"]["suggested"]
    assert {"code": "tr", "name": "Turkish"} in state["folder"]["languages"]
    assert state["moodle"] == {"url": None, "token_saved": False}
    assert state["courses"] == [] and state["restart_pending"] is False
    health = client.get("/api/health").json()
    assert health["setup_complete"] is False and isinstance(health["boot"], str)


def test_choosing_the_folder_writes_config_and_asks_for_a_restart(home, keychain, fake_moodle, tmp_path):
    home.mkdir(parents=True)
    (home / "config.toml").write_text('port = 5000\n[models]\nlive = "fast"\n')
    restarts = []
    client = make_client(home, fake_moodle, restarts=restarts)
    folder = tmp_path / "Courses"
    response = client.post("/api/setup/folder", json={"data_root": str(folder), "language": "en"})
    assert response.status_code == 200 and response.json()["restart"] is True
    assert restarts == [1] and folder.is_dir()
    config = load_config()
    assert (config.data_root, config.language, config.port, config.model_live) == (folder, "en", 5000, "fast")
    assert client.get("/api/setup").json()["restart_pending"] is True


@pytest.mark.parametrize("path, code", [("relative/path", "folder_not_absolute"), ("", "folder_not_absolute")])
def test_bad_folder_is_refused(home, keychain, fake_moodle, path, code):
    client = make_client(home, fake_moodle)
    response = client.post("/api/setup/folder", json={"data_root": path})
    assert response.status_code == 400 and response.json()["error"]["code"] == code
    assert not (home / "config.toml").exists()


def test_folder_browser_lists_subfolders(home, keychain, fake_moodle, tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "A").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    client = make_client(home, fake_moodle)
    body = client.get("/api/setup/dirs", params={"path": str(tmp_path)}).json()
    assert body["dirs"][:2] == ["A", "b"] and ".hidden" not in body["dirs"] and "file.txt" not in body["dirs"]
    missing = client.get("/api/setup/dirs", params={"path": str(tmp_path / "nope" / "deeper")}).json()
    assert missing["dirs"] == body["dirs"]  # a folder that does not exist yet opens its nearest parent
    assert client.get("/api/setup/dirs", params={"path": "relative"}).status_code == 404
    assert client.get("/api/setup/dirs").json()["path"] == "~"


def test_moodle_token_is_checked_then_kept_only_in_the_keychain(home, keychain, fake_moodle):
    client = make_client(home, fake_moodle)
    wrong = client.post("/api/setup/moodle", json={"url": "moodle.test", "token": "wrong"})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "moodle_invalid_token"
    assert keychain == {} and not (home / "config.toml").exists()

    missing = client.post("/api/setup/moodle", json={"url": "moodle.test", "token": ""})
    assert missing.json()["error"]["code"] == "moodle_token_missing"

    ok = client.post("/api/setup/moodle", json={"url": "https://moodle.test/my/", "token": f"  {TOKEN} "})
    assert ok.status_code == 200
    body = ok.json()
    assert (body["url"], body["site"], body["user"]) == ("https://moodle.test", "Test University", "Ada Student")
    assert keychain == {"https://moodle.test": TOKEN}
    assert load_config().moodle_url == "https://moodle.test"
    assert TOKEN not in (home / "config.toml").read_text() and TOKEN not in ok.text
    assert client.get("/api/setup").json()["moodle"] == {"url": "https://moodle.test", "token_saved": True}

    # A saved token is reused when the field is left empty.
    again = client.post("/api/setup/moodle", json={"url": "https://moodle.test", "token": ""})
    assert again.status_code == 200


def test_a_page_that_is_not_moodle_gives_a_clear_error(home, keychain):
    app = create_app(
        Config(home=home),
        runner=FakeRunner(),
        moodle_factory=lambda url, token: moodle.MoodleClient(url, token, opener=lambda req: io.BytesIO(b"<html>login</html>")),
    )
    response = TestClient(app).post("/api/setup/moodle", json={"url": "https://example.test", "token": "abc"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "moodle_not_found"


def test_moodle_courses_are_suggested_running_ones_first(home, keychain, fake_moodle):
    client = make_client(home, fake_moodle)
    client.post("/api/setup/moodle", json={"url": "https://moodle.test", "token": TOKEN})
    courses = client.get("/api/setup/moodle/courses").json()["courses"]
    assert [c["id"] for c in courses][-1] == 11  # last term's course comes last
    first = next(c for c in courses if c["id"] == 12)
    assert first["current"] is True
    assert first["suggested"] == {"code": "CS 101", "name": "Introduction to Algorithms", "folder": "CS101 Introduction to Algorithms", "aliases": ["101"]}


def test_moodle_can_be_removed(home, keychain, fake_moodle):
    client = make_client(home, fake_moodle)
    client.post("/api/setup/moodle", json={"url": "https://moodle.test", "token": TOKEN})
    assert client.delete("/api/setup/moodle").status_code == 200
    assert load_config().moodle_url is None
    assert client.get("/api/setup/moodle/courses").status_code == 409


def test_whole_setup_journey_ends_in_a_working_app(home, keychain, fake_moodle, tmp_path):
    runner = FakeRunner(results=[PROPOSAL])
    client = make_client(home, fake_moodle, runner=runner)
    data = tmp_path / "Courses"
    client.post("/api/setup/folder", json={"data_root": str(data), "language": "tr"})
    client.post("/api/setup/moodle", json={"url": "https://moodle.test", "token": TOKEN})
    suggestion = next(c for c in client.get("/api/setup/moodle/courses").json()["courses"] if c["id"] == 12)
    saved = client.post(
        "/api/setup/courses",
        json={"courses": [{**suggestion["suggested"], "language": "en", "moodle_id": 12}, {"code": "HIST 100", "name": "History", "aliases": []}]},
    )
    assert saved.status_code == 200 and saved.json()["complete"] is True
    assert (data / "HIST100 History" / "slides").is_dir()

    # The server restarts after the folder and Moodle steps; a new app reads the new config.
    app = create_app(
        load_config(), now=lambda: NOW, runner=runner, moodle_factory=lambda url, token: moodle.MoodleClient(url, token, opener=fake_moodle)
    )
    client = TestClient(app)
    assert client.get("/api/health").json()["setup_complete"] is True
    client.post("/api/sync/moodle", params={"force": True})
    app.state.jobs.join()

    pdfs = client.get("/api/setup/courses/CS 101/pdfs").json()["pdfs"]
    assert pdfs[0] == {"file": "slides/CS101_Syllabus.pdf", "size": pdfs[0]["size"], "syllabus": True}
    proposed = client.post("/api/setup/courses/CS 101/schedule/propose", json={"file": "slides/CS101_Syllabus.pdf"})
    assert proposed.status_code == 200
    proposal = proposed.json()["proposal"]
    assert len(proposal["slots"]) == 1
    call = runner.calls[-1]
    assert "Tuesday 09:00-11:00" in call.text and "Today: 2026-10-05 (mon)" in call.text
    assert "Turkish" in call.system

    stored = client.put(
        "/api/setup/courses/CS 101/schedule",
        json={"slots": proposal["slots"], "exams": proposal["exams"], "topics": proposal["topics"], "syllabus": "slides/CS101_Syllabus.pdf"},
    )
    assert stored.status_code == 200
    assert client.put("/api/setup/term", json={"term_end": proposal["term_end"]}).status_code == 200

    today = client.get("/api/today", params={"day": "2026-10-06"}).json()
    assert [(c["code"], c["start"], c["topic"]) for c in today["classes"]] == [("CS 101", "09:00", "Sorting")]
    assert [e["title"] for e in client.get("/api/today", params={"day": "2026-11-01"}).json()["exams"]] == ["Midterm"]
    courses = {c["code"]: c for c in client.get("/api/courses").json()["courses"]}
    assert courses["CS 101"]["has_syllabus"] is True
    decks = client.get("/api/courses/CS 101/decks").json()["decks"]
    assert len(decks) == 2
    assert TOKEN not in (data / "courses.toml").read_text()
    assert TOKEN.encode() not in (home / "study.db").read_bytes()


def test_course_pdfs_can_be_added_from_the_page(home, keychain, fake_moodle, tmp_path):
    client = make_client(home, fake_moodle)
    client.post("/api/setup/folder", json={"data_root": str(tmp_path / "data")})
    client.post("/api/setup/courses", json={"courses": [{"code": "HIST 100", "name": "History"}]})
    pdf = make_pdf([["Syllabus", "Mondays 10:00-12:00"]])
    added = client.post("/api/setup/courses/HIST 100/pdfs", files={"file": ("syllabus.pdf", pdf, "application/pdf")})
    assert added.json()["file"] == "slides/syllabus.pdf"
    again = client.post("/api/setup/courses/HIST 100/pdfs", files={"file": ("syllabus.pdf", make_pdf([["other"]]), "application/pdf")})
    assert again.json()["file"] == "slides/syllabus (2).pdf"
    not_pdf = client.post("/api/setup/courses/HIST 100/pdfs", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert not_pdf.status_code == 400 and not_pdf.json()["error"]["code"] == "not_pdf"
    outside = client.post("/api/setup/courses/HIST 100/schedule/propose", json={"file": "../../etc/passwd"})
    assert outside.status_code == 404
    opened = []
    client.app.state.reveal_fn = opened.append
    assert client.post("/api/setup/courses/HIST 100/reveal").status_code == 200 and opened


def test_scanned_syllabus_without_text_is_reported(home, keychain, fake_moodle, tmp_path):
    client = make_client(home, fake_moodle)
    client.post("/api/setup/folder", json={"data_root": str(tmp_path / "data")})
    client.post("/api/setup/courses", json={"courses": [{"code": "HIST 100", "name": "History"}]})
    client.post("/api/setup/courses/HIST 100/pdfs", files={"file": ("s.pdf", make_pdf([[]]), "application/pdf")})
    response = client.post("/api/setup/courses/HIST 100/schedule/propose", json={"file": "slides/s.pdf"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "syllabus_no_text"


def test_course_steps_need_the_folder_first(home, keychain, fake_moodle):
    client = make_client(home, fake_moodle)
    response = client.post("/api/setup/courses", json={"courses": [{"code": "A 1", "name": "A"}]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "data_root_missing"


def test_claude_check(home, keychain, fake_moodle):
    ok = make_client(home, fake_moodle, runner=FakeRunner(results=[{"ok": True}])).get("/api/setup/check/claude").json()
    assert ok == {"ok": True, "code": None, "message": None}
    runner = FakeRunner(results=[ClaudeError("not_logged_in", "Please run /login")])
    failed = make_client(home, fake_moodle, runner=runner).get("/api/setup/check/claude").json()
    assert failed["ok"] is False and failed["code"] == "not_logged_in"


def test_tools_check_shape(home, keychain, fake_moodle):
    body = make_client(home, fake_moodle).get("/api/setup/check/tools").json()
    assert set(body) == {"ffmpeg", "whisper", "whisper_model"} and all(isinstance(v, bool) for v in body.values())


def test_setup_page_strings_exist():
    strings = json.loads((Path(__file__).resolve().parents[1] / "src/studydesk/web/strings.tr.json").read_text())
    assert any(key.startswith("setup.") for key in strings)
