"""Build the Claude calls for explaining a slide and answering a question about it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from studydesk.ai.runner import ClaudeCall

HERE = Path(__file__).parent
LANGUAGES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish"}

LEVELS = {
    "short": "Length: short. Two or three sentences with only the main idea.",
    "normal": "Length: normal. The main idea plus one concrete example, about 80-150 words.",
    "detailed": (
        "Length: detailed. Step by step, two examples, every symbol of each formula explained, "
        "connections to earlier slides, and the most common confusion. About 250-400 words."
    ),
}

VARIANTS = {
    "simpler": (
        "The student did not follow. Explain the slide again from zero for someone with no background: "
        "no jargon beyond the slide's own terms, one everyday analogy, short sentences."
    ),
    "example": "Give one new, fully worked concrete example of the slide's main idea, different from any example on the slide.",
    "different": "The earlier explanation (below) did not land. Explain the same idea from a different angle with a different example.",
    "formula": "Walk through the formula(s) on this slide: what each symbol is, why the formula has this shape, then a tiny numeric example.",
}

# Claude Code effort per length; lower effort answers several times faster (measured 2026-10-04).
EFFORT = {"short": "low", "normal": "low", "detailed": "medium"}


@cache
def _prompt(name: str) -> str:
    return (HERE / "prompts" / f"{name}.md").read_text(encoding="utf-8")


@cache
def _schema(name: str) -> dict:
    return json.loads((HERE / "schemas" / f"{name}.json").read_text(encoding="utf-8"))


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


@dataclass(frozen=True)
class SlideContext:
    course_code: str
    course_name: str
    deck: str
    label: str
    idx: int
    total: int
    title: str
    text: str
    image: Path | None = None
    week_topic: str | None = None
    previous_summary: str | None = None
    lecturer_notes: str | None = None
    known_terms: tuple[str, ...] = ()
    previous_explanation: str | None = None


def _context_block(ctx: SlideContext) -> list[str]:
    lines = [
        f"Course: {ctx.course_code} {ctx.course_name}",
        f"Deck: {ctx.deck}, slide {ctx.label} ({ctx.idx} of {ctx.total})" + (" - the last slide" if ctx.idx == ctx.total else ""),
    ]
    if ctx.week_topic:
        lines.append(f"This week's syllabus topic: {ctx.week_topic}")
    if ctx.previous_summary:
        lines.append(f"Previous slide: {ctx.previous_summary}")
    if ctx.lecturer_notes:
        lines.append(f"What the lecturer said on this slide (transcript excerpt):\n{ctx.lecturer_notes}")
    lines.append(f"Slide title: {ctx.title}")
    lines.append(f"Slide text (extracted):\n{ctx.text.strip() or '(no text)'}")
    if ctx.known_terms:
        lines.append(
            "The student already knows these; do not explain them again, mention them in a few words at most: "
            + ", ".join(ctx.known_terms)
        )
    return lines


def explain_call(
    ctx: SlideContext,
    level: str = "normal",
    variant: str | None = None,
    language: str = "tr",
    model: str | None = None,
    effort: str | None = None,
) -> ClaudeCall:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}")
    if variant is not None and variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    lines = _context_block(ctx)
    lines.append(LEVELS[level])
    if variant:
        lines.append(VARIANTS[variant])
        if variant == "different" and ctx.previous_explanation:
            lines.append(f"Earlier explanation:\n{ctx.previous_explanation}")
    return ClaudeCall(
        system=_prompt("tutor_system").replace("{language}", language_name(language)),
        text="\n\n".join(lines),
        schema=_schema("explanation"),
        images=(ctx.image,) if ctx.image else (),
        model=model,
        effort=effort or EFFORT[level],
    )


@dataclass(frozen=True)
class Exchange:
    question: str
    answer: str


def answer_call(
    ctx: SlideContext,
    question: str,
    thread: tuple[Exchange, ...] = (),
    level: str = "normal",
    language: str = "tr",
    model: str | None = None,
    effort: str | None = None,
) -> ClaudeCall:
    lines = _context_block(ctx)
    for exchange in thread[-5:]:
        lines.append(f"Earlier question: {exchange.question}\nEarlier answer: {exchange.answer}")
    lines.append(LEVELS[level].replace("Length", "Answer length"))
    lines.append(f"Question: {question.strip()}")
    return ClaudeCall(
        system=_prompt("answer_system").replace("{language}", language_name(language)),
        text="\n\n".join(lines),
        schema=_schema("answer"),
        images=(ctx.image,) if ctx.image else (),
        model=model,
        effort=effort or "low",
    )


def bar_call(
    ctx: SlideContext | None,
    message: str,
    courses: tuple[tuple[str, str, tuple[str, ...]], ...],
    thread: tuple[Exchange, ...] = (),
    level: str = "normal",
    language: str = "tr",
    model: str | None = None,
    course_line: str | None = None,
) -> ClaudeCall:
    """One call that either answers the message or turns it into an app action."""
    lines = _context_block(ctx) if ctx else [course_line or "No slide is open."]
    if courses:
        lines.append(
            "Courses (code: name; aliases):\n"
            + "\n".join(f"- {code}: {name}; {', '.join(aliases)}" for code, name, aliases in courses)
        )
    for exchange in thread[-5:]:
        lines.append(f"Earlier question: {exchange.question}\nEarlier answer: {exchange.answer}")
    lines.append(LEVELS[level].replace("Length", "Answer length"))
    lines.append(f"Message: {message.strip()}")
    return ClaudeCall(
        system=_prompt("bar_system").replace("{language}", language_name(language)),
        text="\n\n".join(lines),
        schema=_schema("bar"),
        images=(ctx.image,) if ctx and ctx.image else (),
        model=model,
        effort="low",
    )
