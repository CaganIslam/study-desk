# Blueprint

> The plan and shape of the project. Keep this honest. If the plan changes, update it.

## What we're building

study-desk is a local web app for students who study from lecture slides. It runs on the student's own Mac and is opened in a browser. A study session goes slide by slide. For each slide, Claude gives a short explanation in the student's language, with technical terms kept in English. Around that loop, the app collects everything a course produces: Moodle files, the student's own lecture recordings and board photos, the schedule, syllabi and textbooks. It also remembers where the student left off, what they asked, which terms they struggle with and what the lecturer emphasised.

The first user is the maintainer: a CS student whose courses are taught in English, studying in Turkish. The app is built so anyone with a Mac, Claude Code and (optionally) Moodle can use it.

## Discovery decision

- decision: go. The discovery pipeline was skipped.
- rationale: this is the maintainer's own daily workflow. It ran for weeks as manual Claude Code sessions ("next slide", "what is X, briefly"). The problem and the demand are first-hand, so a market validation would not change the decision. A short research pass (existing study apps, learning-science evidence, technical feasibility) was done instead.
- findings: [`docs/research/phase-0-verification.md`](research/phase-0-verification.md)

## How it's built

```
 Moodle ─────── sync on open ──────▶ course folder/slides (PDF) ─▶ slide cache (PNG + text) ─┐
 Voice Memos ── import by time ────▶ transcribe (mlx-whisper, local) ─▶ align to slides ──────┤
 Board photos ─ import by time ────▶ read board (Claude) ─▶ attach to slide ─────────────────┤
 schedule + syllabus ──────────────▶ course / week matching ───────────────────────────────┤
                                                                                           ▼
                     SQLite: courses, slides, sessions, steps, terms, review cards, alignment
                                                                                           │
 Browser (127.0.0.1) ◀──── FastAPI server ◀──── claude -p (explain, answer, command, align)
```

The study loop:

```
open course ─▶ resume slide ─▶ explanation (prefetched) ─▶ next / I know this / simpler / ask
                                         │
                                         └─▶ new terms ─▶ glossary ─▶ daily review (spaced repetition)
```

## Stack

- backend: Python 3.12, FastAPI, SQLite (FTS5), uv
- frontend: plain HTML/CSS/JS served by the backend, no build step. KaTeX, marked and highlight.js are vendored.
- AI: Claude Code headless (`claude -p`), stateless calls with JSON schemas ([ADR 0002](adr/0002-claude-code-headless-runtime.md))
- audio: mlx-whisper (`whisper-large-v3-turbo`), ffmpeg
- PDF: pypdfium2 (render and extract text)
- review scheduling: py-fsrs
- ops: launchd agent that starts the server at login, bound to localhost only

## Milestone roadmap

| Milestone | Goal | Gate |
|---|---|---|
| Milestone 0 - Verification | Prove the risky assumptions before building on them | All checks recorded in `docs/research/phase-0-verification.md` |
| Milestone 1 - Core study loop | Study a lecture slide by slide in the browser. Includes the input bar, length levels, "I know this", live mode, Moodle sync, resume and terms | The maintainer studies a full lecture with it, and live mode works in class |
| v0.1 - Public alpha | Someone else can install and use the core loop | README install steps work on a clean user account |
| Milestone 2 - Term review | Daily spaced repetition, end-of-lecture mini quiz | Review runs daily, typed EN answers are checked |
| Milestone 3 - Recordings | Voice memos are imported, assigned to a course and transcribed automatically | A recording lands in the right course with no manual step |
| Milestone 4 - Alignment and board photos | Transcript and photos attached to slides. Decks that reach Moodle late are matched afterwards | Each explanation shows what the lecturer said on that slide |
| Milestone 5 - Books | Textbook chapters linked to syllabus topics and explanations | Explanations link to the right chapter and page |
| Milestone 6 - Exam mode | Scoped summaries and personal quizzes before an exam | A quiz built from the student's own questions and weak terms |
| Tech Debt & Fixes | Cleanup after each gate | - |

Order and dependencies: 0 → 1 → (2, 3 in any order) → 4 (needs 3) → 5 → 6 (needs 2, better with 4).

## Decided (cross-cutting)

- Claude is called through `claude -p --safe-mode --no-session-persistence --output-format json --json-schema`. Every call is stateless and the server builds its context ([ADR 0002](adr/0002-claude-code-headless-runtime.md)).
- Personal data lives in a data root outside the repo. The database lives in `~/Library/Application Support/StudyDesk/` ([ADR 0003](adr/0003-personal-data-outside-repo.md)).
- Audio is never stored. Only transcripts are kept.
- Nothing deterministic goes to Claude: Moodle sync, schedule matching and known commands are handled in code.
- All UI text lives in one strings file from day one (Turkish first).

## Open decisions

> Issue-local decisions live as `## Options` in their issue and are picked at propose time.

- Schedule source: a YAML file in the data root, or an `.ics` import (local, schedule issue).
- Moodle token storage: macOS Keychain, or a config file with restricted permissions (local, Moodle sync issue).
- Prefetch depth: 1 or 2 slides ahead (local, prefetch issue).
- Model per call type, e.g. a faster model in live mode (local, Claude runner issue).
- ~~Transcription integration~~ Decided in #2: call an `mlx_whisper` already on the PATH as a subprocess, fall back to an optional package extra only when it is missing; the model is reused from the Hugging Face cache.
- Voice Memos access: Full Disk Access for the server's Python, or a small dedicated helper (decided after the Milestone 0 check).

## Open questions

- Does iCloud download new voice memos to the Mac without the Voice Memos app being opened?
- ~~How accurate is whisper on lecture audio?~~ Answered in phase-0 check 8: readable with `condition_on_previous_text=False`; `initial_prompt` and word timestamps are not used.
