"""SQLite access and numbered SQL migrations.

A connection is opened per unit of work, so request threads never share one.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection inside a transaction: committed on success, rolled back on error."""
        conn = self._open()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def migrate(self) -> list[str]:
        """Apply migrations that have not run yet, in name order. Returns the names applied."""
        conn = self._open()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name TEXT PRIMARY KEY,"
                " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            conn.commit()
            done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
            applied = []
            for script in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if script.name in done:
                    continue
                if not _MIGRATION_NAME.match(script.name):
                    raise RuntimeError(f"bad migration file name: {script.name}")
                # One script per transaction, recorded in the same transaction.
                try:
                    conn.executescript(
                        "BEGIN;\n"
                        + script.read_text(encoding="utf-8")
                        + f"\nINSERT INTO schema_migrations (name) VALUES ('{script.name}');\nCOMMIT;"
                    )
                except sqlite3.Error:
                    if conn.in_transaction:
                        conn.rollback()
                    raise
                applied.append(script.name)
            return applied
        finally:
            conn.close()
