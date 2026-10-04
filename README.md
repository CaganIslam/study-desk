# study-desk

A local-first study companion for university courses. It runs on your Mac as a small web app on `localhost` and turns your course material into a slide-by-slide study session, with Claude as the tutor.

> **Status: early development.** Nothing is runnable yet. The plan and the milestones are in [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md).

## What it does (planned)

- **Slide by slide.** Open a course and continue where you left off. Press "next" to get a short explanation of the current slide in your own language. Technical terms stay in English, since that is the language of the exam.
- **One input bar.** Type a question about the slide ("what is a linear separator?") or a command ("open ML lecture 2", "go to slide 30") in the same box.
- **Explanation controls.** Short, normal or detailed explanations. A "simpler" button explains the slide again from scratch, and "I know this, skip" moves on and remembers what you already know.
- **Lecture recordings.** Record the lecture with Voice Memos on your phone or tablet, then drag the recording into the app. It is matched to the right course by the time it was recorded, transcribed locally and checked. If the transcript comes out broken, the app tells you and suggests a fix. Good transcripts are aligned to the slides, so every explanation includes what the lecturer said on that slide.
- **Board photos.** Photos of the board are matched to the course and the slide by the time they were taken, and their content is transcribed.
- **Terms.** Every new term goes into a glossary with a one-sentence English definition you could write in an exam. A daily spaced-repetition review asks you, among other things, to write the English term from its meaning.
- **Moodle sync.** New course files are downloaded when you open the app.
- **Live mode.** A lightweight mode for following along during a lecture.
- **Exam mode.** Summaries and quizzes built from the questions you asked and from what the lecturer emphasised.

## How it works

- Everything runs on your machine. Slides, transcripts, photos and notes stay in a folder you choose. They never go into this repository.
- Explanations come from [Claude Code](https://docs.claude.com/en/docs/claude-code) running headless (`claude -p`) on your own Claude subscription. For each explanation, the current slide (image and text) and a short context are sent to Claude. Nothing else leaves the machine. [`docs/STACK.md`](docs/STACK.md) lists exactly what goes where.
- Audio is transcribed locally with [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper). The audio itself is not stored, only the transcript.

## Requirements (planned)

- macOS on Apple Silicon (local transcription uses MLX).
- Claude Code, installed and logged in
- Python 3.12+ with [uv](https://docs.astral.sh/uv/), and ffmpeg
- Optional: a Moodle account with web service access, for automatic course file sync

## Importing earlier study sessions

If you studied with Claude Code (or anything else) before, `study-desk import-sessions history.json` brings those sessions in: where you stopped, what you asked, which terms were hard. The format is in [`docs/import-format.md`](docs/import-format.md).

## Language

The interface starts in Turkish. The explanation language is a setting, and an English interface is planned.

## Contributing

Work is tracked in GitHub issues and milestones. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before writing code.

## License

[MIT](LICENSE)
