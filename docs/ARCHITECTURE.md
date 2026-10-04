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
- **AI calls:** only `ai/runner.py` starts `claude`. Each call is one process: `claude -p --safe-mode --no-session-persistence --tools "" --system-prompt <prompt> --input-format stream-json --output-format stream-json --json-schema <schema>`, plus `--model`/`--effort` when set. The slide PNG goes inside the message as a base64 image block, so Claude has no tools and no file access. Effort is `low` for short/normal explanations and answers, `medium` for detailed ones (low effort answered about twice as fast with the same quality, measured 2026-10-04). Prompts live in `ai/prompts/*.md`, schemas in `ai/schemas/*.json`, call builders in `ai/tutor.py`. Every call type has a prompt file in `ai/prompts/` and a JSON schema in `ai/schemas/`. The server builds the context: current slide image and text, a short summary of the previous slide, what the lecturer said, known terms, and the Q&A thread for this slide. No conversation state lives in Claude. Calls have a timeout. When Claude is unavailable (limit, network), only AI features degrade.
- **Courses and schedule:** `courses.toml` in the data root is the source of truth (format in `docs/courses-toml.md`). It is read with `tomllib` and re-read when it changes; courses are referenced by their `code` everywhere else. Times are wall-clock times in the file's `timezone`.
- **Background work:** `jobs.JobQueue`, one in-process worker thread, so jobs run in order: sync, import, transcription, alignment, prefetch. A job key that is already queued or running is not queued twice. Jobs are idempotent and safe to re-run.
- **Decks and slides:** every PDF in `<course>/slides/` is a deck. Pages are grouped into logical slides: when most pages end with a frame number, pages sharing a number are one slide and the number is its label (what the lecturer calls it); otherwise a page whose text extends the previous page is a build step. A slide is shown and explained from its last page. Decks are re-indexed when their mtime/size changes (hash decides), keeping their id. Every pdfium call (scan and render) holds `decks.PDFIUM_LOCK`: pdfium is not thread-safe and concurrent use crashes the process. PNG renders are cached by file hash in `<app dir>/cache/slides/` at two sizes: `view` (2000 px) and `ai` (1280 px).
- **Moodle:** `ingest/moodle.py` talks to the web service with the stdlib (no Claude). Only PDFs are synced, into `<course>/slides/`. Downloaded files are tracked in `moodle_files`; unchanged files are skipped, a file put there by hand with the same name and size is adopted, and a different file with the same name is never overwritten (the download is saved as `<name> (Moodle).pdf`).
- **API:** JSON under `/api/...`, pages served as static files. Errors return `{"error": {"code", "message"}}` with a proper status code.
- **Activity, sessions, notes, search:** the study page records a `view` in `activity` for every slide shown. Resume points (last slide per course or overall) and sessions (views of one course with gaps under 30 minutes) are derived from it, never opened or closed by the browser. When a session has been idle for 30 minutes, a notes file is written to `<course>/notes/YYYY-MM-DD-HHMM.md` (slides, known marks, questions with the first sentence of the answer, exam notes, terms), assembled without Claude; `session_notes` remembers which were written. Explanations and questions are indexed in the FTS5 table `search_index` with folded text; rows made before search existed are backfilled at startup.
- **Terms:** `study/terms.py`. Terms from explanations (`new`) and answers (`hard`) are stored once per normalised key (folded, parentheses dropped, simple plural `s` removed) and shared across courses, with every slide they came up on. "I know this" turns a slide's `new` terms into `known` (hard terms stay hard). The 40 most recent known terms of the course go into each explanation call. The card is a `<dialog>`; pronunciation uses the browser's speech synthesis (macOS voices).
- **Live mode:** `#/live` opens the class running now (or a picked course) at its newest deck by file time, resuming inside it if the student was there. It is the study screen with a badge, short explanations by default, and the live model (`[models] live`, default `sonnet`). While live, the page asks for a Moodle sync every minute and the server syncs if the last one is older than 3 minutes; a new deck of the course is announced on the page. Without a deck, questions go to `deckless_questions` with the course and are attached to slides later (Milestone 4).
- **Recordings:** dropped anywhere in the window (`POST /api/recordings`, multipart) or imported with `study-desk import-recordings FOLDER`. The start time comes from the file's `creation_time` (ffprobe) and the course from the schedule match; no match means status `needs_course` and the student picks one. Transcription runs on its own `JobQueue` (`app.state.transcriber`) so long jobs never hold up prefetching; it calls the installed `mlx_whisper` CLI with the benchmarked settings (`ingest/transcribe.py`). Every transcript is checked (repeated or highly compressed segments, minutes covered, words per minute); a failed check becomes `bad_quality` with plain-language reasons and a retry-with-large-model button, never used silently. Transcripts go to `<course>/transcripts/YYYY-MM-DD-HHMM.md` and `transcript_segments`. Uploaded audio lives in `<app dir>/inbox/` only until its transcript is saved (or it is discarded); files given to the importer are only read.
- **Commands:** `POST /api/command`. `study/commands.py` folds the text (lowercase, Turkish letters to ASCII, filler words like "reis" dropped) and recognises whole-text commands: next/previous, go to slide N (typos like "salyta" included), open a course and lecture by code or alias, length, variants, I know this, home. A leading position ("14. slayttayız, ...") moves to that slide before the rest is answered. Anything else is one Claude call (`bar_call`, schema `bar.json`) that either answers it in the context of the current slide or returns an action from the same list. Answers are stored per slide in `questions` and passed back as the thread for follow-ups.
- **Text:** UI strings come from `web/strings.<lang>.json`, never hard-coded in HTML/JS.
- **Frontend:** plain ES modules in `web/js/` (`app.js` hash router, one module per page, `api.js` for fetch + error shape, `render.js` for markdown + KaTeX). Math is cut out before markdown parsing and rendered with KaTeX; raw HTML in model output is escaped. Pages and scripts are served with `Cache-Control: no-cache`. Per-viewer conveniences (the length level per course) live in `localStorage` behind try/catch.
- **Explanations:** `study/explanations.py` builds the slide context, calls Claude and caches the result per (slide, level, variant, language) in `explanations`, tied to the deck's hash. The previous slide's cached summary is passed on for continuity. After an explanation is served, the next slide is prefetched at the same level (`study/prefetch.py`): only the slide after the current one is wanted, a queued job for a slide the student already left is skipped, and `InFlight` makes a request that arrives during a prefetch of the same slide wait for it instead of calling Claude again. Cached explanations are not regenerated when the known-term list changes; "refresh" does that.
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

## Running it

- `scripts/install.sh` installs the launchd agent `com.studydesk.server` (`~/Library/LaunchAgents/`): it runs `.venv/bin/study-desk` at login, restarts it if it stops (`KeepAlive`, 10 s throttle) and logs to `~/Library/Logs/StudyDesk/server.log`. The agent gets a PATH with the folders of `claude`, `ffmpeg`, `mlx_whisper` and `uv`, because launchd starts processes with a minimal PATH. Re-running the script replaces the running agent. `scripts/uninstall.sh` removes the agent and keeps all data.
- During development, stop the agent (`launchctl bootout gui/$(id -u)/com.studydesk.server`) or run a second copy with another `port` in a separate `STUDYDESK_HOME`.

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
