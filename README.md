# study-desk

A local study companion for university courses. It runs on your Mac as a small web app on `localhost` and turns your course slides into a slide-by-slide study session, with Claude as the tutor. Around that loop it keeps everything a course produces: Moodle files, your lecture recordings, the schedule and exam dates, the terms you learn, and where you left off.

> **Status: alpha (v0.1).** Used daily by the maintainer for five courses. The interface is in Turkish for now; explanations can be in Turkish, English, German, French or Spanish.

## What it does

- **Slide by slide.** Open a course and continue where you left off. Press "Sıradaki" (next) and the current slide is explained in your language; technical terms stay in English, the language of the exam. The next slide is prepared in the background, so moving on is quick.
- **Explanation controls.** Short, normal or detailed. "Daha basit" explains the slide again from zero, "Örnek ver" gives a worked example, "Formülü aç" walks through a formula. "Biliyorum, geç" skips a slide and remembers that you know it.
- **One input bar.** Ask about the slide ("bu formül ne?", "what is a linear separator?") or give a command ("462 lec2 aç", "14. slayta git", "kaldığım yer") in the same box.
- **Moodle sync.** New course PDFs are downloaded every time you open the app.
- **Lecture recordings.** Record the lecture with Voice Memos, then drag the recording into the app. It is matched to the right course by the time it was recorded, transcribed on your Mac and checked. A broken transcript is reported in plain words with a fix to try. Good transcripts are matched to the slides, so every explanation includes what the lecturer said on that slide, and exam or homework hints show up on the home screen.
- **Live mode.** A light mode for following a lecture as it happens: the newest deck of the class that is on now, short explanations, a faster model.
- **Terms.** Every new term goes into a glossary with a one-sentence English definition.
- **Today screen.** Today's classes with the week's topic, upcoming exams, where to continue, new Moodle files.
- **Search and notes.** Every explanation and question is searchable; each study session leaves a short notes file in the course folder.

Planned: board photos matched to slides, daily spaced-repetition review of terms, textbooks linked to syllabus topics, an exam mode. See [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md).

## Requirements

