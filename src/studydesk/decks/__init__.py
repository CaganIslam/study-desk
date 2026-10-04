"""PDF decks: text per page, logical slides, and cached PNG renders.

Lecturers' PDFs often split one slide into several pages (animation builds).
Pages are grouped back into logical slides, so "slide 14" means what the
lecturer calls slide 14:
1. If most pages end with a frame number in the footer, pages sharing a number
   form one slide and the number is its label.
2. Otherwise a page whose text extends the previous page's text (same title)
   is a build step of that slide.
A slide is shown and explained from its last page, which carries every build step.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from studydesk.courses import Catalog
from studydesk.db import Database

SIZES = {"view": 2000, "ai": 1280}  # long edge in pixels
_FOOTER_NUMBER = re.compile(r"(?:^|\s)(\d{1,3})\s*$")


@dataclass(frozen=True)
class LogicalSlide:
    idx: int
    label: str
    title: str
    text: str
    first_page: int
    last_page: int


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page_texts(pdf: pdfium.PdfDocument) -> list[str]:
    texts = []
    for index in range(len(pdf)):
        textpage = pdf[index].get_textpage()
        try:
            texts.append(textpage.get_text_range())
        finally:
            textpage.close()
    return texts


def _footer_numbers(texts: list[str]) -> list[int | None] | None:
    """Frame numbers from the last line of each page, if the deck is consistently numbered."""
    numbers = []
    for text in texts:
        lines = _lines(text)
        match = _FOOTER_NUMBER.search(lines[-1]) if lines else None
        numbers.append(int(match.group(1)) if match else None)
    found = [n for n in numbers if n is not None]
    if len(found) < 0.6 * len(texts) or max(found, default=0) > len(texts):
        return None
    if any(b < a for a, b in zip(found, found[1:])):
        return None
    return numbers


def group_pages(texts: list[str]) -> tuple[list[LogicalSlide], bool]:
    """Group PDF pages into logical slides. Returns the slides and whether footer numbers were used."""
    numbers = _footer_numbers(texts)
    groups: list[list[int]] = []
    for page, text in enumerate(texts):
        if not groups:
            groups.append([page])
            continue
        previous = groups[-1][-1]
        if numbers is not None:
            same = numbers[page] is not None and numbers[page] == numbers[previous]
        else:
            before, now = _normalise(texts[previous]), _normalise(text)
            same_title = _lines(texts[previous])[:1] == _lines(text)[:1]
            same = bool(before) and same_title and before in now
        if same:
            groups[-1].append(page)
        else:
            groups.append([page])

    slides = []
    for idx, pages in enumerate(groups, start=1):
        last = pages[-1]
        lines = _lines(texts[last])
        label = str(numbers[last]) if numbers is not None and numbers[last] is not None else str(idx)
        slides.append(
            LogicalSlide(
                idx=idx,
                label=label,
                title=lines[0][:200] if lines else "",
                text=texts[last].strip(),
                first_page=pages[0],
                last_page=last,
            )
        )
    return slides, numbers is not None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def scan(db: Database, catalog: Catalog, data_root: Path, course_code: str | None = None) -> None:
    """Index new or changed PDFs in the courses' slides folders. Unchanged files are skipped by mtime and size."""
    for course in catalog.courses:
        if course_code and course.code != course_code:
            continue
        folder = data_root / course.folder / "slides"
        pdfs = sorted(folder.glob("*.pdf")) if folder.is_dir() else []
        with db.connect() as conn:
            known = {row["path"]: row for row in conn.execute("SELECT * FROM decks WHERE course_code = ?", (course.code,))}
            for gone in set(known) - {str(p) for p in pdfs}:
                conn.execute("DELETE FROM decks WHERE path = ?", (gone,))
        for pdf_path in pdfs:
            stat = pdf_path.stat()
            row = known.get(str(pdf_path))
            if row and row["mtime"] == stat.st_mtime and row["size"] == stat.st_size:
                continue
            sha = _sha256(pdf_path)
            if row and row["sha256"] == sha:
                with db.connect() as conn:
                    conn.execute("UPDATE decks SET mtime = ?, size = ? WHERE id = ?", (stat.st_mtime, stat.st_size, row["id"]))
                continue
            try:
                document = pdfium.PdfDocument(str(pdf_path))
            except pdfium.PdfiumError:
                continue  # not a readable PDF; skipped until it changes
            try:
                slides, numbered = group_pages(page_texts(document))
                pages = len(document)
            finally:
                document.close()
            with db.connect() as conn:
                if row:
                    deck_id = row["id"]
                    conn.execute(
                        "UPDATE decks SET sha256 = ?, mtime = ?, size = ?, pages = ?, numbered = ?, scanned_at = datetime('now') WHERE id = ?",
                        (sha, stat.st_mtime, stat.st_size, pages, int(numbered), deck_id),
                    )
                    conn.execute("DELETE FROM slides WHERE deck_id = ?", (deck_id,))
                else:
                    deck_id = conn.execute(
                        "INSERT INTO decks (course_code, path, sha256, mtime, size, pages, numbered) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (course.code, str(pdf_path), sha, stat.st_mtime, stat.st_size, pages, int(numbered)),
                    ).lastrowid
                conn.executemany(
                    "INSERT INTO slides (deck_id, idx, label, title, text, first_page, last_page) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(deck_id, s.idx, s.label, s.title, s.text, s.first_page, s.last_page) for s in slides],
                )


def list_decks(db: Database, course_code: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT d.id, d.path, d.pages, d.numbered, COUNT(s.idx) AS slides FROM decks d"
            " LEFT JOIN slides s ON s.deck_id = d.id WHERE d.course_code = ? GROUP BY d.id",
            (course_code,),
        ).fetchall()
    decks = [
        {"id": r["id"], "filename": Path(r["path"]).name, "pages": r["pages"], "slides": r["slides"], "numbered": bool(r["numbered"])}
        for r in rows
    ]
    return sorted(decks, key=lambda d: _natural_key(d["filename"]))


def get_deck(db: Database, deck_id: int):
    with db.connect() as conn:
        return conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()


def get_slides(db: Database, deck_id: int) -> list:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM slides WHERE deck_id = ? ORDER BY idx", (deck_id,)).fetchall()


def get_slide(db: Database, deck_id: int, idx: int):
    with db.connect() as conn:
        return conn.execute("SELECT * FROM slides WHERE deck_id = ? AND idx = ?", (deck_id, idx)).fetchone()


def render(deck, slide, size: str, cache_dir: Path) -> Path:
    """PNG of the slide's last page at the given size, rendered once and cached by file hash."""
    if size not in SIZES:
        raise ValueError(f"unknown size {size!r}")
    target = cache_dir / deck["sha256"] / f"{slide['last_page']}-{size}.png"
    if target.exists():
        return target
    document = pdfium.PdfDocument(deck["path"])
    try:
        page = document[slide["last_page"]]
        width, height = page.get_size()
        scale = SIZES[size] / max(width, height)
        image = page.render(scale=scale).to_pil()
    finally:
        document.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    image.save(tmp, format="PNG", optimize=True)
    tmp.replace(target)
    return target
