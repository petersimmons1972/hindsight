# Kill the surviving mutants — `ci-gate`

A mutation sweep found holes in this repo's own gates. Your job is to write the tests that close
them. **The report of exactly what survived, with each mutant's diff and a suggested killing test,
is committed at `briefs/survivors/ci-gate-survivors.md`. Read it first.**

Read `CLAUDE.md` for the repo's non-negotiables before starting.

## Why this matters

This repository exists to stop failure modes recurring, and its own gates were substantially
theatre: 91 mutants across the merged gates, **56 survived**. A first hardening round cut that to
39. You are closing what is left. A gate that cannot go red is not a gate.

## The discipline — this IS the job

For **every** test you write, prove it kills its mutant:

1. Run the new test against unmutated code → it must **PASS**.
2. Apply the mutant diff from the report.
3. Re-run → the new test must **FAIL**.
4. Restore the code.

Report the before/after for each. **A test that passes in both states kills nothing and is worse
than no test, because it reads as coverage.** If you cannot make a test kill its mutant, say so
plainly rather than shipping it.

Some survivors may be genuinely **equivalent** (no observable behaviour change). Say so and skip
them — an honest "equivalent, not worth a test" is a correct answer. Do **not** invent a contrived
assertion to claim a kill.

## Hard constraints

- **Your deliverable is TESTS.** Do not change production code unless a survivor genuinely requires
  a behaviour change; if so keep it minimal and call it out separately in your summary.
- **Never modify `pipeline/L1/` or `catalog/`** — source data, protected at dispatch time.
- Read exit status **directly, never through a pipe** (`cmd | head` reports *head's* status —
  catalogued here as CI-17, and it has already produced one false reading in this campaign).
- Standard library only; `pip install --user` fails on the runner (PEP 668).
- Run the **full** existing suite at the end and confirm it is still green. You must not break what
  already passes.

## Budget

**Cap: 80 tool calls.** If you hit it, stop and state exactly which survivors remain uncovered. A
partial result reported as complete is worse than a reported cutoff.

## Deliverable

First line of your summary, literally:

`KILLED: <n> of <m> targeted survivors`

Then a table: survivor id | new test name | proven-kill (yes/no) | note. Then any survivor you
judged equivalent, with reasoning. Then the final full-suite result.
