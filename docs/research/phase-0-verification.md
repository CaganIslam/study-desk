# Phase 0: verification of risky assumptions

Checks run before building on them. Each one either passed with evidence or stays open as a Milestone 0 issue.

| # | Assumption | Result | Date |
|---|---|---|---|
| 1 | `claude -p` works headless on a subscription login, returns schema-valid JSON, and can read a slide image | **Pass.** `--safe-mode` + `--json-schema` + Read on a slide PNG: 12.7 s, 3 turns, valid `structured_output`. `--bare` is not an option (needs an API key). | 2026-10-03 |
| 2 | Voice Memos recordings can be decoded | **Pass.** Voice Memos 26.x saves `.qta` (QuickTime): track 0 is AAC stereo (decodes with ffmpeg), track 1 is `apac` spatial audio (ffmpeg cannot decode it, not needed), tracks 2-3 are small metadata (no transcript). ffmpeg's default stream selection picks track 0. | 2026-10-03 |
| 3 | A recording's start time is available without the Voice Memos database | **Pass.** `creation_time` in the file metadata (UTC). Drag-and-drop imports can still be matched to a course. | 2026-10-03 |
| 4 | Time-based course matching is right | **Pass** on two real samples: a 47-minute recording starting Thursday 11:46 matched the Thursday 10:00-13:00 course (confirmed by the user), and a 50-minute recording starting Thursday 14:50 matched the Thursday 13:00-16:00 course, with the clashing slot the user does not attend ignored. | 2026-10-04 |
| 5 | Moodle can be read without Claude, directly from Python | **Pass.** `core_webservice_get_site_info`, `core_enrol_get_users_courses`, `core_course_get_contents` and a `pluginfile.php` download with the token all work, 0.1-0.4 s per call, with TLS verification on. | 2026-10-04 |
| 6 | The server, started by launchd, can read the Voice Memos library (Full Disk Access) | **Dropped.** The user drags recordings into the app instead (decision 2026-10-04). No Full Disk Access is needed; the course still comes from the file's `creation_time` (check 3). | 2026-10-04 |
| 7 | iCloud downloads new recordings to the Mac without the Voice Memos app being opened | **Dropped** with check 6. | 2026-10-04 |
| 8 | mlx-whisper on a real lecture: speed, technical-term accuracy, hallucination on silence | **Pass, with one required setting.** `condition_on_previous_text=False` is mandatory: with the default (`True`) the transcript fell into a repetition loop after 4 minutes and lost the remaining 46. With it off, a 50-minute lecture took 36 s (turbo) and the text is readable and faithful. Details below. | 2026-10-04 |

Notes:
- (Kept for reference, not used.) The Voice Memos library is `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/` with `CloudRecordings.db` (`ZCLOUDRECORDING`: `ZDATE`, `ZDURATION`, `ZPATH`; `ZDATE` is seconds since 2001-01-01, add 978307200 for Unix time). It cannot be read without Full Disk Access.
- A 47-minute `.qta` is about 207 MB, mostly the spatial track. The app does not store audio, so size is not an issue.
- mlx-whisper's `transcribe()` supports `word_timestamps`, `initial_prompt` and `hallucination_silence_threshold`.

## Check 8: transcription benchmark

Input: one real lecture, 50.2 minutes, recorded with Voice Memos on an iPad in a classroom (`.qta`, AAC track, mean volume -32.5 dB, no silent gap longer than 3 s at -40 dB). Model files came from the local Hugging Face cache; the installed `mlx_whisper` CLI was used. All runs `--language en`. The transcripts themselves are not kept in the repo.

| Run | Settings | Wall time | Words | Repeated consecutive segments | Segments with compression ratio > 2.4 | Minutes covered |
|---|---|---|---|---|---|---|
| A | turbo, defaults | 63 s | 19,960 | 29 | 89 of 105 | 50.2 |
| B | turbo + `initial_prompt` (deck terms) | 66 s | 13,959 | 1,826 | 1,853 of 1,947 | 49.9 |
| C | B + `word_timestamps` + `hallucination_silence_threshold=2` | 688 s | 2,773 | 6 | 12 of 28 | **8.7** |
| D | turbo, `condition_on_previous_text=False` | **36 s** | 4,755 | 1 | 0 of 379 | 49.3 |
| E | large-v3, `condition_on_previous_text=False` | 96 s | 4,764 | 1 | 0 of 408 | 49.6 |

What happened:
- A and B fell into repetition loops ("the truth value to the truth value ..." from minute 4 to the end in A, "formula formula ..." in B). Classroom noise with no clean silences seems to trigger it, and conditioning on the previous window carries the loop forward.
- C stopped the loop by skipping, but skipped 41 of the 50 minutes and took 11 times longer.
- D and E are both readable and faithful. Typical errors: "K-tree" for K3, "virtual deduction" (D) / "natural induction" (E) for natural deduction, "piano" for Peano (E), "proposition of logic" for propositional logic. Term counts are close between D and E (e.g. truth table 11 / 12, soundness 9 / 9, quantifier 10 / 10, first order logic 32 / 29).
- No Turkish speech was detected in this lecture.

Recommended settings:
- `whisper-large-v3-turbo`, `--language en` (per-course setting), `--condition-on-previous-text False`.
- No `initial_prompt`: it did not prevent loops, and without conditioning the reference implementation applies it to the first window only. Vocabulary hints, if needed later, mean prompting per chunk.
- No word timestamps: segment timestamps (a few seconds) are enough for slide and photo alignment, and word timestamps made the run 10x slower.
- large-v3 is an optional quality setting: similar accuracy on this sample, 2.7x slower (still about 6 minutes for a 3-hour lecture).
- Integration: call the user's installed `mlx_whisper` CLI as a subprocess and read its JSON output; fall back to an optional package extra only when it is missing.

## Light research

- Learning science: Dunlosky et al. (2013) rate practice testing and distributed practice as the highest-utility techniques, and rereading, highlighting and summarising as low. This is why the app leans on spaced term review, end-of-lecture quizzes and exam mode rather than summaries. https://www.sciencedaily.com/releases/2013/01/130110111734.htm
- Existing apps (Coconote, Turbo AI) turn recordings and PDFs into notes, flashcards and quizzes in the cloud. study-desk differs in being local, slide-aligned (what the lecturer said on each slide) and organised automatically by Moodle and the schedule.
