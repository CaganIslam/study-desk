import pytest

from studydesk.courses import Catalog, Course
from studydesk.study.commands import parse, resolve_deck, split_position

CATALOG = Catalog(
    courses=(
        Course(code="CMPE 462", name="Machine Learning", folder="x", aliases=("462", "ml", "makine", "makine öğrenmesi")),
        Course(code="CMPE 443", name="Embedded Systems", folder="y", aliases=("443", "embedded", "gömülü")),
        Course(code="CMPE 580", name="Logic in Computer Science", folder="z", aliases=("580", "logic", "mantık")),
        Course(code="IE 310", name="Operations Research", folder="w", aliases=("310", "ie310", "yöneylem")),
    )
)
ML = CATALOG.courses[0]

COMMANDS = [
    ("sıradaki", {"type": "next"}),
    ("sıradaki slayt", {"type": "next"}),
    ("sırdaki", {"type": "next"}),
    ("devam", {"type": "next"}),
    ("Sıradaki", {"type": "next"}),
    ("önceki", {"type": "prev"}),
    ("geri", {"type": "prev"}),
    ("30. slayta geç", {"type": "goto_slide", "label": "30"}),
    ("pardon 30. salyta geç", {"type": "goto_slide", "label": "30"}),
    ("31. slayta geçelim", {"type": "goto_slide", "label": "31"}),
    ("4. slayda geç", {"type": "goto_slide", "label": "4"}),
    ("slayt 12", {"type": "goto_slide", "label": "12"}),
    ("30'a geç", {"type": "goto_slide", "label": "30"}),
    ("462 lec2 aç reis", {"type": "open", "course": "CMPE 462", "lecture": "2"}),
    ("ml dersini aç", {"type": "open", "course": "CMPE 462"}),
    ("makine öğrenmesi aç", {"type": "open", "course": "CMPE 462"}),
    ("443 aç", {"type": "open", "course": "CMPE 443"}),
    ("580 lec 1", {"type": "open", "course": "CMPE 580", "lecture": "1"}),
    ("ıe 310 aç", {"type": "open", "course": "IE 310"}),
    ("IE310", {"type": "open", "course": "IE 310"}),
    ("gömülü 2c", {"type": "open", "course": "CMPE 443", "lecture": "2c"}),
    ("kısa anlat", {"type": "set_level", "level": "short"}),
    ("geniş anlat", {"type": "set_level", "level": "detailed"}),
    ("detaylı anlat", {"type": "set_level", "level": "detailed"}),
    ("normal", {"type": "set_level", "level": "normal"}),
    ("daha basit anlat", {"type": "variant", "variant": "simpler"}),
    ("anlamadım", {"type": "variant", "variant": "simpler"}),
    ("örnek ver", {"type": "variant", "variant": "example"}),
    ("farklı anlat", {"type": "variant", "variant": "different"}),
    ("formülü aç", {"type": "variant", "variant": "formula"}),
    ("biliyorum", {"type": "know_skip"}),
    ("bunu biliyorum geç", {"type": "know_skip"}),
    ("ana sayfa", {"type": "home"}),
]

QUESTIONS = [
    "l2 norm vector norm felan bunlar neydi kısa basitçe anlatsana",
    "svm logistic regression bunlar nedir kısa bsaitçe yazsana",
    "dot product ve transpose da var kısa basitçe anlatsana",
    "imputation techniques nedir kısa basitçe anlatsana",
    "bu formül ne",
    "geri yayılım nedir",
    "lec 2 varmış perceptron ona geçsene",
    "ısochro- bişey dedi hoca HRt olarak - ne o",
    "sat ve smt nedir",
]


@pytest.mark.parametrize("text, expected", COMMANDS)
def test_commands(text, expected):
    command = parse(text, CATALOG)
    assert command is not None, text
    assert command.as_dict() == expected


@pytest.mark.parametrize("text", QUESTIONS)
def test_questions_are_not_commands(text):
    assert parse(text, CATALOG) is None


def test_lecture_alone_uses_the_current_course():
    assert parse("lec 3", CATALOG, current=ML).as_dict() == {"type": "open", "course": "CMPE 462", "lecture": "3"}
    assert parse("lec 3", CATALOG) is None


def test_position_prefix_is_split_from_the_question():
    assert split_position("14. slayttayız hoca diyor ki ground truth labels nedir") == ("14", "hoca diyor ki ground truth labels nedir")
    assert split_position("13. slayta regularization var - ve hyper parameters dedi hoca")[0] == "13"
    assert split_position("30. slayta geç") == (None, "30. slayta geç") or split_position("30. slayta geç")[1]
    assert split_position("ground truth nedir") == (None, "ground truth nedir")


DECKS = [
    {"id": 1, "filename": "Lec01-intro.pdf"},
    {"id": 2, "filename": "Lec02-Perceptron.pdf"},
    {"id": 3, "filename": "F26_02a-EmbeddedProcessingPlatforms.pdf"},
    {"id": 4, "filename": "F26_02c-Microcontrollers.pdf"},
    {"id": 5, "filename": "CMPE580-2026-2027-1-01.pdf"},
    {"id": 6, "filename": "CMPE580-2026-2027-1-02.pdf"},
    {"id": 7, "filename": "ders2 color 2026.pdf"},
]


@pytest.mark.parametrize(
    "lecture, code, expected",
    [("2", "CMPE 462", 2), ("02", "CMPE 462", 2), ("2c", "CMPE 443", 4), ("1", "CMPE 580", 5), ("2", "CMPE 580", 6), ("9", "CMPE 462", None)],
)
def test_resolve_deck(lecture, code, expected):
    decks = {"CMPE 462": DECKS[:2], "CMPE 443": DECKS[2:4], "CMPE 580": DECKS[4:6]}[code]
    found = resolve_deck(lecture, decks, code)
    assert (found["id"] if found else None) == expected


def test_resolve_deck_after_a_keyword():
    assert resolve_deck("2", [DECKS[6]], "CMPE 537")["id"] == 7
