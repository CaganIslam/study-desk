-- What the student looked at and when. Sessions, resume points and summaries are derived from it.
CREATE TABLE activity (
    id      INTEGER PRIMARY KEY,
    deck_id INTEGER NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    idx     INTEGER NOT NULL,
    kind    TEXT    NOT NULL,             -- view
    at      TEXT    NOT NULL              -- ISO 8601, UTC
);
CREATE INDEX activity_by_time ON activity (at);
CREATE INDEX activity_by_deck ON activity (deck_id, at);

-- Session notes already written to a course's notes/ folder.
CREATE TABLE session_notes (
    course_code TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    path        TEXT NOT NULL,
    PRIMARY KEY (course_code, started_at)
);

-- Full-text search over explanations and questions. `body` is folded (lowercase,
-- Turkish letters to ASCII) so "duzenlilestirme" finds "Düzenlileştirme".
CREATE VIRTUAL TABLE search_index USING fts5 (
    kind UNINDEXED,        -- explanation | question
    deck_id UNINDEXED,
    idx UNINDEXED,
    course_code UNINDEXED,
    title,
    body,
    tokenize = "unicode61 remove_diacritics 2"
);
