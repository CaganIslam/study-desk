from datetime import datetime, timedelta, timezone

from studydesk.courses import Catalog, Course
from studydesk.study import questions, sessions
from studydesk.study.commands import parse
from tests.test_study_api import app_env, explain  # noqa: F401  (fixture reuse)

T0 = datetime(2026, 10, 6, 7, 0, tzinfo=timezone.utc)


def db_of(client):
    return client.app_state.db


def test_resume_point_per_course_and_overall(app_env):
    client, _, deck_id = app_env
    db = db_of(client)
    sessions.record_view(db, deck_id, 1, T0)
    sessions.record_view(db, deck_id, 3, T0 + timedelta(minutes=2))
    last = sessions.resume(db, "CS 101")
    assert (last["deck_id"], last["idx"], last["label"], last["title"]) == (deck_id, 3, "3", "Topic 3")
    assert sessions.resume(db)["idx"] == 3
    assert sessions.resume(db, "NOPE") is None


def test_sessions_split_on_a_long_gap(app_env):
    client, _, deck_id = app_env
    db = db_of(client)
    for minutes, idx in [(0, 1), (5, 2), (12, 2), (60, 3)]:
        sessions.record_view(db, deck_id, idx, T0 + timedelta(minutes=minutes))
    found = sessions.sessions(db)
    assert [s.views for s in found] == [[(deck_id, 1), (deck_id, 2)], [(deck_id, 3)]]
    assert found[0].minutes == 12


def test_notes_are_written_once_after_the_session_ends(app_env, tmp_path):
    client, _, deck_id = app_env
    db = db_of(client)
    data = client.app_state.config.data_root
    catalog = client.app_state.catalog.get()
    explain(client, deck_id, 1)
    client.app_state.jobs.join()
    start = datetime.now(timezone.utc)
    sessions.record_view(db, deck_id, 1, start)
    questions.add(db, deck_id, 1, "pivot nedir", "Bir eleman. Uzun açıklama.", [], "CS 101")
    client.put(f"/api/decks/{deck_id}/slides/1/marks/known")
    sessions.record_view(db, deck_id, 2, start + timedelta(seconds=5))
    assert sessions.write_due_notes(db, catalog, data, now=start + timedelta(minutes=10)) == []
    written = sessions.write_due_notes(db, catalog, data, now=start + timedelta(minutes=45))
    assert len(written) == 1 and written[0].parent == data / "CS101" / "notes"
    text = written[0].read_text()
    assert "1. Topic 1 ✓" in text and "**pivot nedir** (1. slayt) Bir eleman." in text
    assert "remember this" in text and "**pivot** - eksen" in text
    assert sessions.write_due_notes(db, catalog, data, now=start + timedelta(minutes=90)) == []


def test_search_folds_turkish_letters(app_env):
    client, _, deck_id = app_env
    db = db_of(client)
    questions.add(db, deck_id, 2, "Düzenlileştirme ne işe yarar?", "Aşırı öğrenmeyi azaltır.", [], "CS 101")
    found = sessions.search(db, "duzenlilestirme")
    assert [(r["kind"], r["idx"], r["label"]) for r in found] == [("question", 2, "2")]
    assert sessions.search(db, "asiri ogrenme")[0]["idx"] == 2
    assert sessions.search(db, "") == []


def test_explanations_are_searchable(app_env):
    client, _, deck_id = app_env
    explain(client, deck_id, 3)
    client.app_state.jobs.join()
    found = sessions.search(db_of(client), "topic 3")
    assert found and found[0]["kind"] == "explanation" and found[0]["idx"] == 3


CATALOG = Catalog(courses=(Course(code="CS 101", name="Algorithms", folder="x", aliases=("101",)),))


def test_parser_knows_resume_summary_and_search():
    assert parse("nerede kaldık", CATALOG).type == "resume"
    assert parse("kaldığım yer", CATALOG).type == "resume"
    assert parse("bugün ne çalıştım", CATALOG).type == "today_summary"
    found = parse("regularization nerede geçti", CATALOG)
    assert (found.type, found.query) == ("search", "regularization")
    assert parse("ara pivot", CATALOG).query == "pivot"


def test_commands_through_the_api(app_env):
    client, _, deck_id = app_env
    client.post("/api/activity", json={"deck_id": deck_id, "idx": 3})
    command = lambda text: client.post("/api/command", json={"text": text}).json()["action"]  # noqa: E731
    assert command("nerede kaldık") == {"type": "open", "course": "CS 101", "deck_id": deck_id, "idx": 3}
    assert command("101 aç") == {"type": "open", "course": "CS 101", "deck_id": deck_id, "idx": 3}
    summary = command("bugün ne çalıştım")
    assert summary["type"] == "today_summary" and summary["sessions"][0]["course"] == "CS 101"
    assert set(summary["sessions"][0]) >= {"course", "start", "end", "minutes", "slides", "questions"}
    explain(client, deck_id, 3)
    client.app_state.jobs.join()
    search = command("topic 3 nerede geçti")
    assert search["type"] == "search" and search["results"][0]["idx"] == 3


def test_flow_study_close_reopen_lands_on_the_same_slide(app_env):
    client, _, deck_id = app_env
    for idx in (1, 2, 3):
        client.post("/api/activity", json={"deck_id": deck_id, "idx": idx})
    assert client.get("/api/resume", params={"course": "CS 101"}).json()["resume"]["idx"] == 3
    assert client.post("/api/activity", json={"deck_id": deck_id, "idx": 99}).status_code == 404
    body = client.get("/api/sessions").json()
    assert set(body) == {"day", "sessions"} and body["sessions"][0]["slides"][-1]["label"] == "3"


def test_backfill_indexes_older_rows_once(app_env):
    client, _, deck_id = app_env
    db = db_of(client)
    explain(client, deck_id, 2)
    client.app_state.jobs.join()
    with db.connect() as conn:
        conn.execute("DELETE FROM search_index")
    assert sessions.backfill_index(db) >= 1
    assert sessions.search(db, "topic 2")
    assert sessions.backfill_index(db) == 0


def test_overview_shape_and_stats(app_env):
    client, _, deck_id = app_env
    explain(client, deck_id, 1)
    client.app_state.jobs.join()
    client.put(f"/api/decks/{deck_id}/slides/1/marks/known")
    client.post("/api/activity", json={"deck_id": deck_id, "idx": 1})
    client.post("/api/activity", json={"deck_id": deck_id, "idx": 2})
    body = client.get("/api/overview").json()
    assert set(body) == {"courses", "resume", "studied_minutes_today"}
    course = body["courses"][0]
    assert set(course) == {"code", "name", "last_studied", "slides_viewed", "hard_terms", "known_terms"}
    assert (course["slides_viewed"], course["known_terms"], course["hard_terms"]) == (2, 1, 0)
    assert body["resume"]["idx"] == 2 and body["studied_minutes_today"] >= 1
