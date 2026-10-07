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


def import_recordings(paths: list[Path], model: str = "turbo") -> None:
    """Transcribe recordings from a folder or files. The files are only read, never moved or deleted."""
    from studydesk.courses import CatalogFile
    from studydesk.db import Database
    from studydesk.ingest import recordings

    config = load_config()
    if config.data_root is None:
        raise SystemExit("Set data_root in config.toml first.")
    db = Database(config.database_path)
    db.migrate()
    catalog = CatalogFile(config.data_root).get()
    files = []
    for path in paths:
        files += sorted(p for p in path.iterdir() if p.suffix.lower() in recordings.AUDIO_SUFFIXES) if path.is_dir() else [path]
    for number, path in enumerate(files, start=1):
        rec_id, is_new = recordings.add(db, catalog, path)
        rec = recordings.get(db, rec_id)
        if not is_new and rec["status"] == "done":
            print(f"[{number}/{len(files)}] {path.name}: already transcribed")
            continue
        if rec["status"] == "needs_course":
            print(f"[{number}/{len(files)}] {path.name}: no class at that time, choose its course in the app")
            continue
        status = recordings.process(db, catalog, config.data_root, rec_id, model, owned_audio=False)
        rec = recordings.get(db, rec_id)
        quality = json.loads(rec["quality_json"]) if rec["quality_json"] else {}
        stats = quality.get("stats", {})
        print(
            f"[{number}/{len(files)}] {path.name} -> {rec['course_code']}: {status}"
            f" ({stats.get('words', 0)} words, {stats.get('covered_ratio', 0):.0%} covered"
            + (f", problems: {', '.join(quality.get('reasons', []))}" if quality.get("reasons") else "")
            + (f", error: {rec['error']}" if rec["error"] else "")
            + ")"
        )


def align_recordings(force: bool = False) -> None:
    """Match transcripts to slides (one Claude call per recording)."""
    from studydesk.ai.runner import ClaudeCLI, ClaudeError
    from studydesk.courses import CatalogFile
    from studydesk.db import Database
    from studydesk.ingest import alignment

    config = load_config()
    db = Database(config.database_path)
    db.migrate()
    catalog = CatalogFile(config.data_root).get()
    with db.connect() as conn:
        todo = (
            [r["id"] for r in conn.execute("SELECT id FROM recordings WHERE status = 'done' ORDER BY started_at")]
            if force
            else alignment.unaligned(db)
        )
    runner = ClaudeCLI(cwd=config.app_home)
    for number, rec_id in enumerate(todo, start=1):
        with db.connect() as conn:
            rec = conn.execute("SELECT source_name, course_code FROM recordings WHERE id = ?", (rec_id,)).fetchone()
        try:
            stats = alignment.align(db, catalog, runner, rec_id, config.model_default)
            print(f"[{number}/{len(todo)}] {rec['source_name']} ({rec['course_code']}): {stats}")
        except ClaudeError as exc:
            print(f"[{number}/{len(todo)}] {rec['source_name']}: {exc.code} {exc}")
            if exc.code in ("limit", "not_logged_in", "not_installed"):
                break


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="study-desk")
    commands = parser.add_subparsers(dest="command")
    imp = commands.add_parser("import-sessions", help="import study history from a JSON file (docs/import-format.md)")
    imp.add_argument("file", type=Path)
    rec = commands.add_parser("import-recordings", help="transcribe lecture recordings from a folder or files")
    rec.add_argument("paths", type=Path, nargs="+")
    rec.add_argument("--model", default="turbo", choices=["turbo", "large"])
    align = commands.add_parser("align-recordings", help="match transcripts to slides with Claude")
    align.add_argument("--force", action="store_true", help="align again even if already aligned")
    args = parser.parse_args(argv)
    if args.command == "align-recordings":
        align_recordings(args.force)
    elif args.command == "import-sessions":
        import_sessions(args.file)
    elif args.command == "import-recordings":
        import_recordings(args.paths, args.model)
    else:
        serve()


if __name__ == "__main__":
    main()
