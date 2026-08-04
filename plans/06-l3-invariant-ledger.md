# PLAN-06 — L3 synthesis as a validated ledger, not prose
Issue: petersimmons1972/hindsight#21 · Status: FOUNDER-BLOCKED — plan 02 is complete and the
coordinator fixture landed in PR #63, but W1/W2 require disk-spooled inputs absent from §7/§14's
allowed-file contract. Founder must authorize exact retained artifact paths and review/retention
policy before W1 dispatch. Founder ruling 1, reshaped.

## 1. CONTEXT YOU DO NOT HAVE

`hindsight` synthesises failure modes through tiers: L0 raw corpora → L1 normalised entries → L2
clusters and a recurrence report → **L3, which does not exist yet**. Founder ruling 1 named this the
next task. It was resequenced *after* plan 02 (with the founder's approval) for one reason: plan 02
makes each entry carry a `recurrence_of` decision, which changes what "a recurrence" *is* — L3 built
first would need re-deriving.

The original spec produced markdown documents (`L3/invariants.md`). **That is reshaped here.** This
repo's own measurement found the harness rule corpus is **8.3% mechanism / 59.3% judgment**, and its
doctrine states *"documented is not a state — it is the state we are escaping."* A synthesis document
is another diary. The deliverable is a **machine-readable ledger with exactly two outcomes**.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight
Branch from: main    Work on: feat/21-l3-invariant-ledger
Inputs:      pipeline/L2/clusters.jsonl (pinned) · pipeline/L2/recurrence-report.md · pipeline/L1/*.jsonl
Note:        This is JUDGMENT work. Run it as pinned Workflow agents (opus/sonnet/haiku explicitly
             named -- an unpinned agent call is a bug), not as a single mechanical dispatch.
```

## 3. GOAL

Produce `pipeline/L3/invariants.jsonl` where **every row resolves to `machine` or `judgment` and
nothing else**, plus the validator that makes a third state impossible.

- **W1** family synthesis — one agent per family, isolated to its own clusters, never the whole
  corpus (spool to disk, never to context). Families: agent/orchestration runtime · infra/ops ·
  measurement/research · content/publishing.
- **W2** global synthesis, input is the four family outputs only.
- **W3** enforcement conversion — each class resolves to `machine` (a named, committed, **existing**
  path) or `judgment` (explicitly unenforceable, **with its procedural substitute**).

## 4. DEFINITION OF DONE

- **D1** `pipeline/validate_l3.py` exits 1 on any row that is neither `machine` nor `judgment`.
  **"Documented" is not a state.**
- **D2** Exits 1 on any `machine` row whose named path does not exist (`--assert-paths-exist`).
  A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **D3** Exits 1 on any row with **single-repo provenance** — an L3 invariant requires ≥2 distinct
  source repos. One incident on one host is repo-level.
- **D4** Every `judgment` row names its **procedural substitute**. A row that is unenforceable and
  offers nothing in its place is not a finding, it is a shrug.
- **D5** Empty or missing `clusters.jsonl` ⇒ **exit 1**, never an empty ledger (R4).
- **D6** Memory files are a protected path: W2 emits a **diff only, never a write**.
- **D7** Ground truth for the validator is coordinator-authored and committed **before** the
  synthesis runs (R3) — the synthesising agent may not author the fixture that grades it. This
  repo already paid for that lesson: one agent authored both the regex markers and the sentences
  grading them, and the gate was measuring itself.

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.** **R2 Both directions, always.**
- **R3 Ground-truth fixtures are coordinator-authored**, committed before the packet is dispatched.
- **R4 Empty / zero / missing input must FAIL LOUD.** The two zeros must be distinguishable.
- **R5 No exit status through a pipe.** **R8 Dispatches are serial in this repo.**

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6, plus two specific to this plan.*

- **NEVER write to any file under `~/.claude/`.** Memory files are protected; emit a diff.
- **NEVER promote an invariant with single-repo provenance.** A pointer to another file is not a
  lesson at all.
- **NEVER delete a catalog row or L1 record**; **NEVER regenerate `catalog/id-ledger.txt`.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER relax a test to make a change pass.** **NEVER edit `conf/` or `pipeline/L1/` to pass a check.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER read a command's exit status through a pipe** (CI-17). **NEVER modify a file that is
  neither listed by name in §7 nor located under a directory listed in §7.**
- **Do not merge, push to `main`, or open a PR.**

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/pipeline/validate_l3.py
/home/psimmons/projects/hindsight/pipeline/L3/invariants.jsonl
/home/psimmons/projects/hindsight/pipeline/tests/test_validate_l3.py
/home/psimmons/projects/hindsight/pipeline/tests/fixtures/l3_ground_truth.jsonl
/home/psimmons/projects/hindsight/docs/L3.md
/home/psimmons/projects/hindsight/pipeline/L3/work/
```

## 8. RED-FIRST PROCEDURE

Write `test_validate_l3.py` against the coordinator-authored fixture **first**, including a row in a
third state, a `machine` row with a non-existent path, and a single-repo-provenance row. Run and
observe every test fail on absence. Paste it. Only then implement.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | `python3 pipeline/validate_l3.py; echo "exit=$?"` | `exit=0` on the real ledger |
| A2 | `python3 pipeline/validate_l3.py --assert-paths-exist; echo "exit=$?"` | `exit=0`; every `machine` path resolves |
| A3 | *fixture with a third state* → validate | exit 1 naming the row (D1) |
| A4 | *fixture with single-repo provenance* → validate | exit 1 naming the row (D3) |
| A5 | `python3 pipeline/validate_l3.py --clusters /dev/null; echo "exit=$?"` | exit 1 (D5) |
| A6 | `grep -c '"kind": *"judgment"' pipeline/L3/invariants.jsonl` vs rows carrying a substitute | equal (D4) |
| A7 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥179 passed, 0 failed |
| A8 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf` | **empty** |
| A9 | `bats guard/tests/*.bats bin/tests/*.bats` | ≥109 ok, 0 failures |

## 10. MUTATION REQUIREMENT

- **M1** allow a third state to pass → D1's test must die.
- **M2** skip the path-existence assertion → D2's test must die.
- **M3** accept single-repo provenance → D3's test must die.
- **M4** empty clusters yields an empty ledger and exit 0 → D5's test must die.

Report survivors explicitly.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight && git checkout -- pipeline/ docs/ && \
  git clean -fd pipeline/L3 pipeline/tests && \
  git checkout main && git branch -D feat/21-l3-invariant-ledger
```
This reverts tracked changes and removes only UNTRACKED/uncommitted work (`git clean -fd`, never
`rm -rf`) so a committed brief already merged under `pipeline/L3/` survives the undo.
No file outside the repo is written; in particular nothing under `~/.claude/`.

## 12. ESCALATE INSTEAD OF GUESSING

- A candidate invariant is clearly real but has single-repo provenance — report it, do not promote it.
- A class resolves to neither `machine` nor `judgment` — that is a finding about the taxonomy; report it.
- Producing a `machine` row would require inventing a path that does not exist. **Use `judgment`.**
- The synthesis would need the whole corpus in one context — re-partition instead.

## 13. REPORT FORMAT

First line **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`, then the red-first run,
§9 actual-vs-expected, §10 results, the ledger's `machine`/`judgment` split, `git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch feat/21-l3-invariant-ledger off main.
Read /home/psimmons/projects/hindsight/plans/06-l3-invariant-ledger.md in full and execute it exactly
as written. It is self-contained. Modify ONLY the files named in section 7, and files located
under a directory named in section 7 -- nothing else.
Every L3 row resolves to `machine` or `judgment` -- there is no third state, and "documented" is not
one. Never invent a path to fill a field; `enforcement: null` and `judgment` are correct answers.
Never write to ~/.claude/ -- emit a diff. Complete section 8 first and paste the failing run.
Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
