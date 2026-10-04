import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from studydesk.config import Config
from studydesk.courses import Catalog, Course
from studydesk.db import Database
from studydesk.decks import SIZES, get_slides, group_pages, list_decks, render, scan
from studydesk.server import create_app
from tests.pdfgen import make_pdf

# --- grouping (plain text, no PDF needed) -------------------------------------


def test_footer_numbers_group_builds():
    texts = [
        "Course Title\nAuthor 1",
        "Topic A\nfirst point\nAuthor 2",
        "Topic A\nfirst point\nsecond point\nAuthor 2",
        "Topic B\nAuthor 3",
    ]
    slides, numbered = group_pages(texts)
    assert numbered is True
    assert [(s.label, s.first_page, s.last_page) for s in slides] == [("1", 0, 0), ("2", 1, 2), ("3", 3, 3)]
    assert slides[1].title == "Topic A" and "second point" in slides[1].text


def test_unnumbered_builds_are_grouped_by_growing_text():
    texts = ["Topic A\nfirst", "Topic A\nfirst\nsecond", "Topic B\nother", "Topic B\nunrelated"]
    slides, numbered = group_pages(texts)
    assert numbered is False
    assert [(s.label, s.first_page, s.last_page) for s in slides] == [("1", 0, 1), ("2", 2, 2), ("3", 3, 3)]


def test_numbers_that_are_not_frame_numbers_are_ignored():
    # "CS 443" ends every page: larger than the page count, so not a frame number.
    slides, numbered = group_pages(["Intro\nCS 443", "Next\nCS 443"])
    assert numbered is False and len(slides) == 2


def test_decreasing_numbers_are_not_frame_numbers():
    slides, numbered = group_pages(["A\n3", "B\n1", "C\n2"])
    assert numbered is False


# --- scanning real (synthetic) PDF files ---------------------------------------

COURSE = Course(code="CS 101", name="Algorithms", folder="CS101")


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "study.db")
    db.migrate()
    slides = tmp_path / "data" / "CS101" / "slides"
    slides.mkdir(parents=True)
    return db, tmp_path / "data", slides


def write(path, pages):
    path.write_bytes(make_pdf(pages))


def test_scan_indexes_decks_in_natural_order(env):
    db, data, slides = env
    write(slides / "Lec10.pdf", [["Ten", "A 1"]])
    write(slides / "Lec2.pdf", [["Two", "first", "A 1"], ["Two", "first", "second", "A 1"], ["Next", "A 2"]])
    scan(db, Catalog(courses=(COURSE,)), data)
    decks = list_decks(db, "CS 101")
    assert [d["filename"] for d in decks] == ["Lec2.pdf", "Lec10.pdf"]
    lec2 = decks[0]
    assert (lec2["pages"], lec2["slides"], lec2["numbered"]) == (3, 2, True)
    first = get_slides(db, lec2["id"])[0]
    assert first["title"] == "Two" and "second" in first["text"]


def test_changed_deck_keeps_its_id_and_removed_deck_disappears(env):
    db, data, slides = env
    catalog = Catalog(courses=(COURSE,))
    write(slides / "Lec1.pdf", [["One", "A 1"]])
    write(slides / "Lec2.pdf", [["Two", "A 1"]])
    scan(db, catalog, data)
    ids = {d["filename"]: d["id"] for d in list_decks(db, "CS 101")}
    write(slides / "Lec1.pdf", [["One", "A 1"], ["More", "A 2"]])
    stat = (slides / "Lec1.pdf").stat()
    os.utime(slides / "Lec1.pdf", (stat.st_atime, stat.st_mtime + 5))
    (slides / "Lec2.pdf").unlink()
    scan(db, catalog, data)
    decks = list_decks(db, "CS 101")
    assert [(d["filename"], d["id"], d["slides"]) for d in decks] == [("Lec1.pdf", ids["Lec1.pdf"], 2)]


def test_unreadable_pdf_is_skipped(env):
    db, data, slides = env
    (slides / "broken.pdf").write_bytes(b"not a pdf")
    write(slides / "ok.pdf", [["Fine", "A 1"]])
    scan(db, Catalog(courses=(COURSE,)), data)
    assert [d["filename"] for d in list_decks(db, "CS 101")] == ["ok.pdf"]


def test_render_is_cached_and_sized(env, tmp_path):
    db, data, slides = env
    write(slides / "Lec1.pdf", [["One", "A 1"]])
    scan(db, Catalog(courses=(COURSE,)), data)
    deck_id = list_decks(db, "CS 101")[0]["id"]
    with db.connect() as conn:
        deck = conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    slide = get_slides(db, deck_id)[0]
    path = render(deck, slide, "ai", tmp_path / "cache")
    assert max(Image.open(path).size) == SIZES["ai"]
    mtime = path.stat().st_mtime
    assert render(deck, slide, "ai", tmp_path / "cache") == path and path.stat().st_mtime == mtime


# --- API contract --------------------------------------------------------------


@pytest.fixture
def client(home, tmp_path):
    data = tmp_path / "apidata"
    slides = data / "CS101" / "slides"
    slides.mkdir(parents=True)
    write(slides / "Lec1.pdf", [["Intro", "A 1"], ["Topic", "x", "A 2"], ["Topic", "x", "y", "A 2"], ["End", "A 3"]])
    (data / "courses.toml").write_text('[[courses]]\ncode = "CS 101"\nname = "A"\nfolder = "CS101"\n')
    return TestClient(create_app(Config(home=home, data_root=data)))


def test_deck_and_slide_endpoints(client):
    decks = client.get("/api/courses/CS 101/decks").json()
    assert set(decks) == {"code", "decks"}
    deck = decks["decks"][0]
    assert set(deck) == {"id", "filename", "pages", "slides", "numbered"}
    listing = client.get(f"/api/decks/{deck['id']}/slides").json()
    assert set(listing) == {"deck", "slides"} and set(listing["slides"][0]) == {"idx", "label", "title", "marks", "explained", "questions"}
    detail = client.get(f"/api/decks/{deck['id']}/slides/2").json()
    assert set(detail) == {"idx", "label", "title", "text", "pages", "total", "prev", "next"}
    assert detail["pages"] == [2, 3] and detail["prev"] == 1 and detail["next"] == 3
    assert client.get(f"/api/decks/{deck['id']}/find", params={"label": "2"}).json() == {"idx": 2, "label": "2"}
    image = client.get(f"/api/decks/{deck['id']}/slides/2/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"


def test_missing_things_use_error_shape(client):
    assert client.get("/api/courses/NOPE/decks").json()["error"]["code"] == "course_not_found"
    assert client.get("/api/decks/999/slides").json()["error"]["code"] == "deck_not_found"
    deck_id = client.get("/api/courses/CS 101/decks").json()["decks"][0]["id"]
    assert client.get(f"/api/decks/{deck_id}/slides/99").json()["error"]["code"] == "slide_not_found"
    assert client.get(f"/api/decks/{deck_id}/slides/1/image", params={"size": "huge"}).status_code == 400
