# Stack & providers

> The internal stack plus every external provider and dependency: role, tier, env vars, data sent, data residency, cost, and link.
> Doubles as the privacy / data-flow map: **check this before sending confidential data to any provider.**

## Stack

- language / runtime: Python 3.12 (uv), plain JavaScript in the browser
- framework: FastAPI
- datastore: SQLite with FTS5, in `~/Library/Application Support/StudyDesk/`
- hosting: the user's own Mac. A launchd agent runs the server at login on `127.0.0.1`.

Local libraries (no data leaves the machine):

| Library | Role | License |
|---|---|---|
| mlx-whisper | transcription on Apple Silicon | MIT |
| ffmpeg | audio decoding (reads the AAC track of `.qta` / `.m4a`) | LGPL/GPL (system install) |
| pypdfium2 | slide rendering and text extraction | Apache-2.0 / BSD |
| py-fsrs | spaced-repetition scheduling | MIT |
| KaTeX, marked, highlight.js | formulas, markdown, code in the browser (vendored) | MIT / BSD |

## External providers

| Provider | Role | Tier/plan | Env var(s) | Data sent | Residency | Cost | Link |
|---|---|---|---|---|---|---|---|
| Anthropic Claude, via Claude Code | Explanations, answers, command fallback, transcript-to-slide alignment, board photo reading, term extraction | The user's own Claude plan (Claude Code login) | none (Claude Code's own login) | current slide image and text, a short context summary, the lecturer's words for that slide, the user's question, known-term list; for alignment, the lecture transcript and slide titles | Anthropic | Counts toward the user's plan limits | https://docs.claude.com/en/docs/claude-code |
| Moodle web service (the user's university) | List and download course PDFs | The user's account | URL in `config.toml` (`[moodle] url`); token in the macOS Keychain (service `study-desk-moodle`, account = URL), `MOODLE_TOKEN` overrides it | the token and file requests | the university's server | free | https://docs.moodle.org/dev/Web_services |
| Hugging Face Hub | One-time download of the whisper model | free | none | nothing personal (model download only) | - | free | https://huggingface.co/mlx-community/whisper-large-v3-turbo |

## Data that may leave the box

- Slide image and text, short context, lecturer's words for the slide, the user's questions → Anthropic (via Claude Code)
- Lecture transcripts (alignment call) and board photos (reading call) → Anthropic (via Claude Code)
- Moodle token and requests → the user's own Moodle server
- Nothing else. Audio never leaves the machine and is not stored.
