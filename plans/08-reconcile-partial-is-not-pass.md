# PLAN-08 — PARTIAL must not exit 0
Issue: petersimmons1972/hindsight#25 (V5 / sixth layer) · Status: COMPLETE — PR #26 merged at `902945d`; post-merge main guard green · Blocked-by: none · Blocks: X2

## 1. CONTEXT YOU DO NOT HAVE

`hindsight` is a cross-repo failure-mode registry. `pipeline/reconcile_l1.py` compares its L1 corpus
against ground truth in **5 sources**; four of them are sibling repos that live *outside* this
checkout (`P = REPO.parent`). Its verification-ledger row V5 reads: *"Corpus coverage holds →
`COMPLETE`, exit 0."*

**On a CI runner only this repo is checked out, so four sources are absent, the verdict is `PARTIAL`
— and `PARTIAL` returns 0.** Measured 2026-08-02 in a fresh-checkout simulation:

```
PARTIAL: 0 enumerable entries unaccounted for (1/5 sources resolved)
EXIT=0
```

The workflow's "Reconcile L1 corpus" step therefore reports green while comparing **1 of 5 sources**.

This is the **sixth layer** of this repo's manufactured-green ladder — data → config → control flow
→ environment → scope → **exit code** — and it is the most dangerous so far, because unlike the
enforcement step's explicit `SKIPPED` it presents as an ordinary successful step. Nothing needs to be
edited to exploit it; it is the current state of `main`.

