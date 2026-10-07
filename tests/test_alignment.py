import pytest

from studydesk.ai.runner import FakeRunner
from studydesk.ingest import alignment
from studydesk.ingest.transcribe import Segment, Transcript
from tests.test_study_api import app_env, explain  # noqa: F401  (fixture reuse)


def add_recording(client, segments, duration=600.0):
    db = client.app_state.db
    with db.connect() as conn:
        rec_id = conn.execute(
            "INSERT INTO recordings (sha256, source_name, started_at, duration_s, course_code, status)"
            " VALUES ('x', 'lecture.qta', '2026-10-06T06:05:00+00:00', ?, 'CS 101', 'done')",
            (duration,),
        ).lastrowid
        conn.executemany(
            "INSERT INTO transcript_segments (recording_id, start_s, end_s, text) VALUES (?, ?, ?, ?)",
            [(rec_id, s.start, s.end, s.text) for s in segments],
        )
    return rec_id


SEGMENTS = [
    Segment(0, 50, "Today we talk about topic one."),
    Segment(60, 110, "This pivot thing will be on the midterm, remember it."),
    Segment(120, 170, "Now topic two, quickly."),
    Segment(180, 230, "Quiz next Wednesday, bring a cheat sheet."),
]
ANSWER = {
    "sections": [
        {"start": "00:00", "end": "02:00", "deck": "Lec1.pdf", "label": "1", "topic": ""},
        {"start": "02:00", "end": "03:00", "deck": "Lec1.pdf", "label": "2", "topic": ""},
        {"start": "03:00", "end": "04:00", "deck": "", "label": "", "topic": "Admin: quiz"},
        {"start": "04:00", "end": "05:00", "deck": "Nope.pdf", "label": "9", "topic": "unknown deck"},
    ],
    "emphasis": [
        {"at": "01:05", "kind": "exam", "quote": "The pivot is on the midterm."},
        {"at": "03:05", "kind": "admin", "quote": "Quiz next Wednesday; cheat sheet allowed."},
    ],
}


@pytest.fixture
def aligned(app_env):
    client, _, deck_id = app_env
    rec_id = add_recording(client, SEGMENTS)
    client.app_state.runner = FakeRunner(results=[ANSWER])
    stats = alignment.align(client.app_state.db, client.app_state.catalog.get(), client.app_state.runner, rec_id)
    return client, deck_id, rec_id, stats


def test_sections_and_emphasis_are_stored(aligned):
    client, deck_id, rec_id, stats = aligned
    assert stats == {"sections": 4, "slides": 2, "emphasis": 2}
    call = client.app_state.runner.calls[0]
    assert "Deck: Lec1.pdf" in call.text and "[01:00] This pivot thing" in call.text
    assert alignment.needing_realign(client.app_state.db, "CS 101") == [rec_id]


def test_lecturer_notes_and_emphasis_per_slide(aligned):
    client, deck_id, *_ = aligned
    db = client.app_state.db
    notes = alignment.lecturer_notes(db, deck_id, 1)
    assert "topic one" in notes and "midterm" in notes and "topic two" not in notes
    assert [e["kind"] for e in alignment.emphasis_for_slide(db, deck_id, 1)] == ["exam"]
    lecture = client.get(f"/api/decks/{deck_id}/slides/1/lecture").json()
    assert set(lecture) == {"notes", "emphasis", "recordings"} and lecture["recordings"][0]["at"] == "00:00"
    slides = client.get(f"/api/decks/{deck_id}/slides").json()["slides"]
    assert [s["emphasis"] for s in slides] == [1, 0, 0, 0]
    assert {e["kind"] for e in client.get("/api/emphasis").json()["emphasis"]} == {"exam", "admin"}


def test_explanations_use_the_lecturers_words_and_refresh_when_they_arrive(app_env):
    client, runner, deck_id = app_env
    explain(client, deck_id, 1)
    client.app_state.jobs.join()
    first = [c for c in runner.calls if "Slide title: Topic 1" in c.text]
    assert len(first) == 1 and "What the lecturer said" not in first[0].text
    rec_id = add_recording(client, SEGMENTS)
    alignment.align(client.app_state.db, client.app_state.catalog.get(), FakeRunner(results=[ANSWER]), rec_id)
    body = explain(client, deck_id, 1).json()
    assert body["cached"] is False, "the explanation made before the recording is stale now"
    latest = [c for c in runner.calls if "Slide title: Topic 1" in c.text][-1]
    assert "What the lecturer said on this slide" in latest.text and "midterm" in latest.text
    assert explain(client, deck_id, 1).json()["cached"] is True


def test_time_parsing():
    assert alignment.seconds_of("75:30") == 4530 and alignment.seconds_of("1:02:03") == 3723
    assert alignment.seconds_of("soon") is None and alignment.mmss(4530) == "75:30"
