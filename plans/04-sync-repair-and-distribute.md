# PLAN-04 — repair the sync channel so the floor reaches its consumers
Issue: petersimmons1972/hindsight#22 (closes #24) · Status: READY · Blocked-by: none · Blocks: 05

## 1. CONTEXT YOU DO NOT HAVE

`hindsight` is the canonical failure-mode registry; twelve other repos hold vendored copies. The
tool that distributes them is PR #2, and it is defective in a reproduced way: an unguarded `mkdir`
under `set -e` inside the per-repo loop **aborts the whole 12-repo batch on one bad consumer**, and
the later repos are never attempted and never reported. On 2026-08-01 an earlier version of this
tool, invoked with an unrecognised flag, fell back to a real config and **wrote into 11 live repos**,
overwriting an L0 source corpus. It was recoverable only because git happened to be underneath.

**A second, worse instance is already on `main`.** `bin/sync-failure-modes.sh` is tracked, takes
**no arguments**, and `cp`s unconditionally into every path in its config, then exits 0 regardless of
skips. Measured 2026-08-02: `grep -cE 'dry-run|--apply|undo'` → **0**. It has no dry-run default, no
undo journal and no explicit apply flag — the exact shape of the incident above, live, today. **This
plan covers that file too; PR #2 is not the only offender.**

Founder ruling: **repair, do not close.** The capability is wanted; the blast radius is not. This
plan also makes the channel load-bearing for plan 05 — it becomes the transport for a per-repo
enforcement self-check, not just catalog text.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight
Branch from: main    Work on: fix/22-sync-repair
Existing:    the PR #2 branch (dispatch/C6-vendor-sync) · conf/consumers.conf
Green baseline: pytest 179 passed + 2 skipped, bats 109, guard OK (171 IDs), reconcile COMPLETE 5/5.
```

## 3. GOAL

Rebuild the sync tool to `bin/land.sh` discipline: dry-run by default, undo journal emitted **before**
the first write, no implicit target, and a batch that cannot be silently truncated by one bad
consumer. Every contract pinned by a test proven red first.

## 4. DEFINITION OF DONE

Carried verbatim from C6c's T1–T7 so closing #24 loses nothing:

- **T1** Repo 3 of 12 has an unmakeable target dir → repos 4–12 are **still attempted**, and the
  summary reports 1 failure / 12 attempted. **Must fail on the current tree.**
- **T2** The summary counts `attempted`, `succeeded`, `failed`, and `attempted == 12` always.
  Zero-attempted ⇒ exit 1 (R4).
- **T3** A target file exists and lacks our authorship fragment → refuse, exit non-zero, write
  nothing (FM-147).
- **T4** The target path is namespaced (`docs/vendor/hindsight/…`), never a bare
  `docs/failure-modes.md` (FM-147).
- **T5** An undo journal is written **before** the first write, listing every target with its prior
  state (absent / untracked / tracked+hash); `--undo` restores exactly (FM-148, Law 3).
- **T6** An unrecognised argument ⇒ abort, **no fallback to a default target** (FM-146). *This is
  the literal 2026-08-01 incident.*
- **T7** `--dry-run` is the default; `--apply` requires an explicit flag **and** a non-empty
  `--consumers` path.

Plus: **D8** the batch summary distinguishes "attempted and found no change" from "not attempted"
(R4, the two zeros).

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.** **R2 Both directions, always.**
- **R3 Ground-truth fixtures are coordinator-authored.**
- **R4 Empty / zero / missing input must FAIL LOUD.** The two zeros must be distinguishable.
- **R5 No exit status through a pipe.**
- **R6 Every tool that writes emits an undo journal before writing**, and exposes `--undo`. No
  implicit default target; an unrecognised argument aborts rather than falling back.
- **R8 Dispatches are serial in this repo.**
- **R9 No `--apply` of the sync tool against anything real** without founder sign-off. Dry-run plus
  temp-repo unit tests only.

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6, plus the one that matters most here.*

- **NEVER run this tool with `--apply` against any real repository during development or testing.**
  Every test uses temp repos created by the test itself. This prohibition is the whole plan.
- **NEVER delete a catalog row or L1 record**; **NEVER regenerate `catalog/id-ledger.txt`.**
- **NEVER relax a test to make a change pass.** **NEVER edit `conf/` or `pipeline/L1/` to pass a check.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER read a command's exit status through a pipe** (CI-17).
- **NEVER modify a file not listed in §7.** **Do not merge, push to `main`, or open a PR.**

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/bin/sync-failure-modes.sh
/home/psimmons/projects/hindsight/bin/tests/test_sync_failure_modes.bats
/home/psimmons/projects/hindsight/bin/failure-modes-projects.conf.example
/home/psimmons/projects/hindsight/docs/SYNC.md
```
`bin/sync-failure-modes.sh` is the file **already on main** and is the primary target: T1-T7 apply to
it first, then to whatever PR #2 contributes.

## 8. RED-FIRST PROCEDURE

Build a 12-temp-repo fixture where repo 3's target dir cannot be created. Run T1 against the current
tree and **observe the batch abort** — that is the red. Paste it. Only then implement.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | `bats bin/tests/test_sync_failure_modes.bats` | all ok, T1–T7 + D8 |
| A2 | `bash bin/sync-failure-modes.sh --consumers /tmp/tmprepos.conf 2>/tmp/a2.err; echo "exit=$?"` | `exit=0`, dry-run banner, 12 attempted |
| A3 | `bash bin/sync-failure-modes.sh --bogus-flag; echo "exit=$?"` | non-zero, **no write**, no fallback (T6) |
| A4 | `bash bin/sync-failure-modes.sh --consumers ""; echo "exit=$?"` | non-zero (T7) |
| A5 | `grep -c 'undo' /tmp/a2.err` | ≥1 — journal named before any write |
| A6 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥179 passed, 0 failed |
| A7 | `bats guard/tests/*.bats bin/tests/*.bats` | ≥109 ok |
| A8 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf/known-phantoms.conf` | **empty** |

## 10. MUTATION REQUIREMENT

- **M1** restore the unguarded `mkdir` under `set -e` → T1 must die.
- **M2** make `--apply` the default → T7 must die.
- **M3** write the undo journal *after* the first write → T5 must die.
- **M4** let an unrecognised arg fall through to the default consumers file → T6 must die.

Report survivors explicitly.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight && git checkout -- bin/ conf/ docs/ && \
  git checkout main && git branch -D fix/22-sync-repair
rm -rf /tmp/tmprepos*        # test fixtures only — never a real repo
```

## 12. ESCALATE INSTEAD OF GUESSING

- Any step appears to require `--apply` against a path outside `/tmp`.
- A consumer repo's real layout is needed to write a test — use a fixture, or stop and report.
- You cannot make T1 fail on the current tree.

## 13. REPORT FORMAT

First line **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`, then the red-first proof,
§9 actual-vs-expected, §10 results, `git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch fix/22-sync-repair off main.
Read /home/psimmons/projects/hindsight/plans/04-sync-repair-and-distribute.md in full and execute it
exactly as written. It is self-contained. Modify ONLY the four files in section 7.
ABSOLUTE CONSTRAINT: never run this tool with --apply against any real repository, for any reason.
All tests use temp repos the test itself creates. An earlier version of this tool wrote into 11 live
repos and overwrote a source corpus. Complete section 8 first and paste the failing batch-abort.
Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
