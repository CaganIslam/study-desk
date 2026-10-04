-- The glossary. A term is shared across courses; `key` is the folded, normalised
-- form used to recognise the same term written slightly differently.
CREATE TABLE terms (
    id            INTEGER PRIMARY KEY,
    key           TEXT    NOT NULL UNIQUE,
    term          TEXT    NOT NULL,
    meaning       TEXT    NOT NULL DEFAULT '',
    definition_en TEXT    NOT NULL DEFAULT '',
    example       TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL DEFAULT 'new',   -- new | hard | known
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE term_courses (
    term_id     INTEGER NOT NULL REFERENCES terms (id) ON DELETE CASCADE,
    course_code TEXT    NOT NULL,
    PRIMARY KEY (term_id, course_code)
);

-- Where a term came up: a slide's explanation or a question asked on a slide.
CREATE TABLE term_occurrences (
    term_id INTEGER NOT NULL REFERENCES terms (id) ON DELETE CASCADE,
    deck_id INTEGER NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    idx     INTEGER NOT NULL,
    source  TEXT    NOT NULL,   -- explanation | question
    PRIMARY KEY (term_id, deck_id, idx, source)
);
