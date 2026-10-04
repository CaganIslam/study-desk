# Progress log

> The project's memory - what's been done. Newest first.
> **Append an entry after every issue / PR / milestone.** One short bullet block each.

<!-- Template for an entry:

## YYYY-MM-DD - <short title>
- Issue: #N  ·  PR: #M  ·  Milestone: <name>
- What changed: <one or two plain lines>
- Notes for next time: <anything that will save future-you time>
-->

## 2026-10-04 - Glossary
- Issue: #12  ·  Milestone: Milestone 1 - Core study loop
- What changed: terms captured from explanations and answers, statuses new/hard/known, "I know this" marks a slide's terms known and they are no longer re-explained, term card (meaning, exam definition, example, where seen, status buttons, pronunciation), terms page with filters, `T` opens the first term of the explanation. Older explanations are backfilled at startup.
- Notes for next time: 24 terms came out of the explanations made so far on real decks. Option picked: dedupe by normalised string (no extra Claude call to merge near-duplicates).

## 2026-10-04 - Sessions, resume, notes and search
- Issue: #11  ·  Milestone: Milestone 1 - Core study loop
- What changed: slide views recorded; resume point per course and overall ("nerede kaldık", "ml aç" open where you stopped, course page shows it); sessions derived from views; a notes file per finished session; full-text search over explanations and questions ("X nerede geçti"); "bugün ne çalıştım" lists today's sessions.
- Notes for next time: on real data, search for "regularization" found the slide 13-15 explanations and the earlier question. Option picked: notes assembled from stored data without Claude (free, instant, and the explanations are already Claude's).

## 2026-10-04 - Input bar
- Issue: #10  ·  Milestone: Milestone 1 - Core study loop
- What changed: one bar on every page for questions and commands. Local parser for common commands (51 table-driven cases, many from real past sessions); one Claude call for everything else that answers or picks an action; questions stored per slide and shown under the explanation; "?" mark in the slide strip.
- Notes for next time: checked in Chrome: "462 lec3 aç" opened ML Lec03, "13. slaytta regularization diyor ne o kısa basitçe" moved to slide 13 and answered there. Moving between slides no longer waits for the explanation. Option picked: parser rules in code (testable), not a grammar file.

## 2026-10-04 - Prefetch
- Issue: #9  ·  Milestone: Milestone 1 - Core study loop
- What changed: the next slide is explained in the background while the current one is read; stale prefetches are skipped; concurrent requests for the same explanation share one Claude call.
- Notes for next time: on a real deck, slide 27 arrived 4 s after "next" (it was still being prefetched) instead of 13 s. Option picked: depth 1 (cheaper on plan limits; reading a slide takes longer than one explanation).

## 2026-10-04 - Study screen
- Issue: #8  ·  Milestone: Milestone 1 - Core study loop
- What changed: course list, deck list and the study screen (slide, explanation with KaTeX, exam notes, terms, slide strip with known/explained marks, next/previous/jump by lecturer's number, "I know this, skip", length toggle, variants, keyboard shortcuts). Backend: cached explanations, `POST .../explain`, known marks. KaTeX, marked and highlight.js vendored.
- Notes for next time: checked in Chrome on a real ML deck: space, B and 1 work, continuity between slides shows up in the text, no console errors. Options picked: plain JS modules (no framework, no build).

## 2026-10-04 - Claude runner and tutor prompts
- Issue: #7  ·  Milestone: Milestone 1 - Core study loop
- What changed: `ai/runner.py` (one locked-down `claude -p` process per call, image inline, failures mapped to not_installed / not_logged_in / limit / timeout / bad_output / failed, `FakeRunner` for tests); tutor and answer prompts with JSON schemas; length levels (short / normal / detailed) and variants (simpler / example / different / formula); known-term list; previous-slide summary for continuity.
- Notes for next time: real calls on ML, logic and embedded slides gave correct, well-structured explanations: normal 12-14 s, short 10 s, answer 6.5 s. Options picked: image inline in `stream-json` (no Read turn, no tools); default model = the user's Claude Code default, live mode will pass a faster model.

## 2026-10-04 - Slide cache
- Issue: #6  ·  Milestone: Milestone 1 - Core study loop
- What changed: decks and logical slides indexed from the course folders (`decks`, `slides` tables), animation builds grouped by footer frame numbers or by growing text, cached PNG renders, deck/slide/image/find-by-label endpoints. Decks are re-scanned after a Moodle sync brings new files.
- Notes for next time: checked on real decks: labels match what the lecturer calls the slides (ML Lec01 = 33 slides; Lec02 slide 24 = pages 33-35). Scan of all courses 0.3 s, render 0.06-0.13 s. Options picked: two sizes (`view` sharp on screen, `ai` cheaper for Claude); builds collapsed into one slide (labels follow the lecturer).

## 2026-10-04 - Moodle sync
- Issue: #5  ·  Milestone: Milestone 1 - Core study loop
- What changed: background job queue; Moodle sync of course PDFs into `slides/`, triggered when the page opens and the last sync is older than 30 minutes (`POST /api/sync/moodle`, status at `GET`). Token in the macOS Keychain.
- Notes for next time: first real run downloaded 14 new PDFs across 4 courses, a second run downloaded nothing. Options picked: Keychain over a config file (secret stays out of plain files); PDFs only (decks are what the study loop uses).

## 2026-10-04 - Courses, schedule and time-to-course matching
- Issue: #4  ·  Milestone: Milestone 1 - Core study loop
- What changed: `courses.toml` in the data root (format in `docs/courses-toml.md`) with courses, weekly slots, closures, exams and weekly topics; `match()` picks the attended class with the largest overlap (15-minute tolerance); `/api/courses` and `/api/today` (with the class running now). The `tests` check is now required on `main`.
- Notes for next time: options picked: TOML over YAML or `.ics` (no new dependency, same format as config.toml); weekly topics are written in the file, not extracted by Claude yet.

## 2026-10-04 - Project skeleton
- Issue: #3  ·  Milestone: Milestone 1 - Core study loop
- What changed: `studydesk` package (uv, Python 3.12), FastAPI app on 127.0.0.1:4620 with `/api/health`, error shape for unknown API paths, config loading, SQLite with numbered migrations, placeholder page with a strings file, pytest suite (12 tests) and a CI test workflow.
- Notes for next time: config lives in the app directory, not the data root (picked option). Run the server with `uv run study-desk`; set `STUDYDESK_HOME` to a temp dir for throwaway runs.

## 2026-10-04 - Recordings by drag and drop
- Issue: #1 (closed, not planned)  ·  Milestone: Milestone 0 - Verification
- What changed: automatic Voice Memos import dropped at the maintainer's request; recordings are dragged into the app. Checks 6-7 dropped, BLUEPRINT and README updated, transcript quality check added as a cross-cutting rule.
- Notes for next time: no Full Disk Access anywhere. The recording time comes from `creation_time` inside the file.

## 2026-10-04 - Whisper benchmark on a real lecture
- Issue: #2  ·  Milestone: Milestone 0 - Verification
- What changed: phase-0 check 8 recorded. Five transcription runs on a 50-minute classroom recording; recommended settings written down; BLUEPRINT open question and the transcription integration decision closed.
- Notes for next time: `condition_on_previous_text=False` is not optional. Default settings loop on classroom audio and silently lose most of the lecture; check segment compression ratios after every transcription.

## 2026-10-04 - Repository bootstrapped
- Milestone: Milestone 0 - Verification
- What changed: repo created with the projectflow method. Living docs written from the approach plan: BLUEPRINT, ARCHITECTURE, STACK, ADRs 0002-0003, phase-0 verification notes.
- Notes for next time: checks 1-5 in `docs/research/phase-0-verification.md` passed. Checks 6-8 are the open Milestone 0 issues. The discovery pipeline was skipped on purpose (see BLUEPRINT).
