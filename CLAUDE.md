# study-desk - project conventions

This project follows the **projectflow** method. Read it before working,
and keep the living docs current.

## Read first (the living docs)
- `docs/BLUEPRINT.md` - the plan: what we're building and how.
- `docs/ARCHITECTURE.md` - constraints, structure, and the patterns/methods we use.
  Follow these instead of inventing new ones.
- `docs/PROGRESS.md` - what's been done. **Update it after every issue/PR.**
- `docs/STACK.md` - the tech stack + external providers + env keys + per-provider
  data-residency map; consult before adding a dependency or sending data off-box.

## How we work
0. **New project / greenfield?** Announce the **discovery pipeline** and start Phase 0
   rather than waiting to be asked. Seven phases, each behind an approval gate: framing
   (with kill criteria written before any evidence), research, red-team validation with
   a **go / cautious-go / no-go** in `BLUEPRINT.md`, charter, PRD, technical design,
   sprint planning → then issues. Phase 1 asks whether research should be short or deep;
   ask, don't infer. Skip the pipeline for well-understood or small work, and **say that
   you're skipping and why**. (SKILL.md §1.0; detail in `docs/DISCOVERY-PIPELINE.md`,
   phase prompts in `docs/prompts/`)
1. Requirements → labeled issues (one per area, linked). Don't code from a vague ask.
   Don't pre-decide issue-local implementation choices either - write them as
   `## Options` (one-line trade-off each) in the issue; only cross-cutting calls
   (shared contracts, patterns, dependencies) are settled upfront in BLUEPRINT.md
   or an ADR. (SKILL.md §3)
2. Show the backlog + priority; let the maintainer steer.
3. Per issue: **propose → approve → implement** - one at a time. Present the issue in
   **plain language** (what it is, what it's for, what it does, what it changes -
   purpose and effect first), **not a file dump**. If the issue lists `## Options`,
   the proposal picks one and says why; approval locks it in, and the pick is
   recorded on the issue. The propose→approve→implement gate
   is unchanged; the issue's `## Files` field stays as the written engineering spec.
4. Verify: the agent runs everything runnable itself (tests, lint, build, CLI smoke) and
   reports the output; "manual steps" are **only** genuine human-hands/eyes checks (UI
   clicks, judging look/sound). If nothing needs human hands, there's no manual step.
   **If nothing is runnable at all** (docs, config, content), verification is still
   required: re-read what changed, check it against the files it claims consistency
   with, and say which files you checked and what you compared.
5. Open a PR (`Closes #N`) after approval; reviewed + approved before merge.
6. At each milestone close, offer a **bug hunt**.

## Configuration (set per project)
- **areas:** `backend, frontend, ingest, ai, devops, docs` (+ `repo` scope for repository configuration)
  - `backend` - FastAPI server, SQLite, sessions, terms, review scheduling
  - `frontend` - the browser pages (plain HTML/CSS/JS, strings files)
  - `ingest` - Moodle sync, Voice Memos import, transcription, board photos, books
  - `ai` - the `claude -p` runner, prompts and JSON schemas
  - `devops` - launchd agent, install scripts, CI
  - `docs` - README, living docs, ADRs, research notes
- **test commands:** `uv run pytest` (unit + contract + flow). Added with the project skeleton in Milestone 1. Until then, changes are docs and are verified by reading them against each other.
- **traceability:** issues map to the milestones in `docs/BLUEPRINT.md`. Milestone descriptions carry `Requirements covered:`.
- **working language:** English (default) - the language repo artifacts are written in.
- **personal data:** never in the repo (ADR 0003). Use synthetic fixtures in tests.

## Conventions
- Labels: one `area:` + one `priority:` + one type (`feat`/`bug`/`enhancement`/`documentation`/`testing`).
- Branch: `<type>/<area>/<slug>-<issueNumber>` from current `main`.
- Commits / PR titles: `<type>(<area>): subject` (linted).
- PR body: short, plain, `Closes #N`.

## Guardrails
- **Propose before doing** (every turn). **No Edit, Write, or branch on an issue's
  behalf until a proposal has been made and approved in an earlier message.** That's
  the trigger. **A written issue is never a proposal** - the issue is the spec, the
  proposal is a message that presents it plainly, names the approach, and waits. A
  well-written issue makes this easy to forget.
- **No completion claim without evidence** (every turn). "Done", "fixed", "working",
  "passing" each need the supporting output **in the same message**. Trigger: before
  writing any of those words.
- **Stay inside the issue.** Only the files the issue needs. No drive-by tidying or
  reformatting. A necessary out-of-scope change is named in the proposal, not slipped
  in; a worthwhile but unnecessary one becomes its own issue.
- **Leave the build green**, throughout the work and not only at the end.
- **An agent cannot audit its own output.** Anything whose job is to catch errors in
  a previous step (review, verification, QA, bug hunt) is done by a fresh agent that
  did not produce that work. Parallel agents need a different angle or an adversarial
  stance, or their agreement means nothing. (SKILL.md §3.5)
- Approval before PRs, pushes, merges, or destructive ops.
- Destructive ops (deletes, DB resets) need a dry-run + confirmation.
- **No AI attribution in commits or PRs** - no "generated by", no `Co-Authored-By`.
- **Repo language is English by default** - code, comments, docs, commit/PR/issue text.
  The one exception is the project's declared **working language** (Configuration); repo
  artifacts are written in that. Talk to the maintainer in their own language regardless.
- Keep commit/PR descriptions explanatory but short and plain.
- **End every turn with a short action plan** - to-dos / open decisions / **next**
  (omit empty buckets, always keep *Next*), as the last thing in the message.
- **Every turn, check the deep-skill table** (below; full table in SKILL.md §0.5): find
  this turn's step, and if the mapped skill is installed **and** the step genuinely needs
  it, invoke it before doing the step; otherwise use projectflow's inline guidance.
  Optional power-up, never required. Looking is mandatory; whether it's needed is a
  judgment call.
  (install: github.com/obra/superpowers - optional; without them projectflow uses its
  inline guidance.)

  | Step | Deep skill(s) if installed |
  | --- | --- |
  | discovery pipeline (new project) | `brainstorming` · `dispatching-parallel-agents` · `deep-research` · `writing-plans` |
  | requirements → issues | `brainstorming` |
  | propose the approach / plan | `writing-plans` |
  | implement | `test-driven-development` · `using-git-worktrees` |
  | independent parallel work | `dispatching-parallel-agents` |
  | a test breaks / a failure | `systematic-debugging` |
  | before claiming "done" | `verification-before-completion` |
  | before a PR / on review feedback | `requesting-code-review` · `receiving-code-review` |
  | merge / close the branch | `finishing-a-development-branch` |
