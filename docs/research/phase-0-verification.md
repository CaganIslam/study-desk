# Phase 0: verification of risky assumptions

Checks run before building on them. Each one either passed with evidence or stays open as a Milestone 0 issue.

| # | Assumption | Result | Date |
|---|---|---|---|
| 1 | `claude -p` works headless on a subscription login, returns schema-valid JSON, and can read a slide image | **Pass.** `--safe-mode` + `--json-schema` + Read on a slide PNG: 12.7 s, 3 turns, valid `structured_output`. `--bare` is not an option (needs an API key). | 2026-10-03 |
| 2 | Voice Memos recordings can be decoded | **Pass.** Voice Memos 26.x saves `.qta` (QuickTime): track 0 is AAC stereo (decodes with ffmpeg), track 1 is `apac` spatial audio (ffmpeg cannot decode it, not needed), tracks 2-3 are small metadata (no transcript). ffmpeg's default stream selection picks track 0. | 2026-10-03 |
| 3 | A recording's start time is available without the Voice Memos database | **Pass.** `creation_time` in the file metadata (UTC). Drag-and-drop imports can still be matched to a course. | 2026-10-03 |
| 4 | Time-based course matching is right | **Pass** on the first real sample: a 47-minute recording starting Thursday 11:46 was matched to the course scheduled Thursday 10:00-13:00, confirmed by the user. | 2026-10-03 |
| 5 | Moodle can be read without Claude, directly from Python | **Pass.** `core_webservice_get_site_info`, `core_enrol_get_users_courses`, `core_course_get_contents` and a `pluginfile.php` download with the token all work, 0.1-0.4 s per call, with TLS verification on. | 2026-10-04 |
| 6 | The server, started by launchd, can read the Voice Memos library (Full Disk Access) | open | |
| 7 | iCloud downloads new recordings to the Mac without the Voice Memos app being opened | open | |
| 8 | mlx-whisper on a real lecture: speed, technical-term accuracy, hallucination on silence | open | |

Notes:
- The Voice Memos library is `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/` with `CloudRecordings.db` (`ZCLOUDRECORDING`: `ZDATE`, `ZDURATION`, `ZPATH`; `ZDATE` is seconds since 2001-01-01, add 978307200 for Unix time). It cannot be read without Full Disk Access.
- A 47-minute `.qta` is about 207 MB, mostly the spatial track. The app does not store audio, so size is not an issue.
- mlx-whisper's `transcribe()` supports `word_timestamps`, `initial_prompt` and `hallucination_silence_threshold`.

## Light research

- Learning science: Dunlosky et al. (2013) rate practice testing and distributed practice as the highest-utility techniques, and rereading, highlighting and summarising as low. This is why the app leans on spaced term review, end-of-lecture quizzes and exam mode rather than summaries. https://www.sciencedaily.com/releases/2013/01/130110111734.htm
- Existing apps (Coconote, Turbo AI) turn recordings and PDFs into notes, flashcards and quizzes in the cloud. study-desk differs in being local, slide-aligned (what the lecturer said on each slide) and organised automatically by Moodle and the schedule.
