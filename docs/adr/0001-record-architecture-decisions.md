# 1. Record architecture decisions

- Status: accepted

## Context
We want the reasoning behind structural choices to be durable and reviewable, so
newcomers (and future us) don't re-litigate settled calls.

## Decision
We keep lightweight Architectural Decision Records in `docs/adr/`, one Markdown file
per decision (`NNNN-title.md`), using the template in this folder. Structural changes
land with an ADR (label `documentation`) and a one-line update to `ARCHITECTURE.md`.

## Consequences
- The "why" lives next to the code and is versioned with it.
- Small overhead per decision; worth it for anything structural.