**The tool is scrupulously honest in prose and wrong in its exit code.** It prints `PARTIAL`, names
the four sources it did not check, and explains that it "certifies only the resolved sources". Then
it returns 0. **A gate is its exit code; everything else is documentation.**

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight   (private, petersimmons1972/hindsight)
Branch from: main    Work on: fix/reconcile-partial-exit
Suites:      cd /home/psimmons/projects/hindsight && python3 -m pytest guard/tests/ pipeline/tests/ -q
             cd /home/psimmons/projects/hindsight && bats guard/tests/*.bats bin/tests/*.bats
CI:          .github/workflows/guard.yml, step "Reconcile L1 corpus":
               python3 pipeline/reconcile_l1.py
Green baseline you must not regress: pytest 167, bats 92+, guard OK (171 IDs).
```

Locate by NAME in `pipeline/reconcile_l1.py`: the `ENUMERABLE` map · `REPO` / `P` derivation ·
`main()`'s verdict selection (`UNVERIFIED` / `SHORT` / `PARTIAL` / `COMPLETE`) and its final
`return 1 if short else 0`.

**Two environments. Every claim must hold in BOTH (FM-158):**

| | WORKSTATION | FRESH CHECKOUT (CI shape) |
|---|---|---|
| verdict | `COMPLETE (5/5 sources resolved)` | `PARTIAL (1/5 sources resolved)` |
| exit | 0 | **0 — the defect** |

Reproduce the fresh shape by copying `pipeline/` and `catalog/` into a directory whose parent holds
no sibling repos (e.g. `/tmp/freshco/hindsight`) and running from there. `HOME` is the **wrong
lever** — `P` derives from `REPO.parent`, not from `$HOME`, so relocating `HOME` still resolves 5/5.

## 3. GOAL

Make the exit code carry the verdict. `PARTIAL` must not be indistinguishable from `COMPLETE` to a
caller, and CI must stop reporting green on a 1-of-5 comparison — **without** losing the honest
reporting the tool already does, and without making a legitimate local run fail.

## 4. DEFINITION OF DONE

- **D1** `PARTIAL` exits **non-zero** by default. `UNVERIFIED` already exits 1; `SHORT` already exits
  1; `COMPLETE` exits 0. Exactly one verdict maps to 0.
- **D2** An explicit, named opt-out exists for the case where partial really is acceptable — e.g.
  `--allow-partial` — and it must **print what it is waiving** and the count of unchecked sources.
  It may not be the default, and CI may not pass it silently. *A gate that is painful gets disabled;
  a gate with no escape hatch gets deleted. Give it one and make it loud.*
- **D3** `.github/workflows/guard.yml` either resolves the sibling sources or **declares** that it
  runs a reduced check — it may not print green on 1/5 with no signal. Pick one and say which.
- **D4** The honest prose output is **unchanged**: the `PARTIAL` explanation, the named unresolved
  sources, and the SCOPE LIMIT block all still print. This plan changes an exit code, not a message.
- **D5** The local developer path still exits 0 when all five sources resolve — proven on the
  workstation.
- **D6** Tests pin **all four verdicts against their exit codes**, both directions (R2), each proven
  failing first (§8).

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.** Every new test must be demonstrated failing against the
  pre-change tree before the implementation exists. A test that passes on the unfixed tree is not
  evidence — it is CI-18.
- **R2 Both directions, always.** Every guard rule gets a test that it fires on the bad case and a
  test that it stays silent on the good case.
- **R4 Empty / zero / missing input must FAIL LOUD**, never pass silently. **The two zeros must be
  distinguishable**: "measured, found none" and "never measured" may not render the same.
- **R5 No exit status through a pipe.** `${PIPESTATUS[0]}` or no pipe.
- **FM-155** A floor or a count must measure units of work actually PERFORMED, never units merely
  PRESENT.
- **FM-158** A mechanism verified only in the developer's environment is unverified in the
  environment that gates. Every mutation runs in BOTH environments; a result from one environment is
  not a result.

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6.*

- **NEVER delete a catalog row, an L1 record, or an `id-ledger.txt` line to satisfy a validator.**
- **NEVER regenerate `catalog/id-ledger.txt`.** Restore it from git instead.
- **NEVER hand-assign a failure-mode ID.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill
  the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER relax, weaken, delete or skip an existing test to make a change pass.**
- **NEVER edit any file under `conf/` to make a check pass.**
- **NEVER edit any file under `pipeline/L1/` to make a check pass.** That is FM-154.
- **NEVER read a command's exit status through a pipe** (CI-17).
- **NEVER "fix" this by widening what counts as COMPLETE.** Renaming PARTIAL to COMPLETE, or scoring
  absent sources as 100%, is the `else 100.0` fail-open this tool already had once and removed.
- **NEVER modify a file not listed in §7.** **Do not merge, push to `main`, or open a PR.**

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/pipeline/reconcile_l1.py
/home/psimmons/projects/hindsight/pipeline/tests/test_reconcile_l1.py
/home/psimmons/projects/hindsight/.github/workflows/guard.yml
```
Three files.

## 8. RED-FIRST PROCEDURE

```bash
cd /home/psimmons/projects/hindsight
# B1 -- workstation: COMPLETE, exit 0 (must stay this way)
python3 pipeline/reconcile_l1.py >/tmp/b1.txt 2>&1; echo "B1 exit=$?"
grep -E 'COMPLETE|PARTIAL' /tmp/b1.txt

# B2 -- fresh checkout: PARTIAL, exit 0  <-- THE DEFECT
rm -rf /tmp/freshco && mkdir -p /tmp/freshco/hindsight
cp -r pipeline catalog /tmp/freshco/hindsight/
( cd /tmp/freshco/hindsight && python3 pipeline/reconcile_l1.py >/tmp/b2.txt 2>&1; echo "B2 exit=$?" )
grep -E 'PARTIAL|sources resolved' /tmp/b2.txt
```
Paste both. `B2 exit=0` alongside a `PARTIAL` verdict **is** the red. Then write the tests, run them,
observe them fail, paste that, and only then implement.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | fresh-checkout run (B2 recipe) | `PARTIAL`, **exit non-zero** |
| A2 | `python3 pipeline/reconcile_l1.py; echo "exit=$?"` on the workstation | `COMPLETE`, `exit=0` (D5) |
| A3 | fresh-checkout run with `--allow-partial` | exit 0 **and** prints what it waived + unchecked count (D2) |
| A4 | `grep -cE 'were NOT checked\|SCOPE LIMIT' /tmp/a1.txt` | ≥2 — prose unchanged (D4) |
| A5 | a tree with **zero** sources resolvable | `UNVERIFIED`, exit 1 (unchanged) |
| A6 | a genuinely short corpus | `SHORT`, exit 1 (unchanged) |
| A7 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥167 passed |
| A8 | `bats guard/tests/*.bats bin/tests/*.bats` | ≥92 ok |
| A9 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf` | **empty** (FM-154) |
| A10 | CI run on the branch | green **only** if D3's chosen option holds; a 1/5 comparison must not read as a pass |

## 10. MUTATION REQUIREMENT

Apply, show RED, restore, show GREEN — **each in BOTH environments** (FM-158):

- **M1** `PARTIAL` returns 0 again → A1's test must die.
- **M2** `--allow-partial` becomes the default → A1's test must die.
- **M3** `--allow-partial` stops printing what it waived → A3's test must die.
- **M4** absent sources are scored 100% so the verdict becomes `COMPLETE` → A1 **and** A4 must die.

Report survivors explicitly.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight
git checkout -- pipeline/reconcile_l1.py pipeline/tests/test_reconcile_l1.py .github/workflows/guard.yml
git checkout main && git branch -D fix/reconcile-partial-exit
rm -rf /tmp/freshco
```

## 12. ESCALATE INSTEAD OF GUESSING

- Making `PARTIAL` non-zero turns `main` red and you cannot see how CI is meant to resolve the four
  sibling sources — **report it and stop**. A red main telling the truth beats a green one that lies,
  but which of D3's two options to take is the founder's call.
- Any fix would require editing `conf/`, `pipeline/L1/`, or the `ENUMERABLE` map's contents.
- You cannot reproduce B2's `exit=0` — then the defect is environment-specific and that is the finding.

## 13. REPORT FORMAT

First line **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`. Then the §8 B1/B2
baselines, the failing-tests-first run, §9 actual beside expected, §10 both-environment results,
`git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch fix/reconcile-partial-exit off main.
Read /home/psimmons/projects/hindsight/plans/08-reconcile-partial-is-not-pass.md in full and execute
it exactly as written. It is self-contained. Modify ONLY the three files in section 7.
The defect: reconcile_l1.py prints PARTIAL and returns 0, so CI reports green while comparing 1 of 5
sources. Fix the EXIT CODE; do not touch the honest prose output, and never widen what counts as
COMPLETE. Complete section 8 first and paste both baselines BEFORE writing any implementation.
Run every mutant in section 10 in BOTH environments.
Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
