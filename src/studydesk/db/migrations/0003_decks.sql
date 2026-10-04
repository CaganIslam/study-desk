-- PDF decks found in the course folders, and their logical slides.
-- A logical slide groups the PDF pages of one animation build.
CREATE TABLE decks (
    id          INTEGER PRIMARY KEY,
    course_code TEXT    NOT NULL,
    path        TEXT    NOT NULL UNIQUE,
    sha256      TEXT    NOT NULL,
    mtime       REAL    NOT NULL,
    size        INTEGER NOT NULL,
    pages       INTEGER NOT NULL,
    numbered    INTEGER NOT NULL,  -- 1 when slide labels come from the deck's own footer numbers
    scanned_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE slides (
    deck_id    INTEGER NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,  -- 1-based position in the deck
    label      TEXT    NOT NULL,  -- what the lecturer calls it: the footer number, else idx
    title      TEXT    NOT NULL,
    text       TEXT    NOT NULL,
    first_page INTEGER NOT NULL,  -- 0-based PDF page indexes
    last_page  INTEGER NOT NULL,
    PRIMARY KEY (deck_id, idx)
);
