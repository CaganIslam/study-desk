-- Questions asked in live mode while the lecture's deck was not on Moodle yet.
-- They are attached to slides later, when the deck arrives (Milestone 4).
CREATE TABLE deckless_questions (
    id          INTEGER PRIMARY KEY,
    course_code TEXT    NOT NULL,
    question    TEXT    NOT NULL,
    answer_md   TEXT    NOT NULL,
    terms_json  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX deckless_by_course ON deckless_questions (course_code, created_at);
