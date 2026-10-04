import json

from studydesk.ingest.history import import_history
from studydesk.study import sessions
from tests.test_study_api import app_env  # noqa: F401  (fixture reuse)

HISTORY = {
    "sessions": [
        {
            "course": "CS 101",
            "date": "2026-09-22",
            "time": "09:16-10:48",
            "deck": "Lec1.pdf",
            "slides_covered": [1, 2],
            "last_slide": 3,
            "questions": ["pivot nedir", "neden"],
            "terms": [{"en": "Pivot", "asked": True}, {"en": "Heap", "asked": True}, {"en": "array"}],
            "known": ["Heap"],
        },
        {"course": "CS 101", "date": "2026-09-23", "slides_covered": {"Lec1.pdf": [4], "Missing.pdf": [1]}},
        {"course": "NOPE 9", "date": "2026-09-24"},
    ]
}


def run(client):
    state = client.app_state
    return import_history(state.db, state.catalog.get(), state.config.data_root, json.loads(json.dumps(HISTORY)))


def test_import_creates_views_questions_and_terms(app_env):
    client, _, deck_id = app_env
    report = run(client)
    assert (report.sessions, report.views, report.questions, report.terms) == (2, 4, 2, 3)
    assert any("Missing.pdf" in w for w in report.warnings) and any("NOPE 9" in w for w in report.warnings)
    last = sessions.resume(client.app_state.db, "CS 101")
    assert (last["deck_id"], last["idx"]) == (deck_id, 4)  # the 23 September session is the latest
    statuses = {t["term"]: t["status"] for t in client.get("/api/terms").json()["terms"]}
    assert statuses == {"Pivot": "hard", "Heap": "known", "array": "new"}
    found = sessions.sessions(client.app_state.db)
    assert [s.start.date().isoformat() for s in found] == ["2026-09-22", "2026-09-23"]


def test_import_is_idempotent(app_env):
    client, *_ = app_env
    run(client)
    again = run(client)
    assert (again.sessions, again.skipped, again.views) == (0, 2, 0)
    with client.app_state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM deckless_questions").fetchone()[0] == 2


def test_cli_imports_a_file(app_env, tmp_path, monkeypatch, capsys):
    client, *_ = app_env
    from studydesk import __main__ as entry
    from studydesk.config import Config

    config = client.app_state.config
    monkeypatch.setattr(entry, "load_config", lambda: Config(home=config.home, data_root=config.data_root))
    path = tmp_path / "history.json"
    path.write_text(json.dumps(HISTORY))
    entry.main(["import-sessions", str(path)])
    out = capsys.readouterr().out
    assert "imported 2 sessions" in out and "warning:" in out
