"""Run Claude Code headless, one stateless process per call.

`claude -p --safe-mode --no-session-persistence --tools "" --input-format stream-json
--output-format stream-json --json-schema ...`: no user customisations, no tools, no
saved session. The slide image goes inside the message, so Claude needs no file access.
"""

from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ClaudeCall:
    system: str
    text: str
    schema: dict
    images: tuple[Path, ...] = ()
    model: str | None = None
    effort: str | None = None
    timeout: float = 120.0


@dataclass(frozen=True)
class ClaudeResult:
    data: dict
    duration_ms: int | None = None
    cost_usd: float | None = None


class ClaudeError(Exception):
    """`code` is one of: not_installed, not_logged_in, limit, timeout, bad_output, failed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Runner(Protocol):
    def run(self, call: ClaudeCall) -> ClaudeResult: ...


_LOGIN_HINTS = ("/login", "not logged in", "invalid api key", "authentication", "oauth")
_LIMIT_HINTS = ("usage limit", "rate limit", "limit reached", "quota", "hit your limit")


def _classify(message: str) -> str:
    lowered = message.lower()
    if any(hint in lowered for hint in _LOGIN_HINTS):
        return "not_logged_in"
    if any(hint in lowered for hint in _LIMIT_HINTS):
        return "limit"
    return "failed"


class ClaudeCLI:
    def __init__(self, executable: str = "claude", cwd: Path | None = None) -> None:
        self.executable = executable
        self.cwd = cwd

    def command(self, call: ClaudeCall) -> list[str]:
        cmd = [
            self.executable,
            "-p",
            "--safe-mode",
            "--no-session-persistence",
            "--tools",
            "",
            "--system-prompt",
            call.system,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(call.schema),
        ]
        if call.model:
            cmd += ["--model", call.model]
        if call.effort:
            cmd += ["--effort", call.effort]
        return cmd

    @staticmethod
    def message(call: ClaudeCall) -> str:
        content: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(p.read_bytes()).decode()},
            }
            for p in call.images
        ]
        content.append({"type": "text", "text": call.text})
        return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"

    def run(self, call: ClaudeCall) -> ClaudeResult:
        try:
            proc = subprocess.run(
                self.command(call),
                input=self.message(call),
                capture_output=True,
                text=True,
                timeout=call.timeout,
                cwd=self.cwd,
            )
        except FileNotFoundError:
            raise ClaudeError("not_installed", "Claude Code (claude) is not installed or not on PATH") from None
        except subprocess.TimeoutExpired:
            raise ClaudeError("timeout", f"Claude did not answer within {call.timeout:.0f} s") from None

        result = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                result = event
        if result is None:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            raise ClaudeError(_classify(tail[0]), f"Claude failed: {tail[0][:300]}")
        if result.get("is_error"):
            text = str(result.get("result") or result.get("subtype") or "error")
            raise ClaudeError(_classify(text), text[:300])
        data = result.get("structured_output")
        if not isinstance(data, dict):
            raise ClaudeError("bad_output", "Claude returned no structured output")
        return ClaudeResult(data=data, duration_ms=result.get("duration_ms"), cost_usd=result.get("total_cost_usd"))


@dataclass
class FakeRunner:
    """For tests: returns scripted results in order and records every call."""

    results: list = field(default_factory=list)
    calls: list[ClaudeCall] = field(default_factory=list)

    def run(self, call: ClaudeCall) -> ClaudeResult:
        self.calls.append(call)
        item = self.results.pop(0) if self.results else {}
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(call)
        return ClaudeResult(data=item)
