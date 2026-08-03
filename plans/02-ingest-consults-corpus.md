# PLAN-02 — adding a failure mode must consult the corpus first
Issue: petersimmons1972/hindsight#19 · Status: COMPLETE — PR #28 merged at `01d935e`; post-merge main CI pending · Blocked-by: none · Blocks: 03, 06

## 1. CONTEXT YOU DO NOT HAVE

`hindsight` is a cross-repo failure-mode registry whose founding premise is that *writing failure
modes down did not stop them recurring* — one class was re-logged ≥7 times in 3 weeks under 7
different IDs. `bin/similar-causes.py` exists, is correct, is tested at 37/37, and is **invoked by
nothing**: verified 2026-08-02, it has no production caller, `bin/add-failure-mode.sh` contains zero
references to it, and `.githooks/pre-commit` runs only the catalog guard. So in the one repo we
fully control, adding a failure mode does not check whether the corpus already knows it. This plan
closes that, and it is the prerequisite for measuring whether any of this works (plan 03).

**This is a lookup, not a gate.** A previous attempt to build rejection semantics was cancelled by
measurement: recall@5 0.523 against a 0.70 bar, and the maximum distractor score *exceeds* the
maximum true-positive score, so no threshold separates them at any operating point. Do not
reintroduce rejection. Do not sweep thresholds.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight   (private, petersimmons1972/hindsight)
Branch from: main    Work on: feat/19-ingest-consults-corpus
Suites:      cd /home/psimmons/projects/hindsight && python3 -m pytest guard/tests/ pipeline/tests/ -q
             cd /home/psimmons/projects/hindsight && bats guard/tests/*.bats bin/tests/*.bats
             cd /home/psimmons/projects/hindsight && python3 guard/failure_mode_catalog_guard.py
CI:          .github/workflows/guard.yml on self-hosted `homelab-arc`. The only workflow.
Green baseline you must not regress: pytest 167, bats 92, guard OK (171 IDs), reconcile COMPLETE 5/5.
```

Relevant existing pieces, located by NAME: `bin/add-failure-mode.sh` (appends a row, sources the
next ID from the guard, appends to `catalog/id-ledger.txt`) · `bin/similar-causes.py` (ranks the
corpus, prints top 10 with an advisory header, exit 0 on a match, fails loud on empty/unreadable
corpus) · `pipeline/extract_mechanical.py` · `pipeline/reconcile_l1.py`.

**A catalog row is currently a two-step operation** and the second step is easy to forget: the row
must also be extracted into L1 or `reconcile_l1.py` correctly reports SHORT. That cost a red main on
2026-08-02.

## 3. GOAL

Two changes, both mechanising a rule that is currently prose.

1. **Ingest consults prior art.** `bin/add-failure-mode.sh` runs `bin/similar-causes.py` against the
   proposed text and refuses to write until a `recurrence_of:` decision is recorded on the row —
   either a cluster id (`c-NNN`) or the literal `none`. The output is an advisory ranked list. It
   **never** blocks on similarity itself and emits no rejection verb.
2. **One command performs the whole loop.** catalog → extract → regenerate L2 → reconcile, so a
   human doing half of it cannot leave `reconcile_l1.py` SHORT.

## 4. DEFINITION OF DONE

- **D1** `bin/add-failure-mode.sh` with no `--recurrence-of` prints the top-10 ranked list and exits
  non-zero **without writing anything** — verified by the catalog being byte-identical afterwards.
- **D2** With `--recurrence-of c-001` or `--recurrence-of none` it writes the row, and the row
  carries the field. Any other value ⇒ exit non-zero naming the accepted forms (R6: an unrecognised
  argument aborts, never falls back).
- **D3** The tool's output contains **no rejection verb** anywhere — not "duplicate", "rejected",
  "blocked", "refused-as-similar". The header states it does not determine duplication.
- **D4** Empty, missing or unreadable corpus ⇒ **exit non-zero and say so** (R4). Zero candidates
  from a *populated* corpus is a legitimate exit 0 with an empty list. **These two zeros must be
  distinguishable in the output.**
- **D5** One command runs catalog → extract → L2 → reconcile and leaves `reconcile_l1.py` COMPLETE.
  Prove it: add a row, then run `reconcile_l1.py` immediately with no manual step between.
- **D6** `bats bin/tests/test_add_failure_mode.bats` exists and pins, on a temp catalog via the
  existing `CATALOG=` override: the guard accepts the new row · the ID came from the guard, not a
  literal · `catalog/id-ledger.txt` grew by **exactly one** line. This also closes the FM-123
  regression where a relocation silently broke this script.
- **D7** Every new test proven failing first (§8).

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.** A test that passes on the unfixed tree is not evidence — it is CI-18.
- **R2 Both directions, always.** Fires on the bad case; stays silent on the good one.
- **R3 Ground-truth fixtures are coordinator-authored**, committed before the packet is dispatched.
  You may add tests; you may not author the acceptance fixture.
- **R4 Empty / zero / missing input must FAIL LOUD**, never pass silently. **The two zeros must be
  distinguishable**: "measured, found none" and "never measured" may not render the same.
- **R5 No exit status through a pipe.** `${PIPESTATUS[0]}` or no pipe.
- **R6 Every tool that writes emits an undo journal before writing**, and exposes `--undo`. No
  implicit default target; an unrecognised argument aborts rather than falling back.
- **FM-155** A count must measure units of work actually PERFORMED, never units merely PRESENT.

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6.*

- **NEVER delete a catalog row, an L1 record, or an `id-ledger.txt` line to satisfy a validator.**
- **NEVER regenerate `catalog/id-ledger.txt`.** Restore it from git instead.
- **NEVER hand-assign a failure-mode ID.**
- **An `enforcement` value of `null` is a CORRECT answer.**
- **NEVER relax, weaken, delete or skip an existing test to make a change pass.**
- **NEVER edit any file under `conf/` or `pipeline/L1/` to make a check pass.**
- **NEVER read a command's exit status through a pipe** (CI-17).
- **NEVER modify a file not listed in §7.** STOP and report instead.
- **Do not merge, push to `main`, or open a PR.** Push the branch only.
- **Do not reintroduce rejection semantics or a `--force-new-cause` override.** An override exists
  only because a gate exists, and measurement cancelled the gate.

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/bin/add-failure-mode.sh
/home/psimmons/projects/hindsight/bin/tests/test_add_failure_mode.bats
/home/psimmons/projects/hindsight/.githooks/pre-commit
/home/psimmons/projects/hindsight/docs/INGEST.md
```
Four files. **You may not modify `bin/similar-causes.py`** — it is verified at 37/37 and this plan
is about calling it, not changing it.

## 8. RED-FIRST PROCEDURE

```bash
cd /home/psimmons/projects/hindsight
# B1 — today: ingest consults nothing
rg -c 'similar|cluster|recurrence' bin/add-failure-mode.sh || echo "B1: zero references (expected)"
# B2 — today: the hook runs only the catalog guard
cat .githooks/pre-commit
# B3 — capture the catalog digest so D1's "wrote nothing" is provable
sha256sum catalog/failure-modes.md catalog/id-ledger.txt | tee /tmp/b3.txt
```
Then write the tests and run them **before** implementing: every new test must FAIL. Paste that run.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | `bash bin/add-failure-mode.sh -c A "a terminal SUCCESS was treated as proof the work finished" >/tmp/a1.txt 2>&1; echo "exit=$?"` | non-zero; top-10 list printed; prompts for `--recurrence-of` |
| A2 | `sha256sum -c /tmp/b3.txt` | both OK — **nothing was written** |
| A3 | `grep -icE 'duplicate\|rejected\|blocked\|refused' /tmp/a1.txt` | `0` (D3) |
| A4 | `bash bin/add-failure-mode.sh -c A "<title>" --recurrence-of bogus; echo "exit=$?"` | non-zero, names the accepted forms |
| A5 | `bash bin/add-failure-mode.sh -c A "<title>" --recurrence-of none; echo "exit=$?"` | `0`; row carries `recurrence_of: none` |
| A6 | `python3 pipeline/reconcile_l1.py; echo "exit=$?"` *(immediately after A5, no manual step)* | `COMPLETE`, `exit=0` (D5) |
| A7 | `CORPUS=/tmp/empty.jsonl bash bin/add-failure-mode.sh -c A "x" --recurrence-of none; echo "exit=$?"` | non-zero, names the empty corpus (D4) |
| A8 | `bats bin/tests/test_add_failure_mode.bats` | all ok; `id-ledger.txt` grew by exactly 1 |
| A9 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥167 passed |
| A10 | `bats guard/tests/*.bats bin/tests/*.bats` | ≥92 ok |
| A11 | `python3 guard/failure_mode_catalog_guard.py; echo "exit=$?"` | `OK`, `exit=0` |
| A12 | `git diff --numstat origin/main...HEAD -- pipeline/L1 conf .github` | **empty output** (FM-154) |

## 10. MUTATION REQUIREMENT

Apply, show RED, restore, show GREEN. Report every result.

- **M1** `--recurrence-of` becomes optional (defaults to `none` silently) → D1's test must die.
- **M2** empty corpus returns an empty list and exit 0 instead of failing loud → D4's test must die.
- **M3** the extract step is dropped from the one-command loop → D5's test must die (reconcile SHORT).
- **M4** an unrecognised `--recurrence-of` value falls back to `none` instead of aborting → D2 dies.

If a mutant survives, **say so explicitly**.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight
git checkout -- bin/add-failure-mode.sh bin/tests/test_add_failure_mode.bats .githooks/pre-commit
rm -f docs/INGEST.md
git checkout main && git branch -D feat/19-ingest-consults-corpus
```
If any acceptance run wrote a real catalog row, remove it with `git checkout -- catalog/` — **never**
by hand-editing `catalog/id-ledger.txt`.

## 12. ESCALATE INSTEAD OF GUESSING

- The work appears to require editing `bin/similar-causes.py` or any file outside §7.
- You cannot make a new test fail before implementing.
- Satisfying D1 appears to require a threshold, a similarity cutoff, or a rejection path.
- `reconcile_l1.py` goes SHORT and the cause is not the missing extract step.
- Any §9 command cannot be run exactly as written.

## 13. REPORT FORMAT

First line, **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`. Then the §8 baselines,
the failing-tests-first run, the §9 table with actual beside expected, §10 results, `git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch feat/19-ingest-consults-corpus off main.
Read /home/psimmons/projects/hindsight/plans/02-ingest-consults-corpus.md in full and execute it
exactly as written. It is self-contained; do not look for additional context and do not ask for it.
Hard constraints: modify ONLY the four files in its section 7 -- in particular do NOT modify
bin/similar-causes.py; obey section 6 PROHIBITIONS literally; complete section 8 and paste the
baseline BEFORE writing any implementation; run every command in section 9 verbatim and report
actual vs expected; run every mutant in section 10. This builds a LOOKUP, not a gate: no thresholds,
no rejection semantics, no override flag. Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
