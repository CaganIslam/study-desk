"""Transcription with the user's installed mlx_whisper, and a quality check of the result.

Settings come from the phase-0 benchmark (docs/research/phase-0-verification.md):
turbo model, `--condition-on-previous-text False` (without it classroom audio falls into
a repetition loop and most of the lecture is lost), no initial prompt, no word timestamps.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large": "mlx-community/whisper-large-v3-mlx",
}


class TranscriptionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Segment:
    start: float
    end: float
    text: str
    compression_ratio: float = 0.0


@dataclass
class Transcript:
    segments: list[Segment]
    model: str
    seconds: float


@dataclass
class Quality:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _model_cached(repo: str) -> bool:
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return (cache / f"models--{repo.replace('/', '--')}").is_dir()


def transcribe(audio: Path, language: str = "en", model: str = "turbo", executable: str | None = None) -> Transcript:
    exe = executable or shutil.which("mlx_whisper")
    if not exe:
        raise TranscriptionError("whisper_missing", "mlx_whisper is not installed (uv tool install mlx-whisper)")
    repo = MODELS.get(model, model)
    env = dict(os.environ)
    if _model_cached(repo):
        env["HF_HUB_OFFLINE"] = "1"  # the model is already here: no network call
    with tempfile.TemporaryDirectory() as out:
        started = time.monotonic()
        proc = subprocess.run(
            [
                exe, str(audio), "--model", repo, "--language", language,
                "--condition-on-previous-text", "False", "--output-format", "json",
                "--output-dir", out, "--output-name", "transcript", "--verbose", "False",
            ],
            capture_output=True, text=True, env=env,
        )  # fmt: skip
        result = Path(out) / "transcript.json"
        if proc.returncode != 0 or not result.exists():
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            raise TranscriptionError("whisper_failed", tail[0][:300])
        data = json.loads(result.read_text(encoding="utf-8"))
    segments = [
        Segment(float(s["start"]), float(s["end"]), str(s["text"]).strip(), float(s.get("compression_ratio") or 0))
        for s in data.get("segments", [])
    ]
    return Transcript(segments=segments, model=repo, seconds=time.monotonic() - started)


def check(transcript: Transcript, duration_s: float) -> Quality:
    """Catch the failure modes seen in the benchmark: repetition loops and lost minutes."""
    segments = [s for s in transcript.segments if s.text]
    n = len(segments)
    words = sum(len(s.text.split()) for s in segments)
    covered = sum(max(0.0, s.end - s.start) for s in segments)
    repeated = sum(1 for a, b in zip(segments, segments[1:]) if a.text == b.text)
    compressed = sum(1 for s in segments if s.compression_ratio > 2.4)
    minutes = max(duration_s / 60, 1e-9)
    stats = {
        "segments": n,
        "words": words,
        "words_per_minute": round(words / minutes, 1),
        "covered_ratio": round(covered / duration_s, 2) if duration_s else 0,
        "repeated_segments": repeated,
        "high_compression_segments": compressed,
    }
    reasons = []
    if duration_s > 60 and n == 0:
        reasons.append("empty")
    if n and (repeated / n > 0.2 or compressed / n > 0.2):
        reasons.append("repetition_loop")
    if duration_s > 120 and covered / duration_s < 0.6:
        reasons.append("missing_minutes")
    if words / minutes > 260:
        reasons.append("too_many_words")
    return Quality(ok=not reasons, reasons=reasons, stats=stats)


def markdown(transcript: Transcript, title: str, every: float = 60.0) -> str:
    """Paragraphs of about a minute, each starting with its [mm:ss] position."""
    lines = [f"# {title}", ""]
    paragraph, start = [], None
    for segment in transcript.segments:
        if not segment.text:
            continue
        if start is None:
            start = segment.start
        paragraph.append(segment.text)
        if segment.end - start >= every:
            lines += [f"[{int(start // 60):02d}:{int(start % 60):02d}] " + " ".join(paragraph), ""]
            paragraph, start = [], None
    if paragraph:
        lines += [f"[{int(start // 60):02d}:{int(start % 60):02d}] " + " ".join(paragraph), ""]
    return "\n".join(lines)
