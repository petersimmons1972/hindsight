# LEDGER — what "done" means, as commands

**This file is executed, not read.** Every row is a command and its observed result. A row with no
runnable command is a CLAIM and must say so.

Audited **2026-08-02** by a cross-vendor lane (gpt-5.6-terra), with every load-bearing result
re-derived by the coordinator rather than taken on report. States:

- **SATISFIED** — a command proves it today
- **CLAIM** — asserted, no runnable check
- **VOID** — superseded by measurement; the capability was cancelled, so no implementation can pass
- **SILENTLY BROKEN** — a command exists, appears to pass, and does not test what the row says

| # | assertion | state | evidence |
|---|---|---|---|
| V1 | CI actually executes | SATISFIED | `gh run list --repo petersimmons1972/hindsight --branch main --limit 1 --json status,conclusion` → `completed/success` |
| V2 | No check is trusted while blank | SATISFIED | `bash bin/require-real-ci.sh 1 --json-file bin/tests/fixtures/t3a_completed_empty_conclusion_defensive.json` → `FAIL … empty/missing conclusion`, exit 2; positive fixture → `PASS`, exit 0 |
| V2b | R7 is a mechanism, not a sentence | **PARTIAL** | `bin/land.sh` does propagate the gate — but **CI never invokes it**. `rg -n 'require-real-ci\|land\.sh' .github/` → the workflow runs only their *test suites*. A direct merge obtains green workflow status without V2 ever running |
| V3 | New tests discriminate | **CLAIM** | `PLAN-TDD.md:621` names `bin/verify-discriminating.sh`; **the file does not exist**. `plans/07` rebuilds it |
| V4 | Catalog is sound | SATISFIED | `python3 guard/failure_mode_catalog_guard.py` → `OK (171 canonical IDs, next FM-172)` |
| **V5** | Corpus coverage holds | **SILENTLY BROKEN** | **The sixth layer.** Row requires `COMPLETE`; `reconcile_l1.py` returns **0 for `PARTIAL` too** (`pipeline/reconcile_l1.py:176`). Reproduced by the coordinator in a fresh-checkout simulation: `PARTIAL: 0 enumerable entries unaccounted for (1/5 sources resolved)`, **EXIT=0**. `plans/08` closes it |
| V6 | Recurrence is measured, not asserted | SATISFIED | `pytest pipeline/tests/test_recurrence_report.py -q` → passes within the 181; the committed report emits the 13-times/4-repos sentence from real data |
| V7 | ~~The decisive test~~ | **VOID** | The capability was cancelled by measurement (`PLAN-TDD.md:625`). Both flags deleted; no implementation can satisfy it, so leaving it would assert a test that can never pass |
| V7b | The lookup surfaces prior art and claims nothing more | SATISFIED | `bash bin/tests/test_similar_causes.sh` → 37/37 |
| V8 | No phantom mechanisms | **SILENTLY BROKEN — admitted** | Advisory *and silent*, per a half-applied ruling. Worse than recorded: on the CI path the phantom ledger is never loaded and the summary prints `phantoms: 0` where 0 means *not measured*. `plans/01` closes it |
| **V9** | Sync is safe | **SILENTLY BROKEN** | `bin/sync-failure-modes.sh` is **on main**, takes **no arguments**, and `cp`s unconditionally into every configured project path (`:41`), then `exit 0` regardless of skips. `grep -cE 'dry-run\|--apply\|undo'` → **0**. Contradicts R6 and R9 outright. `plans/04` must cover this file, not only PR #2 |
| V10 | Provenance | **CLAIM** | No L3 artifact and no runnable provenance check exists yet. `plans/06` makes it executable (`validate_l3.py`) |
| V11 | Every gate is mutation-tested, not merely green | **CLAIM** | The row records historical sweeps (91 mutants → 56 survived → 39 survived) but names **no current command**, and **CI runs no mutation step**. A past sweep is not a standing property |
| V12 | A gate must not certify what it never compared | SATISFIED | `python3 pipeline/reconcile_l1.py` → `COMPLETE … (5/5 sources resolved)` locally, and it correctly *reports* `PARTIAL (1/5)` on a fresh tree. Path derivation from `__file__` (`:28-38`). **Note the split from V5: V12 is about honest reporting and holds; V5 is about the exit code and does not.** |

## What the audit changes

**Three rows were not what the plan said**, and only one of them was admitted:

1. **V5 is the sixth manufactured-green layer** — and it needs **zero file changes**, because it is
   the state of `main` today. Unlike V8's explicit `SKIPPED`, it presents as an ordinary successful
   step. The ladder is now: data → config → control flow → environment → scope → **exit code**.
2. **V9 describes a safety property the shipped tool does not have**, three days after an identical
   shape wrote into 11 live repos.
3. **V2b, V3, V10, V11 are claims, not checks.** V11 is the sharpest: the row asserting that every
   gate is mutation-tested is itself unbacked by any command, and no CI step runs a mutant.

**The generalisable lesson, and it is this repo's own family turned on its ledger:** an honest
*message* and an honest *exit code* are different properties. `reconcile_l1.py` says `PARTIAL` and
says which sources it skipped — it is scrupulously honest in prose — and then returns 0. V12 passes
and V5 fails on the same command. **A gate is its exit code; everything else is documentation.**
