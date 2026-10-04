-- Files this app downloaded from Moodle, so unchanged files are not downloaded again.
CREATE TABLE moodle_files (
    course_code   TEXT    NOT NULL,
    fileurl       TEXT    NOT NULL,
    filename      TEXT    NOT NULL,
    timemodified  INTEGER NOT NULL,
    filesize      INTEGER NOT NULL,
    local_path    TEXT    NOT NULL,
    downloaded_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (course_code, fileurl)
);
