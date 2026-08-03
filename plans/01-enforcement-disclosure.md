# PLAN-01 — the enforcement verifier must disclose what it did not check
Issue: petersimmons1972/hindsight#18 · Status: COMPLETE — PR #27 merged at `99a3172`; main guard green · Blocked-by: none

## 1. CONTEXT YOU DO NOT HAVE

`hindsight` is a cross-repo failure-mode registry. Its L1 corpus records, per failure mode, an
`enforcement` path claimed to prevent it. `--verify-enforcement` checks whether those paths exist.
On CI only 1 of 13 source repos is checked out and that one has no enforcement-bearing entry, so
the check verifies nothing and honestly prints `SKIPPED`, exit 0. The founder ruled 2026-08-02 that
this step stays **ADVISORY but must print the count** of rows whose claimed mechanism does not
execute. The ruling was recorded and never implemented: the step is advisory *and silent*, which is
strictly less than what was authorised.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight   (private, petersimmons1972/hindsight)
Branch from: main    Work on: fix/18-enforcement-disclosure
Suites:      cd /home/psimmons/projects/hindsight && python3 -m pytest guard/tests/ pipeline/tests/ -q
             cd /home/psimmons/projects/hindsight && bats guard/tests/*.bats bin/tests/*.bats
             cd /home/psimmons/projects/hindsight && python3 guard/failure_mode_catalog_guard.py
CI:          .github/workflows/guard.yml on self-hosted `homelab-arc`. It is the ONLY workflow.
             Its last step is:
               python3 guard/failure_mode_catalog_guard.py --verify-enforcement --require-roots 1
Green baseline you must not regress: pytest 167, bats 92, guard OK (171 IDs), reconcile COMPLETE 5/5.
```

Locate symbols by NAME, never by line number, in `guard/failure_mode_catalog_guard.py`:
`verify_enforcement()` · `print_enforcement_report()` · `total_enforcement_bearing()` ·
`load_known_phantoms()` · `default_known_phantoms_path()` · `main()`.

**Two environments. Every claim must hold in BOTH (FM-158).** Measured 2026-08-02, exit 0 in both:

| | WORKSTATION (default `HOME`) | CI-SHAPE (`HOME=/tmp/hs-empty-home`) |
|---|---|---|
| `WARNING` | 221 machine entries have no enforcement | 221 (identical) |
| `ROOTS` | 13/13 | **1/13** |
| `DEBT-FLOOR` | 33 (floor 33) | 33 (floor 33) |
| `DEBT: 15 known phantom(s)` | present | **absent entirely** |
| per-source summary | real counts | `phantoms` and `checked` both **0** |

Summary column order is: `source machine judgment unbacked phantoms unverifiable checked`.

## 3. GOAL

Make the verifier state, on every run in every environment, three root-independent numbers and one
explicit measurement status; and make the phantom ledger load-bearing on the CI path. **The step
still enforces nothing new and still exits 0 where it cannot verify — that is the founder's ruling
and you must not change it.** What changes is that it stops being silent, and stops printing an
unmeasured `0` in a column that elsewhere means "none found".

## 4. DEFINITION OF DONE

- **D1** Every run, both environments, prints on stderr with these literal prefixes:
  ```
  enforcement-verifier: PHANTOM-DEBT: <N> documented in conf/known-phantoms.conf
  enforcement-verifier: UNBACKED: <M> machine entries carry enforcement: null
  enforcement-verifier: PHANTOMS-MEASURED: <K> across <S> source roots
    -- or, where nothing could be checked --
  enforcement-verifier: PHANTOMS-MEASURED: NOT MEASURED HERE (ROOTS <r>/<t>, 0 entries checked)
  ```
- **D2** The `phantoms` column prints `-` (not `0`) for any source whose `checked` is 0, and the
  summary header says so. **A count never taken must not render as a count of zero** (R4, FM-155).
- **D3** `conf/known-phantoms.conf` is loaded **before** the `SKIPPED` early return. Missing,
  unreadable or malformed ⇒ exit 1 naming the file, in BOTH environments. Today, deleting that file
  leaves CI output byte-identical — verified 2026-08-02.
- **D4** Exit status unchanged in every passing case: workstation 0, CI-shape 0,
  DEBT-FLOOR breach 1, unlisted-phantom 1. You are adding disclosure, not a gate. Prove all four
  before and after.
- **D5** Nothing describes this step as a ratchet or a gate, or as enforcing anything. Grep your own
  diff for those words.
- **D6** New tests in `guard/tests/test_verify_enforcement.py`, each proven failing first (§8).

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5. Do not paraphrase; `bin/check-plan-preamble.sh` compares bytes.*

- **R1 Red first, and prove the red.** Every new test must be demonstrated failing against the
  pre-change tree before the implementation exists. A test that passes on the unfixed tree is not
  evidence — it is CI-18.
- **R2 Both directions, always.** Every guard rule gets a test that it fires on the bad case and a
  test that it stays silent on the good case.
- **R4 Empty / zero / missing input must FAIL LOUD**, never pass silently. **The two zeros must be
  distinguishable**: "measured, found none" and "never measured" may not render the same.
- **R5 No exit status through a pipe.** `${PIPESTATUS[0]}` or no pipe.
- **R6 Every tool that writes emits an undo journal before writing.**
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
- **NEVER modify a file not listed in §7.** STOP and report instead.
- **Do not merge, push to `main`, or open a PR.** Push the branch only.
- **NEVER touch `.github/workflows/guard.yml` in this plan.**

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/guard/failure_mode_catalog_guard.py
/home/psimmons/projects/hindsight/guard/tests/test_verify_enforcement.py
```
## 8. RED-FIRST PROCEDURE

Run all four and paste the output. **These are your baseline. Write no implementation until this
section is done.**

```bash
cd /home/psimmons/projects/hindsight
mkdir -p /tmp/hs-empty-home

# B1 — CI shape today: no DEBT line, exit 0
HOME=/tmp/hs-empty-home python3 guard/failure_mode_catalog_guard.py \
    --verify-enforcement --require-roots 1 >/tmp/b1.txt 2>&1; echo "B1 exit=$?"
grep -c 'DEBT:' /tmp/b1.txt          # expect 0  <-- the silence this plan closes

# B2 — same, with the ledger hidden. Today INDISTINGUISHABLE from B1.
cp conf/known-phantoms.conf /tmp/kp.bak
mv conf/known-phantoms.conf /tmp/kp.hidden
HOME=/tmp/hs-empty-home python3 guard/failure_mode_catalog_guard.py \
    --verify-enforcement --require-roots 1 >/tmp/b2.txt 2>&1; echo "B2 exit=$?"
mv /tmp/kp.hidden conf/known-phantoms.conf     # RESTORE IMMEDIATELY
diff -q /tmp/b1.txt /tmp/b2.txt && echo "B1==B2: deleting the ledger is invisible on CI"

# B3 — the unmeasured zero
grep -A4 'summary (source' /tmp/b1.txt         # phantoms and checked both read 0

# B4 — workstation baseline, for the no-regression proof
python3 guard/failure_mode_catalog_guard.py --verify-enforcement --require-roots 1 \
    >/tmp/b4.txt 2>&1; echo "B4 exit=$?"
```

Then write the tests and run them **before** implementing: every new test must FAIL. Paste that
failing run. Only then implement.

## 9. ACCEPTANCE COMMANDS

Run from `/home/psimmons/projects/hindsight`. Report actual beside expected for every row.

| # | command | expected |
|---|---|---|
| A1 | `HOME=/tmp/hs-empty-home python3 guard/failure_mode_catalog_guard.py --verify-enforcement --require-roots 1 >/tmp/a1.txt 2>&1; echo "exit=$?"` | `exit=0` |
| A2 | `grep -c 'PHANTOM-DEBT: 15 documented' /tmp/a1.txt` | `1` |
| A3 | `grep -c 'UNBACKED: 221 machine entries' /tmp/a1.txt` | `1` |
| A4 | `grep -c 'PHANTOMS-MEASURED: NOT MEASURED HERE' /tmp/a1.txt` | `1` |
| A5 | `grep -A4 'summary (source' /tmp/a1.txt` | every row's `phantoms` column is `-`, not `0` |
| A6 | `mv conf/known-phantoms.conf /tmp/kp.hidden; HOME=/tmp/hs-empty-home python3 guard/failure_mode_catalog_guard.py --verify-enforcement --require-roots 1 >/tmp/a6.txt 2>&1; echo "exit=$?"; mv /tmp/kp.hidden conf/known-phantoms.conf` | `exit=1`, message names `conf/known-phantoms.conf` |
| A7 | `python3 guard/failure_mode_catalog_guard.py --verify-enforcement --require-roots 1 >/tmp/a7.txt 2>&1; echo "exit=$?"` | `exit=0` |
| A8 | `grep -c 'PHANTOMS-MEASURED: 15 across' /tmp/a7.txt` | `1` |
| A9 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥167 passed, zero failures |
| A10 | `bats guard/tests/*.bats bin/tests/*.bats` | ≥92 ok, zero failures |
| A11 | `python3 guard/failure_mode_catalog_guard.py; echo "exit=$?"` | `OK`, `exit=0`, 171 IDs |
| A12 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf .github` | **empty output** |

**A12 is not optional.** A change to this tool that touches its own inputs is FM-154.

## 10. MUTATION REQUIREMENT

Apply each, show RED, restore, show GREEN. **Run every mutant in BOTH environments from §2 and
report both results** (FM-158).

- **M1** `PHANTOMS-MEASURED` prints `0` instead of `NOT MEASURED HERE` on the unchecked path.
- **M2** the known-phantoms load is moved back after the `SKIPPED` early return.
- **M3** the summary prints `0` instead of `-` for a source whose `checked` is 0.

If a mutant survives, **say so explicitly**. A survivor reported is a good outcome; a survivor
omitted is the failure this repo exists to catalogue.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight
git checkout -- guard/failure_mode_catalog_guard.py guard/tests/test_verify_enforcement.py
# if already committed on the branch:
git checkout main && git branch -D fix/18-enforcement-disclosure
```
No file outside the repo is written. No network write. You perform no merge.

## 12. ESCALATE INSTEAD OF GUESSING

Stop and report if any of these occur:

- Reaching a DoD item appears to require editing a file outside §7.
- It appears to require editing anything under `conf/` or `pipeline/L1/`.
- An existing test fails and the only fix you can see is changing that test.
- The two environments disagree about a number you expected to be root-independent.
- You cannot make a new test fail before implementing — then it is not discriminating, and saying so
  is the correct outcome.
- Any command in §9 cannot be run exactly as written.

## 13. REPORT FORMAT

First line, **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`. The landing gate
matches on that string; 16 of 31 verify-role actors in this repo's history emitted no verdict line
and their work was unlandable by construction.

Then: the four §8 baselines · the failing-tests-first run · §9 actual beside expected · §10 results
for both environments · `git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch fix/18-enforcement-disclosure off main.
Read /home/psimmons/projects/hindsight/plans/01-enforcement-disclosure.md in full and execute it
exactly as written. It is self-contained; do not look for additional context and do not ask for it.
Hard constraints: modify ONLY the two files in its section 7; obey section 6 PROHIBITIONS literally;
complete section 8 (red-first) and paste the baseline output BEFORE writing any implementation; run
every command in section 9 verbatim and report actual vs expected; run every mutant in section 10 in
BOTH environments. Do not merge, push to main, or open a PR -- push the branch only.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
