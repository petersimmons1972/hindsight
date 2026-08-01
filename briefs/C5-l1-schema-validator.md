# C5 — L1 schema validator

## Context

The L1 corpus was produced by 14 separate extraction agents plus two mechanical parsers.
It is currently validated only for coverage (`pipeline/reconcile_l1.py` checks that no
enumerable entry is missing) — nothing validates that each record is well-formed. A
malformed record will not be noticed until a downstream stage crashes or, worse,
silently skips it.

## Files
- **Create** `pipeline/validate_l1.py`, `pipeline/tests/test_validate_l1.py`.

## Behaviour
Validate every line of `pipeline/L1/*.jsonl`:
- Parses as JSON; required keys present: `id`, `source_path`, `instance`, `auto`.
- `auto` is exactly `machine` or `judgment`.
- `enforcement` is null, or an object with `file` and `kind`, `kind` in
  {test,hook,ci,lint,schema}.
- `first_seen` is null or `YYYY-MM-DD` that is a real date.
- `id` is unique across the whole corpus; report every collision with both source files.
- `instance` is non-empty and not a placeholder (reject "TODO", "N/A", "unknown", "").

Report per-file and total counts. Exit non-zero on any violation. Every violation must
name file, line number, and the specific rule — a validator that says "invalid" without
saying where is a validator people route around.

## Acceptance (TDD)
Gate: `python3 pipeline/validate_l1.py && python3 -m pytest pipeline/tests/test_validate_l1.py -q`
- Bad fixtures rejected: missing key, bad `auto`, malformed `enforcement`, bad date,
  duplicate id, placeholder `instance`. One test per rule.
- A valid fixture passes.
- **The real corpus passes.** If it does not, do NOT relax a rule to make it green —
  report the specific records in the PR body. Real defects in the corpus are a finding,
  not an obstacle.

## Constraints
Read-only w.r.t. L1. stdlib only. No network.

## Out of scope
Repairing bad records. Coverage checking (`reconcile_l1.py` owns that).

## Model
`--harness codex --effort medium`.
