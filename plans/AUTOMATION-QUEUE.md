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

`--audition-exempt` is **no longer routinely needed** (it was, until 2026-08-03). The audition gate
keys on the `(model, harness)` **pair**, and no harness except `opencode` had a `model` configured,
so every cli-dispatch row recorded `model=""` and all codex tiers collapsed into one permanently
"established" pair. `~/.config/cli-dispatch/harnesses.toml` now pins a model per harness, so the
ledger records the tier that actually ran and thin pairs are auditionable again. Pass
`--audition-exempt` only when a specific start genuinely warrants it, with a truthful reason.

`cli-dispatch` returns exit 10 (`committed-no-pr`) when the agent declines to self-certify — that is
**not** a failure. Inspect the worktree under `.dispatch/worktrees/<task>/`, verify the baselines
yourself, then push and open the PR manually.

## Choosing a tier — and when to fan out

**Default to `--harness codex-workflow` for anything with more than one moving part** (founder
ruling, 2026-08-03). A `gpt-5.6-sol` coordinator plans, fans out to cheap children, and synthesizes.
The point is not raw capability, it is **context hygiene**: each child reads the files its own
subtask needs and returns a short answer, so the coordinator's window never accumulates the whole
corpus. That is the same reason this campaign runs on workflows rather than one long session.

Pick by what the work actually demands, not by what is available:

| tier | price in/out per Mtok | use it for |
|---|---|---|
| `gpt-5.6-luna` | $0.20 / $1.20 | mechanical, fully specified: apply this diff, grep-and-report, rename, single-file edit against a stated contract |
| `gpt-5.6-terra` | $2 / $12 | ordinary implementation where the shape is known but the details are not |
| `gpt-5.6-sol` | $5 / $30 | coordination, security-adjacent reasoning, anything adversarial, and any packet whose failure mode is subtle |

Children are `luna` by default; promote a child to `terra` only when a `luna` child has actually
failed the subtask, not pre-emptively.

**The harness default is `gpt-5.6-sol` for every codex start, so a mechanical packet run without
`--model` silently costs flagship rates.** Every packet in the queue above is single-file and fully
specified, so name the cheap tier explicitly:

```bash
cli-dispatch start … --harness codex --model gpt-5.6-luna --effort low …
```

Reach for `codex-workflow` on the `plans/04` chain, on #21, and on anything requiring independent
verification.

```bash
cli-dispatch start --repo … --task <packet> --harness codex-workflow --base origin/main \
  --expect-files … --check … --check-strength behavioral --negative-cases yes \
  --brief-file plans/briefs/<packet>.md
```

### What a fan-out brief must contain

The coordinator runs under `-s workspace-write`, so a child cannot simply be spawned — three
ingredients are mandatory and each was isolated by experiment. Copy this block into any brief that
fans out:

```
STEP 1 — give each child its own CODEX_HOME inside this worktree (they cannot share one):
  for n in 1 2; do
    mkdir -p ".cx-$n"
    ln -sf "$HOME/.codex/auth.json"   ".cx-$n/auth.json"
    ln -sf "$HOME/.codex/config.toml" ".cx-$n/config.toml"
  done

STEP 2 — run the children IN PARALLEL. CODEX_HOME and < /dev/null are mandatory:
  CODEX_HOME=./.cx-1 codex exec -m gpt-5.6-luna -s read-only -C . "<subtask>" < /dev/null > .w1 2>&1 &
  CODEX_HOME=./.cx-2 codex exec -m gpt-5.6-luna -s read-only -C . "<subtask>" < /dev/null > .w2 2>&1 &
  wait

HARD LIMITS: exactly N children, no nesting, no retries.
STEP 3 — synthesize, then delete the .cx-* and .w* scratch files so only the real change is added.
```

Why each ingredient, stated so nobody removes one as noise:

1. **`CODEX_HOME` inside the worktree, `ln -sf` not `cp`.** The default `~/.codex` is outside the
   sandbox, and a child pointed at it dies with `failed to initialize in-process app-server client:
   Read-only file system (os error 30)`. Symlink rather than copy — `~/.codex` is 2.3GB, and copying
   would duplicate a credential. Children must not share one home.
2. **`< /dev/null` on every child.** Without it the child prints `Reading additional input from
   stdin...` and hangs until the stall timer kills the whole dispatch.
3. **`sandbox_workspace_write.network_access=true`** — set for you by the `codex-workflow` harness,
   not by the brief. Without it children spawn fine and then die with `stream disconnected before
   completion: error sending request for url (https://chatgpt.com/backend-api/codex/responses)`.

The coordinator keeps `-s workspace-write` throughout. Do **not** reach for
`--dangerously-bypass-approvals-and-sandbox`: it is unnecessary once the three items above are
right, and it is blocked by the Claude Code auto-mode classifier anyway.

Children are `-s read-only` on purpose. If a subtask must write, have the child emit its patch to a
scratch file and let the coordinator apply it — that keeps exactly one writer in the worktree and
avoids two children racing on the same file.

Verified end-to-end on 2026-08-03 through `cli-dispatch start --harness codex-workflow`:
`agent_exit=0`, discriminating check passed, only the intended file added, scratch cleaned up.

## Verification gate before any merge

Do not merge on the agent's own `VERDICT: CONFIRMED_GOOD`. For each PR:

1. Re-run the baselines above **yourself** in the branch worktree.
2. Mutation-test the change: reintroduce the defect and confirm a test fails. A surviving mutant
   means the test is theatre.
3. Confirm `git diff --numstat origin/main...HEAD -- catalog pipeline/L1` is empty unless the packet
   explicitly authorises L1 edits (packets 3–5 do).
4. Re-confirm CI green **at merge time**, not merely that it was green earlier.
