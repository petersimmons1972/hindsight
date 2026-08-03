# Automation queue — packets ready for unattended dispatch

_Produced 2026-08-03 from an 11-agent triage that **measured** each issue's state rather than
trusting issue text or the campaign record. Every packet below is sized to this repo's ceiling
(≤250 lines, ≤5 files, exactly 1 issue) and carries its own brief under `plans/briefs/`._

**Before trusting any status header in `plans/*.md`, re-measure.** Several were found stale:
`plans/06` said "BLOCKED by 02" while plan 02 is verifiably complete (PR #28 merged, `recurrence_of`
live in `bin/add-failure-mode.sh:376,476` with bats coverage). Trust `plans/00-INDEX.md` and git.

---

## READ THIS FIRST — the constraint that will break your packet

`guard/tests/test_verify_enforcement.py::test_committed_floor_has_no_slack_against_the_committed_corpus`
asserts that `conf/enforcement-floor.conf` **equals** the number of enforcement-bearing L1 rows on
the committed corpus. It reads the real conf and the real corpus, deliberately — every other test in
that file monkeypatches a synthetic floor, which is exactly how a loosened ratchet nearly shipped
green on 2026-08-03.

**Therefore: any packet that adds, removes, or nulls an `enforcement` value MUST re-baseline
`conf/enforcement-floor.conf` in the same commit.** Equality is intentional, not an oversight — the
ratchet means "adding real enforcement raises the floor". The floor is currently **35**.

Measure it with:

```
python3 guard/failure_mode_catalog_guard.py --verify-enforcement | grep DEBT-FLOOR
```

Standing prohibitions, non-negotiable in every packet below:

- **NEVER** relax, skip, invert or delete a test to make a change pass. An assertion flipped from
  `== 0` to `!= 0` is a defect, not a fix; this was caught twice on 2026-08-03.
- **NEVER** delete a catalog row. **NEVER** regenerate `catalog/id-ledger.txt`.
- **NEVER** edit `catalog/` or `pipeline/L1/` to make a check pass. An `enforcement` value of `null`
  is a CORRECT answer — never invent a test or hook path to fill the field.
- **NEVER** read a command's exit status through a pipe (CI-17). Use `${PIPESTATUS[0]}`.
- **NEVER** write a machine-specific interpreter path into a committed file. Use
  `#!/usr/bin/env python3`. There is a guard test enforcing this; it exists because
  `#!/home/linuxbrew/.linuxbrew/bin/python3` shipped in a committed helper and made 11 of 25 sync
  tests fail on CI while passing locally.
- A **green suite is not evidence** for security-adjacent work. Four consecutive rounds of the
  `plans/04` repair were fully green alongside a reproduced live escape.

## Baselines (measured on `a41db44`)

```
python3 -m pytest guard/tests/ pipeline/tests/ -rs --tb=no
   -> 183 passed, 2 skipped
   -> the ONLY acceptable skips are pipeline/tests/test_reconcile_l1.py:213 and :230
      ("sibling source repos are not checked out here")
   -> an EXTRA skip in pipeline/tests/test_cluster.py means the embedding backend is DOWN.
      That is known variance, NOT a regression: 177+4 == 179+2 == 181 collected. Do not "fix" it.
bats guard/tests/*.bats bin/tests/*.bats   -> 0 not-ok
python3 guard/failure_mode_catalog_guard.py -> OK, 171 canonical IDs
python3 pipeline/reconcile_l1.py            -> COMPLETE 5/5 on a workstation with sibling repos
                                               checked out; PARTIAL in a bare worktree is expected
```

Use `/home/linuxbrew/.linuxbrew/bin/python3` for your own commands only.

---

## Ordered queue

| # | Packet | Issue | Ready | Brief |
|---|---|---|---|---|
| 1 | `32-land-dated-corpus` | #32 | **YES** | `plans/briefs/32-land-dated-corpus.md` |
| 2 | `20-1-decoy-disposition` | #20 | **YES** | `plans/briefs/20-1-decoy-disposition.md` |
| 3 | `33-A-stale-paths` | #33 | after #2 | `plans/briefs/33-A-stale-paths.md` |
| 4 | `33-C-malformed-enforcement` | #33 | after #3 | `plans/briefs/33-C-malformed-enforcement.md` |
| 5 | `33-B2-homelab-phantoms` | #33 | **YES** | `plans/briefs/33-B2-homelab-phantoms.md` |
| 6 | `30-1-snapshot-format` | #30 | **YES** | `plans/briefs/30-1-snapshot-format.md` |

**Not automatable — do not dispatch:**

- **#38 / #39** — ruling-blocked. Both target code **deliberately deleted** from `claude-codex` main
  by `8ddc0d8` / PR #555 (the 2026-07-19 node-lane stand-down). ccx-FM-001's mechanism was real and
  tested (`cfc0ebb`, PR #76) and was retired with its host subsystem — so these are not "never
  mechanized" gaps. Building tests at the claimed paths would be hollow coverage the issues
  themselves forbid.
- **#21** — the coordinator must author and commit
  `pipeline/tests/fixtures/l3_ground_truth.jsonl` **before** any synthesis dispatch. The synthesizing
  agent may not author its own grading fixture (plan 06 D7/R3).
- **#20-2/3/4** — blocked behind the `plans/04` chain landing.
- **`plans/04` chain (PRs #40 ← #41 ← #43 ← #44 ← #46)** — round 4 verification returned
  DO_NOT_MERGE on three reproduced blockers. **Do not dispatch round 6 until the push-vs-pull design
  question is ruled on** (see `docs/DECISIONS.md` and `~/HANDOFF.md`).

## Dispatch invocation

Each packet runs as a single serial dispatch — **one at a time, never concurrently**:

```bash
cli-dispatch start \
  --repo /home/psimmons/projects/hindsight \
  --task <packet-name> \
  --harness codex \
  --base origin/main \
  --expect-files '<from the brief>' \
  --check '<from the brief>' \
  --check-strength behavioral \
  --negative-cases yes \
  --brief-file plans/briefs/<packet>.md
```

**The audition slot currently rejects every available pairing** (`codex`, `grok` and `claude` are all
"established"; `opencode` fails on billing), so each start additionally needs `--audition-exempt`
with a truthful reason until that is fixed. See `~/HANDOFF.md` BLOCKED ON FOUNDER item 7.

`cli-dispatch` returns exit 10 (`committed-no-pr`) when the agent declines to self-certify — that is
**not** a failure. Inspect the worktree under `.dispatch/worktrees/<task>/`, verify the baselines
yourself, then push and open the PR manually.

## Verification gate before any merge

Do not merge on the agent's own `VERDICT: CONFIRMED_GOOD`. For each PR:

1. Re-run the baselines above **yourself** in the branch worktree.
2. Mutation-test the change: reintroduce the defect and confirm a test fails. A surviving mutant
   means the test is theatre.
3. Confirm `git diff --numstat origin/main...HEAD -- catalog pipeline/L1` is empty unless the packet
   explicitly authorises L1 edits (packets 3–5 do).
4. Re-confirm CI green **at merge time**, not merely that it was green earlier.
