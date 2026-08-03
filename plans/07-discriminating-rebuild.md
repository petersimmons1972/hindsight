# PLAN-07 — rebuild the discriminating check by reverting the hunk, not copying the tree
Issue: petersimmons1972/hindsight#23 · Replaces PR #10 · Status: READY · Blocks nothing

## 1. CONTEXT YOU DO NOT HAVE

This repo requires that a new test be **proven failing against the pre-change tree** before its
implementation exists (rule R1). A tool was built to mechanise that check — `verify-discriminating.sh`
— and it failed over three rounds. **Its design is disqualified, and the reason is precise.**

It copied each new test into a **merge-base worktree**, ran it, and counted *any* nonzero exit as
discriminating. But a test of genuinely new code **cannot even import** at merge-base. Measured both
directions: with an import of a module the branch adds → `exit=0, discriminating: 1/1`; the identical
assertion without that import → `exit=1, discriminating: 0/1`. **So it is not a discrimination check.
It is a "does this test reference something new" check — which every TDD diff satisfies by
construction.** No classification fixes it: copying a file to an older tree conflates "the behaviour
is absent" with "the module is absent", and the second is true of essentially every new test.

It also gates nothing today: `rg -n verify-discriminating .github/` returns **0 hits**.

**The replacement design, founder-approved:** keep the test, **revert the diff's implementation
hunks**, and run at HEAD. The module still exists — only its behaviour is gone. This is exactly what
the adversarial verifiers did by hand all campaign, and it caught every real defect found.

This packet also discharges the standing **audition debt** — a real audition slot exempted three
times, which is exactly how a gate stops meaning anything.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight
Branch from: main    Work on: feat/23-verify-discriminating
Prior art:   PR #10 (to be closed with evidence, not merged) -- read it, reuse nothing uncritically;
             its 671 lines predate this repo's hardening and were never mutation-tested.
Green baseline: pytest 167, bats 92, guard OK (171 IDs), reconcile COMPLETE 5/5.
```

**Run this as a three-stage cross-vendor triangle, and record each stage in
`qa-ledger/actor-results.jsonl`:** stage 1 attack spec (vendor A) committed **before any
implementation exists** → stage 2 build (vendor B) → stage 3 verify (vendor C). `bin/tests/check-attackspec-red.sh`
exists to validate stage 1's inverted contract — the deliverable is a suite that **fails**, and it
separates four outcomes a naive `! bash suite.sh` collapses.

## 3. GOAL

`bin/verify-discriminating.sh`: given a branch, for each test added or modified relative to
`merge-base(main, HEAD)`, revert the diff's **implementation** hunks at HEAD, run the test, and
require it to FAIL. Emit `discriminating: N/M`. Then **wire it into the landing gate** — a mechanism
nothing calls is the trap this repo has now hit twice (`require-real-ci.sh`, `similar-causes.py`).

## 4. DEFINITION OF DONE

- **D1** A genuinely discriminating test → exit 0.
- **D2** A test that passes with the implementation reverted → exit 1, **naming the file**.
- **D3** **The import confound is gone**, proven by the exact pair from §1: a test whose only red-
  making element is an import of a new module is **not** certified as discriminating.
- **D4** Zero changed test files ⇒ **exit 1, "no new tests"** (R4) — never a silent `0/0` pass.
- **D5** Renames are handled: `git mv` plus an edit must not be silently dropped. The old tool used
  `--diff-filter=AM` and lost them.
- **D6** Symlinked test files are not materialised as text, certified without ever running.
- **D7** Files outside the detection globs are **counted in the denominator or reported**, never
  silently skipped while `N/M` conceals them.
- **D8** It is **called by something**: wired into `bin/land.sh` (or the workflow), and that wiring
  is proven by removing it and observing a failure.

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.** **R2 Both directions, always.**
- **R3 Ground-truth fixtures are coordinator-authored**, committed before the packet is dispatched.
- **R4 Empty / zero / missing input must FAIL LOUD.** The two zeros must be distinguishable.
- **R5 No exit status through a pipe.** **R6 Undo journal before writing.**
- **R8 Dispatches are serial in this repo.**
- **FM-158** Every mutation runs in BOTH environments; a result from one environment is not a result.

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6, plus one from this tool's own history.*

- **NEVER resurrect the merge-base-copy design.** It is disqualified by measurement, not by taste.
- **NEVER report a red-first claim you have not run.** One round-3 report asserted 3 failures and
  reproduced 2 — the failure family this repo exists to catalogue, committed inside the tool built
  to prevent it.
- **NEVER delete a catalog row or L1 record**; **NEVER regenerate `catalog/id-ledger.txt`.**
- **NEVER relax a test to make a change pass.** **NEVER edit `conf/` or `pipeline/L1/` to pass a check.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER read a command's exit status through a pipe** (CI-17). **NEVER modify a file not listed in §7.**
- **Do not merge, push to `main`, or open a PR.**

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/bin/verify-discriminating.sh
/home/psimmons/projects/hindsight/bin/tests/test_verify_discriminating.bats
/home/psimmons/projects/hindsight/bin/land.sh
/home/psimmons/projects/hindsight/docs/DISCRIMINATING.md
```

