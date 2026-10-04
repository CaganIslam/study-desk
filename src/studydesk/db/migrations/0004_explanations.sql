-- Explanations from Claude, cached per slide, length, variant and language.
-- deck_sha ties a cached explanation to the deck version it was made for.
CREATE TABLE explanations (
    deck_id         INTEGER NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    level           TEXT    NOT NULL,
    variant         TEXT    NOT NULL DEFAULT '',
    language        TEXT    NOT NULL,
    deck_sha        TEXT    NOT NULL,
    explanation_md  TEXT    NOT NULL,
    summary         TEXT    NOT NULL,
    terms_json      TEXT    NOT NULL,
    exam_notes_json TEXT    NOT NULL,
    duration_ms     INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (deck_id, idx, level, variant, language)
);

-- Per-slide marks set by the student, e.g. "known" from "I know this, skip".
CREATE TABLE slide_marks (
    deck_id    INTEGER NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,
    mark       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (deck_id, idx, mark)
);
