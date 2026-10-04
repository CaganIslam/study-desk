from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from studydesk.config import Config
from studydesk.ingest import recordings
from studydesk.ingest.transcribe import Segment, Transcript, check, markdown
from studydesk.server import create_app
from tests.test_live import COURSES

TUESDAY_0905_UTC = datetime(2026, 10, 6, 6, 5, tzinfo=timezone.utc)  # 09:05 in Istanbul, CS 101 runs 09:00-11:00
SUNDAY_UTC = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def good(seconds=600):
    return Transcript([Segment(i * 10.0, i * 10.0 + 9, f"sentence number {i} about sorting") for i in range(int(seconds // 10))], "turbo", 1.0)


def looping(seconds=600):
    first = [Segment(0, 9, "fine start")]
    loop = [Segment(10 + i * 10.0, 19 + i * 10.0, "the truth value to the truth value", 29.9) for i in range(int(seconds // 10) - 1)]
    return Transcript(first + loop, "turbo", 1.0)


# --- quality check -------------------------------------------------------------


def test_good_transcript_passes():
    quality = check(good(), 600)
    assert quality.ok and quality.stats["covered_ratio"] > 0.8


def test_repetition_loop_is_caught():
    assert check(looping(), 600).reasons == ["repetition_loop"]


def test_lost_minutes_are_caught():
    assert "missing_minutes" in check(good(120), 600).reasons


def test_markdown_has_minute_stamps():
    import re

    text = markdown(good(180), "CS 101 lecture")
    assert text.startswith("# CS 101 lecture") and text.count("\n[") + text.startswith("[") >= 2
    assert re.search(r"^\[00:00\] ", text, re.M) and re.search(r"^\[01:\d\d\] ", text, re.M)


# --- API -------------------------------------------------------------------------


@pytest.fixture
def rec_env(home, tmp_path):
    data = tmp_path / "data"
    (data / "CS101").mkdir(parents=True)
    (data / "courses.toml").write_text(COURSES)
    app = create_app(Config(home=home, data_root=data))
    # The scenario is in the file's bytes: uploads are stored under random names.
    app.state.probe_fn = lambda path: (SUNDAY_UTC if path.read_bytes().startswith(b"sunday") else TUESDAY_0905_UTC, 600.0)
    results = {"next": good}

    def fake_transcribe(audio, language="en", model="turbo"):
        return results["next"]()

    app.state.transcribe_fn = fake_transcribe

    client = TestClient(app)

    def upload(name, content=b"tuesday lecture"):
        return client.post("/api/recordings", files=[("files", (name, content, "audio/x-m4a"))])

    return client, app, data, home, upload, results


def wait(app):
    app.state.transcriber.join()


def test_drop_a_recording_and_get_a_transcript(rec_env):
    client, app, data, home, upload, _ = rec_env
    body = upload("lecture.qta").json()["recordings"][0]
    assert (body["status"], body["course"]) == ("queued", "CS 101")
    wait(app)
    listed = client.get("/api/recordings").json()["recordings"][0]
    assert set(listed) >= {"id", "started", "minutes", "course", "status", "reasons", "has_audio"}
    assert listed["status"] == "done" and listed["has_audio"] is False
    files = list((data / "CS101" / "transcripts").glob("*.md"))
    assert len(files) == 1 and files[0].name == "2026-10-06-0905.md"
    assert "sorting" in client.get(f"/api/recordings/{listed['id']}/transcript").json()["markdown"]
    assert not list((home / "inbox").glob("*")), "the app's copy of the audio is deleted once transcribed"


def test_same_recording_twice_is_not_added_again(rec_env):
    client, app, _, home, upload, _ = rec_env
    upload("lecture.qta")
    second = upload("lecture-copy.qta").json()["recordings"][0]
    wait(app)
    assert second["status"] == "duplicate" and len(client.get("/api/recordings").json()["recordings"]) == 1


def test_broken_transcript_is_reported_and_can_be_retried(rec_env):
    client, app, data, home, upload, results = rec_env
    results["next"] = looping
    rec_id = upload("lecture.qta").json()["recordings"][0]["id"]
    wait(app)
    listed = client.get("/api/recordings").json()["recordings"][0]
    assert (listed["status"], listed["reasons"], listed["has_audio"]) == ("bad_quality", ["repetition_loop"], True)
    results["next"] = good
    assert client.post(f"/api/recordings/{rec_id}/retry", json={"model": "large"}).json()["status"] == "queued"
    wait(app)
    assert client.get("/api/recordings").json()["recordings"][0]["status"] == "done"
    assert client.post(f"/api/recordings/{rec_id}/retry", json={"model": "large"}).json()["error"]["code"] == "audio_gone"


def test_recording_outside_class_asks_for_the_course(rec_env):
    client, app, data, _, upload, _ = rec_env
    body = upload("sunday.m4a", b"sunday walk").json()["recordings"][0]
    assert body["status"] == "needs_course"
    client.post(f"/api/recordings/{body['id']}/course", json={"course": "CS 101"})
    wait(app)
    assert client.get("/api/recordings").json()["recordings"][0]["status"] == "done"


def test_discard_and_non_audio(rec_env):
    client, app, _, home, upload, results = rec_env
    results["next"] = looping
    rec_id = upload("lecture.qta").json()["recordings"][0]["id"]
    wait(app)
    client.delete(f"/api/recordings/{rec_id}")
    assert client.get("/api/recordings").json()["recordings"] == []
    assert not list((home / "inbox").glob("*"))
    assert upload("notes.txt").json()["recordings"][0]["status"] == "not_audio"


def test_cli_import_reads_but_never_deletes(rec_env, tmp_path, monkeypatch, capsys):
    client, app, data, home, _, _ = rec_env
    from studydesk import __main__ as entry
    from studydesk.config import Config

    folder = tmp_path / "kayitlar"
    folder.mkdir()
    (folder / "New Recording 1.qta").write_bytes(b"one")
    monkeypatch.setattr(entry, "load_config", lambda: Config(home=home, data_root=data))
    monkeypatch.setattr(recordings, "probe", lambda path: (TUESDAY_0905_UTC, 600.0))
    monkeypatch.setattr(recordings.tr, "transcribe", lambda audio, language="en", model="turbo": good())
    entry.main(["import-recordings", str(folder)])
    assert "CS 101: done" in capsys.readouterr().out
    assert (folder / "New Recording 1.qta").exists()
