# Progress log

> The project's memory - what's been done. Newest first.
> **Append an entry after every issue / PR / milestone.** One short bullet block each.

<!-- Template for an entry:

## YYYY-MM-DD - <short title>
- Issue: #N  ·  PR: #M  ·  Milestone: <name>
- What changed: <one or two plain lines>
- Notes for next time: <anything that will save future-you time>
-->

## 2026-10-04 - Whisper benchmark on a real lecture
- Issue: #2  ·  Milestone: Milestone 0 - Verification
- What changed: phase-0 check 8 recorded. Five transcription runs on a 50-minute classroom recording; recommended settings written down; BLUEPRINT open question and the transcription integration decision closed.
- Notes for next time: `condition_on_previous_text=False` is not optional. Default settings loop on classroom audio and silently lose most of the lecture; check segment compression ratios after every transcription.

## 2026-10-04 - Repository bootstrapped
- Milestone: Milestone 0 - Verification
- What changed: repo created with the projectflow method. Living docs written from the approach plan: BLUEPRINT, ARCHITECTURE, STACK, ADRs 0002-0003, phase-0 verification notes.
- Notes for next time: checks 1-5 in `docs/research/phase-0-verification.md` passed. Checks 6-8 are the open Milestone 0 issues. The discovery pipeline was skipped on purpose (see BLUEPRINT).