## 8. RED-FIRST PROCEDURE

Stage 1's deliverable is a suite that **fails against absence**. Validate it with
`bash bin/tests/check-attackspec-red.sh <suite>` and require the **"red with output"** branch — not
"suite absent", not "suite green", not "red but silent". Paste that classification. Then build.

Include, as a fixture, the literal §1 pair — one test made red only by a new import, one made red by
the behaviour — and assert the tool separates them.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | `bash bin/verify-discriminating.sh` on a branch with a genuinely discriminating test | `exit=0`, `discriminating: N/N` |
| A2 | same, on a branch whose test passes with implementation reverted | `exit=1`, names the file (D2) |
| A3 | the §1 import-only fixture | **not certified** (D3) |
| A4 | a branch with zero changed test files | `exit=1`, "no new tests" (D4) |
| A5 | a `git mv`-plus-edit branch | detected, not dropped (D5) |
| A6 | a symlinked test file | not certified without running (D6) |
| A7 | `rg -n verify-discriminating bin/land.sh .github/` | ≥1 hit (D8) |
| A8 | remove the wiring → run the landing gate | fails, proving D8 is load-bearing |
| A9 | `bats bin/tests/*.bats` | ≥92 ok overall |
| A10 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf` | **empty** |

## 10. MUTATION REQUIREMENT

Run each in **both** environments (FM-158):

- **M1** count any nonzero exit as discriminating → D3's test must die.
- **M2** restore `--diff-filter=AM` → D5's test must die.
- **M3** silently skip files outside the globs → D7's test must die.
- **M4** treat zero changed test files as `0/0` pass → D4's test must die.

Report survivors explicitly. Mutation survival — not code reading — is what caught every real defect
in this repo's history.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight && git checkout -- bin/ docs/ && \
  git checkout main && git branch -D feat/23-verify-discriminating
git worktree list   # remove any scratch worktree this tool created
```

## 12. ESCALATE INSTEAD OF GUESSING

- Reverting implementation hunks cannot be done cleanly for a diff shape you encounter — report the
  shape; that is a real finding about the design's limits.
- You cannot separate the §1 import pair — **stop**. That is the disqualifying property of the old
  design and it must not ship twice.
- Wiring into `bin/land.sh` would change landing behaviour beyond adding this check.

## 13. REPORT FORMAT

First line **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`, then the stage-1 red
classification, §9 actual-vs-expected, §10 both-environment results, the D8 wiring proof,
`git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch feat/23-verify-discriminating off main.
Read /home/psimmons/projects/hindsight/plans/07-discriminating-rebuild.md in full and execute it
exactly as written. It is self-contained. Modify ONLY the four files in section 7.
The design is: keep the test, revert the diff's IMPLEMENTATION hunks, run at HEAD. Do NOT copy tests
into a merge-base worktree -- that design is disqualified by measurement and must not ship twice.
Never report a red-first claim you have not actually run. Complete section 8 first.
Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
