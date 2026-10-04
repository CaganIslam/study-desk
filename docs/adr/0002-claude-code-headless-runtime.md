# 2. Claude Code headless as the LLM runtime

- Status: accepted

## Context
The app needs an LLM for slide explanations, answers, command fallback, transcript alignment and board photo reading. The target users already pay for a Claude plan and have Claude Code installed. They should not need a separate API key.

Measured on 2026-10-03: one slide explanation with `claude -p --safe-mode` and a JSON schema took 12.7 s (3 turns: read the image, answer). That is too slow to wait for on every "next".

`--bare` would start faster, but it does not use the subscription login. It needs an API key.

Resuming one conversation per lecture (`--resume`) re-sends the growing history and every image on each call. By slide 40 that is slow and expensive. It also makes it impossible to prepare the next slide in the background without breaking the conversation order, and it leaves hundreds of sessions in `~/.claude/projects`.

## Decision
- Every call is a separate, stateless process: `claude -p --safe-mode --no-session-persistence --output-format json --json-schema <schema>`.
- `--safe-mode` skips the user's CLAUDE.md, skills, hooks, MCP servers and memory, but keeps the normal login. Calls are clean and reproducible.
- The server builds the context for each call (see ARCHITECTURE.md → AI calls).
- The next slide's explanation is prepared in the background while the user reads the current one. Explanations are cached per slide and length level.

## Update 2026-10-04
The image is now passed inside a `stream-json` message and tools are disabled (`--tools ""`), which removed the Read turn. With `--effort low`, a normal explanation takes about 10-14 s on Opus and an answer about 6 s.

## Consequences
- No API key, no extra cost beyond the user's plan. Usage counts toward the plan's limits.
- Continuity between slides has to be supplied explicitly (a short summary of the previous slide, the known-term list).
- Requires Claude Code to be installed and logged in. When it isn't, AI features show a clear message and the rest of the app keeps working.
