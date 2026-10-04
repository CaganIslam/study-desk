"""The input bar's local parser: common commands are understood without Claude.

Text is folded (lowercase, Turkish letters to ASCII, filler words dropped) and
matched against a few patterns. Anything else goes to Claude, which either
answers it as a question or picks one of the same actions.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from studydesk.courses import Catalog, Course

ACTIONS = ("next", "prev", "goto_slide", "open", "set_level", "variant", "know_skip", "home", "resume", "today_summary", "search", "live")
RESUME = ("nerede kaldik", "nerde kaldik", "kaldigim yer", "kaldigimiz yer", "kaldigim yerden", "resume")
TODAY_SUMMARY = ("bugun ne calistim", "bugun ne calistik", "ne calistik", "ne calistim", "bugunun ozeti", "today summary")
SEARCH = re.compile(r"^(?:ara|search|bul) (.+)$|^(.+?) (?:nerede|nerde) (?:gecti|geciyor|vardi|anlatildi)$")

FILLER = {
    "reis", "abi", "hocam", "lutfen", "hadi", "bi", "bir", "bakalim", "simdi", "su", "sunu", "bunu",
    "ya", "artik", "yap", "please", "the", "to", "go", "ac", "acar", "misin", "acsana", "gec", "gecelim",
    "gecsene", "gecer", "git", "gidelim", "dersi", "dersini", "dersine", "derse", "open", "pardon", "tamam", "okey",
}  # fmt: skip

WORDS = {
    "next": {"siradaki", "sirdaki", "sonraki", "devam", "next", "ileri", "siradakine", "sonrakine"},
    "prev": {"onceki", "geri", "previous", "back", "oncekine"},
    "home": {"home", "anasayfa", "dersler", "bugun", "courses", "today"},
    "know_skip": {"biliyorum", "biliyom", "know"},
    "live": {"canli", "live"},
}
LEVEL_WORDS = {
    "short": {"kisa", "kisaca", "short"},
    "normal": {"normal"},
    "detailed": {"genis", "uzun", "detayli", "ayrintili", "detailed", "long"},
}
VARIANT_PHRASES = {
    "simpler": ("daha basit", "basit anlat", "basitce anlat", "anlamadim", "simpler"),
    "example": ("ornek ver", "ornekle anlat", "example"),
    "different": ("farkli anlat", "baska turlu", "different"),
    "formula": ("formulu ac", "formulu anlat", "formula"),
}
SLIDE_WORDS = r"(?:s(?:lay|aly|lya|ly)[td]?(?:a|ta|ttayiz|tayiz|tta|e)?|slide|sayfa|sayfaya)"
POSITION_PREFIX = re.compile(r"^\s*(?:pardon\s+)?(\d{1,3})\s*\.?\s*(?:slayt|slide)[a-zıiğüşöç]*\s*[,:-]?\s*", re.IGNORECASE)
LECTURE_WORDS = r"(?:lec|lecture|ders|week|hafta|chapter|ch|unite)"


def fold(text: str) -> str:
    text = text.replace("I", "ı").replace("İ", "i").lower().replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("ana sayfa", "anasayfa")


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


@dataclass(frozen=True)
class Command:
    type: str
    label: str | None = None
    course: str | None = None
    lecture: str | None = None
    level: str | None = None
    variant: str | None = None
    query: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, {}) or k == "type"}


def _course_keys(course: Course) -> set[str]:
    keys = {fold(a) for a in course.aliases}
    code = fold(course.code)
    keys |= {code, code.replace(" ", ""), "".join(re.findall(r"\d+", code))}
    keys.add(fold(course.name))
    return {k for k in keys if k}


def find_course(text: str, catalog: Catalog) -> Course | None:
    folded = " ".join(words(text))
    best, best_len = None, 0
    for course in catalog.courses:
        for key in _course_keys(course):
            if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", folded) and len(key) > best_len:
                best, best_len = course, len(key)
    return best


def split_position(text: str) -> tuple[str | None, str]:
    """ "14. slayttayız, hoca X diyor, ne o?" -> ("14", "hoca X diyor, ne o?"). The position comes first."""
    match = POSITION_PREFIX.match(text)
    if not match or not text[match.end():].strip():
        return None, text
    return str(int(match.group(1))), text[match.end():].strip()


def parse(text: str, catalog: Catalog, current: Course | None = None) -> Command | None:
    """A Command when the whole text is a command, else None (a question, or for Claude)."""
    folded = " ".join(words(text))
    tokens = [t for t in folded.split() if t not in FILLER]
    if not tokens:
        return None
    joined = " ".join(tokens)

    if any(p == joined or p == folded for p in RESUME):
        return Command("resume")
    if any(p == joined or p == folded for p in TODAY_SUMMARY):
        return Command("today_summary")
    found = SEARCH.match(folded)
    if found:
        return Command("search", query=(found.group(1) or found.group(2)).strip())

    for variant, phrases in VARIANT_PHRASES.items():
        if any(fold(p) in folded for p in phrases) and len(tokens) <= 4:
            return Command("variant", variant=variant)

    # "30. slayta geç", "slayt 30", "14. slayttayız", "30'a geç"
    match = re.fullmatch(rf"(\d{{1,3}}) ?(?:inci|nci|uncu|ncu|e|a|ye|ya)? ?{SLIDE_WORDS}?", joined) or re.fullmatch(
        rf"{SLIDE_WORDS} (\d{{1,3}})", joined
    )
    if match and (re.search(SLIDE_WORDS, joined) or re.search(r"\b(gec|git|gecelim)\b", folded)):
        return Command("goto_slide", label=str(int(match.group(1))))

    for kind in ("next", "prev", "home", "know_skip", "live"):
        if tokens[0] in WORDS[kind] and len(tokens) <= 3 and not any(t in WORDS["next"] for t in tokens[1:] if kind != "next"):
            if all(t in WORDS[kind] or t in {"slayt", "slide", "sayfa", "gec", "bunu", "mod", "moda", "mode"} for t in tokens):
                return Command(kind)

    for level, names in LEVEL_WORDS.items():
        rest = [t for t in tokens if t not in names and t not in {"anlat", "anlatsana", "explain", "olsun", "yaz"}]
        if any(t in names for t in tokens) and not rest:
            return Command("set_level", level=level)

    course = find_course(text, catalog)
    if course is None and current is not None and re.fullmatch(rf"{LECTURE_WORDS} ?\d{{1,2}}[a-z]?|\d{{1,2}}[a-z]? ?(?:inci|nci)? ?{LECTURE_WORDS}", joined):
        course = current
    if course is not None:
        lecture = re.search(rf"{LECTURE_WORDS} ?(\d{{1,2}}[a-z]?)\b|\b(\d{{1,2}}[a-z]?) ?(?:\.|inci|nci)? ?{LECTURE_WORDS}\b", joined)
        keys = _course_keys(course)
        leftover = [
            t for t in tokens
            if t not in keys and not any(t in k.split() for k in keys)
            and not re.fullmatch(rf"(?:{LECTURE_WORDS})?\d{{1,2}}[a-z]?|{LECTURE_WORDS}|cmpe|ie|ee", t)
        ]  # fmt: skip
        if not leftover:
            num = (lecture.group(1) or lecture.group(2)) if lecture else None
            if num is None:  # "gömülü 2c": a bare lecture number after the course
                bare = [t for t in tokens if re.fullmatch(r"\d{1,2}[a-z]?", t) and t not in keys]
                num = bare[0] if bare else None
            return Command("open", course=course.code, lecture=num)
    return None


def _deck_number(filename: str, course_code: str) -> tuple[int | None, str]:
    """The lecture number a deck file stands for, and its letter suffix (for 02a, 02b ...)."""
    stem = fold(Path(filename).stem)
    keyed = re.search(rf"{LECTURE_WORDS}[ _-]?0*(\d{{1,2}})([a-z]?)\b", stem)
    if keyed:
        return int(keyed.group(1)), keyed.group(2)
    code_numbers = set(re.findall(r"\d+", fold(course_code)))
    found = [
        (int(n), suffix)
        for n, suffix in re.findall(r"(?<![0-9])(\d{1,3})([a-z]?)(?![0-9])", stem)
        if n not in code_numbers and not (len(n) == 4)
    ]
    if not found:
        return None, ""
    # "F26_02c": a two-digit term code followed by the lecture number; take the last plain number.
    return found[-1]


def resolve_deck(lecture: str, decks: list[dict], course_code: str) -> dict | None:
    match = re.fullmatch(r"0*(\d{1,2})([a-z]?)", fold(lecture))
    if not match:
        return None
    number, suffix = int(match.group(1)), match.group(2)
    candidates = []
    for deck in decks:
        n, s = _deck_number(deck["filename"], course_code)
        if n == number and (not suffix or s == suffix):
            candidates.append(deck)
    return candidates[0] if candidates else None
