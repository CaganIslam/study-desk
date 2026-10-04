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
