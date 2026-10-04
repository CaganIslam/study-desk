-- Questions typed in the input bar about a slide, with Claude's answers.
CREATE TABLE questions (
    id         INTEGER PRIMARY KEY,
    deck_id    INTEGER NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,
    question   TEXT    NOT NULL,
    answer_md  TEXT    NOT NULL,
    terms_json TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX questions_by_slide ON questions (deck_id, idx);
