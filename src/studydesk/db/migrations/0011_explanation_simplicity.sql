-- Explanations are also cached per simplicity: normal, simple or very_simple.
-- The new column joins the primary key, which SQLite can only change by
-- rebuilding the table. Existing explanations become "normal"; rows of decks
-- that no longer exist could never be shown, so they are not copied.
CREATE TABLE explanations_new (
    deck_id         INTEGER NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    level           TEXT    NOT NULL,
    variant         TEXT    NOT NULL DEFAULT '',
    language        TEXT    NOT NULL,
    simplicity      TEXT    NOT NULL DEFAULT 'normal',
    deck_sha        TEXT    NOT NULL,
    explanation_md  TEXT    NOT NULL,
    summary         TEXT    NOT NULL,
    terms_json      TEXT    NOT NULL,
    exam_notes_json TEXT    NOT NULL,
    duration_ms     INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    notes_sha       TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (deck_id, idx, level, variant, language, simplicity)
);

INSERT INTO explanations_new (
    deck_id, idx, level, variant, language, deck_sha, explanation_md, summary,
    terms_json, exam_notes_json, duration_ms, created_at, notes_sha
)
SELECT deck_id, idx, level, variant, language, deck_sha, explanation_md, summary,
       terms_json, exam_notes_json, duration_ms, created_at, notes_sha
FROM explanations
WHERE deck_id IN (SELECT id FROM decks);

DROP TABLE explanations;
ALTER TABLE explanations_new RENAME TO explanations;
