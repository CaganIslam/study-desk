import sqlite3

import pytest

from studydesk import db as dbmod
from studydesk.db import Database


def test_migrations_apply_once(tmp_path):
    database = Database(tmp_path / "study.db")
    first = database.migrate()
    assert first and first[0].startswith("0001_")
    assert database.migrate() == []
    with database.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"schema_migrations", "app_meta"} <= tables


def test_failed_migration_is_rolled_back(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_ok.sql").write_text("CREATE TABLE a (x INTEGER);")
    (migrations / "0002_broken.sql").write_text("CREATE TABLE b (x INTEGER);\nNOT VALID SQL;")
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", migrations)
    database = Database(tmp_path / "study.db")
    with pytest.raises(sqlite3.Error):
        database.migrate()
    with database.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    assert "a" in tables and "b" not in tables
    assert applied == {"0001_ok.sql"}


def test_connect_rolls_back_on_error(tmp_path):
    database = Database(tmp_path / "study.db")
    database.migrate()
    with pytest.raises(RuntimeError):
        with database.connect() as conn:
            conn.execute("INSERT INTO app_meta (key, value) VALUES ('k', 'v')")
            raise RuntimeError("boom")
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_meta").fetchone()[0] == 0


def test_simplicity_migration_keeps_explanations(tmp_path, monkeypatch):
    before = tmp_path / "before"
    before.mkdir()
    for script in sorted(dbmod.MIGRATIONS_DIR.glob("*.sql")):
        if script.name < "0011":
            (before / script.name).write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    real = dbmod.MIGRATIONS_DIR
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", before)
    database = Database(tmp_path / "study.db")
    database.migrate()
    with database.connect() as conn:
        conn.execute(
            "INSERT INTO decks (id, course_code, path, sha256, mtime, size, pages, numbered)"
            " VALUES (1, 'CS 101', '/x.pdf', 'h', 0, 0, 1, 0)"
        )
        conn.execute(
            "INSERT INTO explanations (deck_id, idx, level, variant, language, deck_sha, explanation_md, summary,"
            " terms_json, exam_notes_json, notes_sha) VALUES (1, 1, 'normal', '', 'tr', 'h', 'old text', 's', '[]', '[]', 'n')"
        )
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", real)
    assert database.migrate() == ["0011_explanation_simplicity.sql"]
    with database.connect() as conn:
        row = conn.execute("SELECT explanation_md, notes_sha, simplicity FROM explanations").fetchone()
        assert tuple(row) == ("old text", "n", "normal")
        conn.execute(
            "INSERT INTO explanations (deck_id, idx, level, variant, language, simplicity, deck_sha, explanation_md,"
            " summary, terms_json, exam_notes_json) VALUES (1, 1, 'normal', '', 'tr', 'simple', 'h', 'new', 's', '[]', '[]')"
        )
        assert conn.execute("SELECT COUNT(*) FROM explanations").fetchone()[0] == 2
