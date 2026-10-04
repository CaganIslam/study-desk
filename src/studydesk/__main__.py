"""Start the server (it only ever listens on 127.0.0.1), or run a one-off command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

from studydesk.config import load_config
from studydesk.server import create_app

HOST = "127.0.0.1"


def serve() -> None:
    config = load_config()
    uvicorn.run(create_app(config), host=HOST, port=config.port, log_level="info")


def import_sessions(path: Path) -> None:
    from studydesk.courses import CatalogFile
    from studydesk.db import Database
    from studydesk.ingest.history import import_history

    config = load_config()
    if config.data_root is None:
        raise SystemExit("Set data_root in config.toml first.")
    db = Database(config.database_path)
    db.migrate()
    report = import_history(db, CatalogFile(config.data_root).get(), config.data_root, json.loads(path.read_text(encoding="utf-8")))
    print(
        f"imported {report.sessions} sessions ({report.skipped} already imported): "
        f"{report.views} slide views, {report.questions} questions, {report.terms} terms"
    )
    for warning in report.warnings:
        print(f"warning: {warning}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="study-desk")
    commands = parser.add_subparsers(dest="command")
    imp = commands.add_parser("import-sessions", help="import study history from a JSON file (docs/import-format.md)")
    imp.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "import-sessions":
        import_sessions(args.file)
    else:
        serve()


if __name__ == "__main__":
    main()
