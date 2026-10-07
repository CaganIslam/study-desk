-- Which minutes of a recording belong to which slide, as found by Claude.
-- deck_id/idx are NULL for parts of the lecture without a matching slide (a topic only).
CREATE TABLE recording_sections (
    id           INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings (id) ON DELETE CASCADE,
    deck_id      INTEGER REFERENCES decks (id) ON DELETE SET NULL,
    idx          INTEGER,
    start_s      REAL    NOT NULL,
    end_s        REAL    NOT NULL,
    topic        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX sections_by_slide ON recording_sections (deck_id, idx);

-- Things the lecturer stressed: exam hints, homework, deadlines, "this is important".
CREATE TABLE emphasis (
    id           INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings (id) ON DELETE CASCADE,
    course_code  TEXT    NOT NULL,
    at_s         REAL    NOT NULL,
    kind         TEXT    NOT NULL,   -- exam | homework | important | admin
    quote        TEXT    NOT NULL
);

ALTER TABLE recordings ADD COLUMN aligned_at TEXT;

-- An explanation made before the lecturer's words were known is stale once they are.
ALTER TABLE explanations ADD COLUMN notes_sha TEXT NOT NULL DEFAULT '';
