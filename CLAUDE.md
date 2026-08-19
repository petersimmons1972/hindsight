# CLAUDE.md — hindsight repo

Claude-specific entry point for `~/projects/hindsight`. This file exists because Claude Code
auto-loads `CLAUDE.md` but **not** `AGENTS.md` — and this repo's real agent instructions moved to
`AGENTS.md` (2026-08-19, universal-agent-policy fan-out Task 12) since none of it was actually
Claude-Code-specific. The two are complementary, not duplicates.

## Read this too

- [`AGENTS.md`](AGENTS.md) — **read this too.** Non-negotiables on the failure-mode catalog and
  guard, pipeline conventions, exit-status handling, CI. This is the real instruction set for any
  harness working in this repo, including Claude Code.
- `~/projects/AGENTS.md` — shared cross-harness conventions this repo inherits from.
