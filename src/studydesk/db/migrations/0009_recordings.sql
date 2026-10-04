-- Lecture recordings dropped into the app. The audio itself is never kept once its
-- transcript is saved; only metadata, the transcript and its quality check stay.
CREATE TABLE recordings (
    id              INTEGER PRIMARY KEY,
    sha256          TEXT    NOT NULL UNIQUE,
    source_name     TEXT    NOT NULL,
    started_at      TEXT    NOT NULL,           -- ISO 8601, UTC (from the file's creation_time)
    duration_s      REAL    NOT NULL,
    course_code     TEXT,                       -- NULL until matched or chosen
    status          TEXT    NOT NULL,           -- needs_course | queued | transcribing | done | bad_quality | failed
    audio_path      TEXT,                       -- the app's own copy while it is needed, else NULL
    transcript_path TEXT,
    model           TEXT,
    quality_json    TEXT,
    error           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE transcript_segments (
    recording_id INTEGER NOT NULL REFERENCES recordings (id) ON DELETE CASCADE,
    start_s      REAL    NOT NULL,
    end_s        REAL    NOT NULL,
    text         TEXT    NOT NULL
);
CREATE INDEX segments_by_recording ON transcript_segments (recording_id, start_s);
