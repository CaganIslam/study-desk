# Architecture & conventions

> Constraints, structure, and the patterns this project uses.
> **Read before writing code.** Follow what's here instead of inventing new ways.
> When a structural decision changes, record an ADR in `docs/adr/` and update this file.

## Folder structure

Repository (code only, public):

```
src/studydesk/
  server.py          FastAPI app and routes (/api/*, static pages)
  config.py          config loading: data root, Moodle, language, models
  db/                SQLite connection, numbered SQL migrations
  courses/           courses, schedule, syllabi, time → course matching
  decks/             PDF → slide PNG + text cache
  ai/                claude -p runner, prompts/, schemas/
  ingest/            moodle.py, recordings.py, transcribe.py, photos.py, books.py
  study/             sessions, steps, resume, prefetch, terms, review
  web/               static HTML/CSS/JS, vendor/, strings.tr.json
scripts/             launchd install / uninstall
tests/               unit, contract (API shape), flow (journeys)
docs/                living docs, ADRs, research
```

Data root (personal, outside the repo, path set in config):

```
<data root>/
  <COURSE CODE> <Course Name>/
    slides/          from Moodle or dropped in by hand
    transcripts/     one markdown file per recording
    photos/          board photos (JPEG)
    books/
    notes/           session summaries
```

Config and database: `~/Library/Application Support/StudyDesk/config.toml` and `study.db` (SQLite). They stay machine-local, outside the data root. `STUDYDESK_HOME` overrides the directory (tests use it). A daily database copy is kept as a backup.

## Patterns & methods we use

- **Data:** the data root holds the material, the database holds metadata and derived text (slide text, transcripts, explanations, terms). Schema changes are numbered SQL files in `db/migrations/` (`NNNN_name.sql`), each applied in its own transaction at startup. Code opens a connection per unit of work with `Database.connect()` (commit on success, rollback on error). Full-text search uses FTS5.
- **AI calls:** only `ai/runner.py` starts `claude`. Each call is one process: `claude -p --safe-mode --no-session-persistence --output-format json --json-schema <schema>`. Every call type has a prompt file in `ai/prompts/` and a JSON schema in `ai/schemas/`. The server builds the context: current slide image and text, a short summary of the previous slide, what the lecturer said, known terms, and the Q&A thread for this slide. No conversation state lives in Claude. Calls have a timeout. When Claude is unavailable (limit, network), only AI features degrade.
- **Courses and schedule:** `courses.toml` in the data root is the source of truth (format in `docs/courses-toml.md`). It is read with `tomllib` and re-read when it changes; courses are referenced by their `code` everywhere else. Times are wall-clock times in the file's `timezone`.
- **Background work:** `jobs.JobQueue`, one in-process worker thread, so jobs run in order: sync, import, transcription, alignment, prefetch. A job key that is already queued or running is not queued twice. Jobs are idempotent and safe to re-run.
- **Moodle:** `ingest/moodle.py` talks to the web service with the stdlib (no Claude). Only PDFs are synced, into `<course>/slides/`. Downloaded files are tracked in `moodle_files`; unchanged files are skipped, a file put there by hand with the same name and size is adopted, and a different file with the same name is never overwritten (the download is saved as `<name> (Moodle).pdf`).
- **API:** JSON under `/api/...`, pages served as static files. Errors return `{"error": {"code", "message"}}` with a proper status code.
- **Commands:** the input bar first tries a local parser (course codes and aliases, lecture and slide numbers, next/previous, length, live mode). Only unrecognised input goes to Claude, which either picks an action from a fixed list (JSON) or says it is a question.
- **Text:** UI strings come from `web/strings.<lang>.json`, never hard-coded in HTML/JS.
- **Naming:** Python `snake_case` modules; tables are plural nouns; branches `<type>/<area>/<slug>-<issue>`.
- **Tests:** pytest. A contract suite asserts status, shape and field names for every `/api` route, never exact values. A flow suite walks journeys (open course → next → ask → resume). Tests never call the real `claude`: the runner is swapped for a fake that returns schema-valid JSON.

## Constraints (the "always / never" list)

- Always bind the server to `127.0.0.1`.
- Always send Claude only what one call needs: the current slide and a short context, never whole decks or whole transcripts (except the alignment call).
- Never commit personal data: slides, transcripts, photos, schedules, tokens, the database.
- Never store audio: a dropped recording is deleted once its transcript is saved. Never read or modify the Voice Memos or Photos libraries.
- Never send deterministic work to Claude.
- Never load assets from a CDN at runtime. Vendor them.
- Commit messages and PRs carry no AI attribution.

## Tooling

- commit/PR grammar: `<type>(<area>): subject` (see `commitlint.config.js`). The PR title is checked in CI (`lint-pr-title`).
- areas: `backend, frontend, ingest, ai, devops, docs` (+ `repo` for repository configuration)
- CI: PR title check now, test workflow added with the project skeleton.
- destructive ops (database reset, re-import): separate commands with a confirmation prompt.

## Decisions

See `docs/adr/`:
- [0001](adr/0001-record-architecture-decisions.md) record architecture decisions
- [0002](adr/0002-claude-code-headless-runtime.md) Claude Code headless as the LLM runtime
- [0003](adr/0003-personal-data-outside-repo.md) personal data outside the repository
- PDF handling uses pypdfium2 rather than PyMuPDF, so the dependency licences stay permissive (PyMuPDF is AGPL).
