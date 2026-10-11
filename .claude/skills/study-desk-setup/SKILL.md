---
name: study-desk-setup
description: Install study-desk on this Mac, open its setup page and help until it works. Use when someone asks to install, set up, configure, update, repair or uninstall study-desk, for example "set up study-desk", "study-desk'i kur", "kurulumu yap", "study-desk açılmıyor".
---

# Setting up study-desk

study-desk is a local web app (FastAPI on `127.0.0.1:4620`) that runs as a launchd agent. Installing it is one script; everything personal (study folder, Moodle, courses, class times) is then entered on the app's own setup page in the browser. Your job is to get the person to that page with a working install, and to help when something fails. Talk to them in their language; the app's interface is in Turkish.

## 1. Check the machine (read-only)

Run and summarise in plain words:

```sh
uname -sm                      # Darwin arm64 expected; on Intel only transcription is unavailable
command -v uv && uv --version  # required
command -v claude && claude --version
command -v ffmpeg; command -v mlx_whisper   # optional, only for lecture recordings
```

- **uv missing:** it is required. Offer `curl -LsSf https://astral.sh/uv/install.sh | sh`, run it only after they agree, then open a new shell (or source the env file the installer names) so `uv` is on the PATH.
- **claude:** you are running inside Claude Code, so it is installed. The app calls the same `claude` in the background with the person's login; the installer passes its folder to the background service.
- **ffmpeg / mlx_whisper:** ask whether they will upload lecture recordings. Only if yes, offer `brew install ffmpeg` and `uv tool install mlx-whisper` (Homebrew must exist: `command -v brew`). The whisper model (about 1.5 GB) downloads by itself on the first recording.

Do not install anything without a yes.

## 2. Install

From the repository root:

```sh
./scripts/install.sh
```

It runs `uv sync`, writes `~/Library/LaunchAgents/com.studydesk.server.plist`, starts the service, waits for `http://127.0.0.1:4620/api/health` and opens the app in the browser. On first run the app shows its setup page (`http://127.0.0.1:4620/#/setup`).

If the health check fails, read the end of `~/Library/Logs/StudyDesk/server.log` and fix the cause:

| Log says | Fix |
|---|---|
| `address already in use` | Another program uses 4620. Add `port = 4621` to `~/Library/Application Support/StudyDesk/config.toml` (create the file if needed), run the installer again, use the new port. |
| `config.toml: ...` or `courses.toml: ...` (a TOML error) | Show the line to the person and fix the file with them. |
| a Python import error | Run `uv sync` in the repo and look at its error. |

## 3. The setup page

Tell the person the page is open and what each step wants:

1. **Ders klasörü:** the folder for their course material (one subfolder per course). Any path; it is created. iCloud is fine.
2. **Moodle (optional):** the Moodle address and their token. **Never ask for the token in chat and never handle it yourself.** They paste it into the page, which checks it and stores it only in the macOS Keychain. Where to find it: Moodle → their name → Preferences → Security keys → the "Moodle mobile web service" row. If that row is missing, logging in once with the Moodle phone app creates it. If the university disabled web services, they skip this step and add courses by hand.
3. **Dersler:** tick this term's courses; codes and folders are suggested.
4. **Ders programı:** "Syllabus'tan oku" lets Claude read class times, exams and weekly topics from the syllabus PDF; they check the form and save. Class times decide which course a dropped recording belongs to, so they should be right.
5. **Kontroller:** one tiny Claude call and the recording tools.

To see where they are without asking them to describe the page:

```sh
curl -s http://127.0.0.1:4620/api/setup | python3 -m json.tool   # never contains the token
curl -s http://127.0.0.1:4620/api/health                          # setup_complete: true when done
```

Common problems on the page:

| Message | Meaning |
|---|---|
| "Moodle bu token'ı kabul etmedi" | Wrong key copied; take the "Moodle mobile web service" one. |
| "Bu adreste Moodle bulunamadı" | Wrong address (they pasted a page that is not the Moodle root) or web services are off. |
| "Claude Code'a giriş yapılmamış" | Run `claude` once in a terminal and log in. |
| "Syllabus'ta ... bulunamadı" / "okunabilir metin yok" | The PDF is a scan or has no schedule; fill the form by hand. |
| A banner says the server still runs with old settings | Press its "Yeniden başlat" button; if that does not help, run the installer again. |

## 4. Done

Setup is complete when `/api/health` reports `"setup_complete": true`. Point them to `http://127.0.0.1:4620` (bookmark it) and to "Ayarlar" in the top bar for later changes.

## Updating and uninstalling

- Update: `git pull && ./scripts/install.sh`.
- Uninstall: `./scripts/uninstall.sh` stops the app and removes the service; their study folder, `~/Library/Application Support/StudyDesk/` and the logs stay. Delete those only if they explicitly ask, and show what will be deleted first.

## Rules

- Never read, print or store the Moodle token (no `security find-generic-password -w`, no echoing it, no writing it to files).
- Their study folder, `courses.toml`, the database and transcripts are personal data: never copy them into the repository or commit them.
- Do not change the app's code to make one setup work. If something is a bug, say so and suggest opening an issue on the repository.
