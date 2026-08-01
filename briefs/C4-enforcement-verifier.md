# C4 — Enforcement verifier

## Context

Entries claim enforcement mechanisms. Some of those mechanisms do not exist — they were
proposed, or aspirational, or the file was later moved or deleted. A phantom mechanism is
worse than an admitted gap: it reads as covered, so nobody ever covers it. The survey
found only ~21% of global lessons name a real mechanism at all, and did not verify that
the named ones still resolve.

## Files
- **Modify** `guard/failure_mode_catalog_guard.py` — add `--verify-enforcement`.
- **Create** `guard/tests/test_verify_enforcement.py`.

## Behaviour
Scan `pipeline/L1/*.jsonl`. For every entry with `auto == "machine"` and a non-null
`enforcement`, resolve `enforcement.file` relative to `~/projects/`. Report:
- **phantom** — `auto: machine` with an `enforcement` path that does not exist. FATAL.
- **unbacked** — `auto: machine` with `enforcement: null`. Report as a WARNING with a
  count, not an error: it is an honest, expected state for most entries and the correct
  response is Phase 5 work, not a failing build.
- **summary** — totals per source, and the machine/judgment split.

Exit non-zero only on phantoms. Print a scope note stating that this checks *existence*,
not that the named file actually enforces the thing it claims — a path that resolves is
necessary, not sufficient.

## Acceptance (TDD)
Gate: `python3 -m pytest guard/tests/test_verify_enforcement.py -q`
- A fixture entry naming a nonexistent path FAILS with that path in the message.
- A fixture entry naming a real path PASSES.
- `auto: machine` + `enforcement: null` produces a WARNING and exit 0, not an error.
- `auto: judgment` + `enforcement: null` is silent — the normal case, no noise.
- Run against the real corpus: must not crash, and must report a count.

## Constraints
Read-only. No network. Must not modify any L1 file.

## Out of scope
Fixing the gaps it finds (Phase 5). Judging enforcement *quality*.

## Model
`--harness codex --effort medium`.
