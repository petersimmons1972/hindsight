# hindsight — agent instructions

Cross-repo failure-mode registry. Read `README.md` first; it explains why this
repo exists and what the guard enforces.

## Non-negotiables

- **`catalog/failure-modes.md` is the only source of truth.** Copies in other
  repos are vendored artifacts. Never add an entry anywhere but here.
- **Never delete a catalog row to satisfy a validator.** That is precisely how 11
  real failure modes (`FM-REC-01..11`) were nearly lost. If a row violates a
  rule, renumber or fix the rule — the rule is younger than the data.
- **Never hand-assign an ID.** Use `bin/add-failure-mode.sh`, which sources the
  next ID from the guard.
- **An `enforcement` value of `null` is a correct answer.** Do not invent a test
  or hook path to fill a field. A fabricated mechanism is worse than an honest
  gap, because it reads as covered.

## Working on the guard

The guard's contract is pinned by `guard/tests/`. Two rules are deliberately
narrower or softer than they first appear (ordering is advisory; the legacy-alias
rule fires only on row IDs). **Both directions of each are tested** — if you
change a rule, update the test to assert the new contract in both directions.
Never relax a test to make a change pass.

Run before committing:

```bash
python3 guard/failure_mode_catalog_guard.py
python3 -m pytest guard/tests/ -q
bats guard/tests/test_failure_mode_catalog_guard.bats
```

## Pipeline conventions

`pipeline/` holds the L0→L3 synthesis. Two rules matter:

- **Spool to disk, never to context.** Extraction agents write JSONL and return a
  count. A tier reads the spool, never the raw corpora. Corpus is ~7,200 lines
  across 27 files; loading it into a session is the failure this design avoids.
- **A lesson is eligible for L3 (global) only with ≥2 distinct source repos.**
  One incident on one named host is repo-level. A pointer to another file is not
  a lesson at all.

## Reading exit status

Never read a command's exit status through a pipe (`cmd | head` reports *head's*
status). This is catalogued as CI-17: the habit that saves context silently
destroyed a measurement and produced a false green. Use `${PIPESTATUS[0]}` or
avoid the pipe.

## CI

Runs on `homelab-arc` (self-hosted). Private repo — see the fleet convention that
private repos use our own ARC runners.
