# 3. Personal data outside the repository

- Status: accepted

## Context
The repository is public. A student's slides, lecture transcripts, board photos, schedule, Moodle token and study history are personal, and the course material is often copyrighted. They must never be committed by accident.

On macOS, the Desktop and Documents folders are often synced to iCloud. Git repositories and SQLite databases can be corrupted when iCloud syncs them mid-write.

## Decision
- Code lives in the repository. Personal material lives in a **data root**, a folder the user chooses in the config (for example a folder on the Desktop). Course folders, transcripts, photos and notes go there.
- The database lives in `~/Library/Application Support/StudyDesk/`, outside iCloud. A daily copy can be written into the data root as a backup.
- `.gitignore` excludes data, databases, audio and local config.
- Secrets (the Moodle token) are never in the repo or in a committed file.

## Consequences
- The data root can sit in iCloud safely, because it holds plain files only. The user can also read notes and slides from other devices.
- First-run setup has to ask for the data root.
- Personal adapters (for example, converting someone's own calendar script into the schedule format) stay outside the repo.