- A Mac. Lecture transcription needs Apple Silicon (M1 or later); everything else runs on any recent Mac.
- [Claude Code](https://docs.claude.com/en/docs/claude-code), installed and logged in with your Claude account. Explanations run on your own Claude plan and count toward its limits.
- [uv](https://docs.astral.sh/uv/), which also installs the right Python for you: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Optional: a Moodle account (for automatic course files), and `ffmpeg` and `mlx-whisper` (for lecture recordings). The setup page tells you what is missing.

## Install

### With Claude Code (easiest)

```sh
git clone https://github.com/CaganIslam/study-desk.git
cd study-desk
claude
```

Then ask Claude Code to set it up, for example "set up study-desk" or "study-desk'i kur". The repository has a setup skill: it checks what is missing, runs the installer, opens the setup page and helps if something fails.

### By hand

```sh
git clone https://github.com/CaganIslam/study-desk.git
cd study-desk
./scripts/install.sh
```

The installer prepares the Python environment, registers a background service that starts the app at login (and restarts it if it stops), and opens **http://127.0.0.1:4620** in your browser. Bookmark that address; that is the app.

## The setup page

On first run the app opens its setup page. You can come back to it any time from **Ayarlar** (settings) in the top bar.

1. **Course folder.** Where your course material lives, one subfolder per course. Pick an existing folder or type a new path; it is created for you. It may be in iCloud Drive or on the Desktop. The database and settings stay on this Mac. Here you also choose the language of the explanations.
2. **Moodle (optional).** Paste your Moodle address and your Moodle token (see below). The app checks the connection on the spot.
3. **Courses.** With Moodle, your enrolled courses are listed with this term's first: tick yours. The app suggests a short code ("CS 101"), a name and a folder; aliases are what you might type in the input bar ("101", "algo"). Without Moodle, add courses by hand.
4. **Schedule.** Pick a course's syllabus PDF and press "Syllabus'tan oku": Claude reads the class times, exam dates and weekly topics, and you check them in a form before saving. Class times matter: a dropped recording is matched to a course by the time it was recorded. You can also fill the form by hand, or add a syllabus PDF from your computer.
5. **Checks.** One tiny call confirms that Claude Code works. The tools for recordings are checked too, with the command to install whatever is missing.

The setup page writes two plain files that you may also edit by hand: `~/Library/Application Support/StudyDesk/config.toml` (folder, language, Moodle address) and `courses.toml` in your course folder ([format](docs/courses-toml.md)).

### Your Moodle token

1. Log in to Moodle in the browser.
2. Click your name (top right) and open **Preferences**.
3. Open **Security keys**.
4. Copy the key on the **Moodle mobile web service** row and paste it on the setup page.

If that row is missing, log in once with the Moodle app on your phone; the key appears after that. If your university has switched web services off, skip the Moodle step: add your courses by hand and put the PDFs into each course's `slides` folder yourself (the setup page has a button that opens the folder in Finder).

The token is stored only in your Mac's Keychain (item `study-desk-moodle`). It is never written to a file or a log.

## Daily use

- Open **http://127.0.0.1:4620**. The Today screen shows your classes, exams and where to continue.
- Open a course, pick a deck, and press **Sıradaki** (or Enter). Type questions or commands into the bar at the bottom (⌘K focuses it).
- **Recordings:** record with Voice Memos on your phone, tablet or Mac. On the Mac, drag the recording from the Voice Memos app (or a file from Finder) anywhere into the study-desk window, or use **＋ Ses kaydı yükle**. The audio is deleted once its transcript is saved.
- **Live mode:** type "canlı" in the bar or use the button on the Today screen while a class is on.
- **PDFs without Moodle:** drop them into `<course folder>/slides/`; they show up as decks.

Everything you produce stays in your course folder:

```
<course folder>/
  courses.toml
  CS101 Algorithms/
    slides/          PDFs from Moodle or added by you
    transcripts/     one text file per lecture recording
    notes/           a short summary of each study session
```

## What leaves your Mac

- For each explanation or question: the current slide (image and text), a short context, the lecturer's words for that slide, and your question go to Claude through Claude Code.
- When a recording is matched to slides: its transcript and the slide titles go to Claude.
- On the setup page: the text of the syllabus you ask it to read goes to Claude.
- Your Moodle token and file requests go only to your university's Moodle.
- Audio never leaves the Mac and is not kept. [`docs/STACK.md`](docs/STACK.md) lists every provider and what it receives.

## Updating

```sh
cd study-desk
git pull
./scripts/install.sh
```

## Uninstalling

`./scripts/uninstall.sh` stops the app and removes the background service. Your course folder, the database (`~/Library/Application Support/StudyDesk/`) and the logs (`~/Library/Logs/StudyDesk/`) are kept; delete them yourself if you want them gone. The Moodle token can be removed from the Keychain Access app (search for `study-desk-moodle`).

## Troubleshooting

| Problem | What to do |
|---|---|
| The page does not open | Run `./scripts/install.sh` again. The log is in `~/Library/Logs/StudyDesk/server.log`. |
| Port 4620 is taken by something else | Add `port = 4621` to `~/Library/Application Support/StudyDesk/config.toml`, run the installer again, use the new port. |
| "Claude Code'a giriş yapılmamış" | Run `claude` once in Terminal and log in. |
| "Claude kullanım limiti doldu" | Your Claude plan's limit is reached. Slides and saved explanations stay available; new explanations work again when the limit resets. |
| Moodle does not accept the token | Copy the key again from Security keys; make sure it is the "Moodle mobile web service" row. |
| A recording says the transcript looks broken | Use "Büyük modelle dene" on the recording; the larger model is slower but more robust. |
| A recording landed in the wrong course or none | Check the class times on the setup page; you can also pick the course on the recording. |

## Importing earlier study sessions

If you studied with Claude Code (or anything else) before, `uv run study-desk import-sessions history.json` brings those sessions in: where you stopped, what you asked, which terms were hard. The format is in [`docs/import-format.md`](docs/import-format.md).

## Development

```sh
uv sync
uv run pytest
```

To run a second copy next to the installed one, give it its own app directory and port: put `port = 4621` into `$DIR/config.toml`, then `STUDYDESK_HOME=$DIR uv run study-desk`. Tests never call the real Claude or Moodle.

Work is tracked in GitHub issues and milestones. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before writing code; [`docs/PROGRESS.md`](docs/PROGRESS.md) is the log of what has been built.

## License

[MIT](LICENSE)
