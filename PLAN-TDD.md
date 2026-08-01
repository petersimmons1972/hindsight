# hindsight — TDD implementation plan (v2)

*Supersedes the wave/dispatch decomposition in `~/.claude/plans/fuzzy-beaming-riddle.md`,
which remains valid as the record of Waves 0–1. This document governs everything from
2026-08-01 forward. One accepted version — revise in place, do not append drafts.*

---

## The premise this plan corrects

Wave 1 produced five PRs. Every one read as "all CI green." **CI has never executed a
single job in this repository.** The only `SUCCESS` on any PR is GitGuardian; the `guard`
workflow — the thing that validates this project — reports an *empty conclusion*, which
renders blank rather than red. Two of the five packets shipped defects (both
silent-truncation) that their green gates could not see. PR #1's entire subject matter was
CI wiring, and it wired CI to a runner scaleset that does not exist for this repo.

So the failure was not in the code. It was in the **gate**: a test suite that never ran,
and a "baseline" that passed against the unfixed tree. Both are the families this repo
exists to catalogue (FM-149, FM-150, CI-1, CI-18).

**Therefore this plan inverts the order.** The gate is built and proven *before* any
further feature work lands. Concretely, three things must be mechanically true before
Phase 2 opens:

1. A CI run on this repo reaches a **non-empty conclusion** (Phase 0).
2. A test added by any packet is **proven to fail on the pre-change tree** (Phase 1).
3. A check with no conclusion is treated as **RED** by the landing gate (Phase 0).

Until those hold, "TDD" is a claim about process, not a property of the artifact.

---

## Standing rules for every phase

These are contract, not advice. Each is drawn from a measured failure in this repo or the
handoff record.

| # | Rule | Origin |
|---|---|---|
| R1 | **Red first, and prove the red.** Every new test must be demonstrated failing against the merge-base tree before the implementation exists. A test that passes on the unfixed tree is not evidence — it is CI-18. | C6b shipped `baseline: guard 0` |
| R2 | **Both directions, always.** Every guard rule gets a test that it *fires on the bad case* and a test that it *stays silent on the good case*. A guard that rejects everything gets disabled within a day. | `lesson-a-fix-can-invert-the-error`, three-laws "honest cost" |
| R3 | **Ground-truth fixtures are coordinator-authored**, committed before the packet is dispatched. Codex may add tests; it may not author the acceptance fixture. | `lesson-validators-must-pass-ground-truth` |
| R4 | **Empty / zero / missing input must FAIL LOUD**, never pass silently. Applies to every counter, parser and matcher built here. | CI-1, FM-150, fleet#152 `total == 0` |
| R5 | **No exit status through a pipe.** `${PIPESTATUS[0]}` or no pipe. | CI-17 |
| R6 | **Every tool that writes emits an undo journal before writing**, and exposes `--undo`. No implicit default target; an unrecognised argument aborts rather than falling back. | FM-146/147/148, three-laws Law 3 |
| R7 | **A green check is not evidence until its conclusion is non-empty.** Landing runs `bin/require-real-ci.sh`, never a human reading of `gh pr view`. | FM-149/150 |
| R8 | **Dispatches are serial in this repo.** `.dispatch/covariates` and `.dispatch/probes` are not pruned by `checkout_state_snapshot`, so concurrent dispatches cross-trip each other's leak detectors. | known env bug, 3rd instance |
| R9 | **No `--apply` of the sync tool against anything real** without founder sign-off. Dry-run + temp-repo unit tests only. | 2026-08-01 incident |

---

## Phase 0 — Make the gate real *(blocks everything; ~1 session)*

### D1 — Runner decision — **RESOLVED AND EXECUTED 2026-08-01 17:52 EDT**

Founder chose (a). `arc-hindsight` installed: namespace `arc-runners-hindsight`, chart
`gha-runner-scale-set-0.14.2`, `runnerScaleSetName=homelab-arc`, image
`registry.petersimmons.com/arc-runner:2.334.0-fleet5`, `minRunners 0 / maxRunners 3` —
identical to the ten existing scalesets. The GitHub App was already installed on the repo
(App token reads it). Undo: `helm uninstall arc-hindsight -n arc-runners-hindsight &&
kubectl delete ns arc-runners-hindsight`. Install script, with its undo journal emitted
before the first write: `~/.claude/jobs/2c17b6f5/tmp/create-arc-hindsight.sh`.

**Measured outcome — V1 satisfied.** The listener claimed the backlog within ~25s. All 20
queued runs drained to `completed`. First real CI signal in this repo's history.

**And it immediately paid for itself: PR #1 is the only PR that fails.**

| PR | packet | guard check, first real execution |
|---|---|---|
| #1 | C7 CI wiring | **FAILURE** |
| #2 | C6 vendor sync | SUCCESS *(but review FAIL stands — a green gate is not a correct gate)* |
| #3 | C1 clustering | SUCCESS |
| #4 | C4 enforcement verifier | SUCCESS |
| #5 | C5 schema validator | SUCCESS |

#1's failure: `python3 -m pip install --user numpy` → **PEP 668
`externally-managed-environment`** on the runner image. The fix is a venv (or
`--break-system-packages`, or `apt install python3-numpy`) — prefer a venv, since
`pipeline/` will grow deps. **The packet whose entire subject was CI wiring is the packet
CI rejects the moment CI exists.** That is the plan's premise, confirmed on first contact,
and it is why #1's earlier review pass carries no weight.

Note #2's SUCCESS carefully: the reviewer *reproduced* a real batch-abort defect in it.
Green and correct are independent properties — C6c still replaces it.

### D1 — original options *(kept for trace)*

`runs-on: homelab-arc` matches ten ARC scalesets, each pinned to its own
`githubConfigUrl`. None is `hindsight`, so jobs queue forever. Two options:

- **(a) Create `arc-hindsight`.** One `helm install` of `gha-runner-scale-set-0.14.2`
  into a new namespace, `githubConfigSecret: arc-github-app` (copied into that
  namespace), `githubConfigUrl: https://github.com/petersimmons1972/hindsight`,
  `minRunners: 0 / maxRunners: 3` — matching the other ten exactly. Reversible via
  `helm uninstall`. Requires the GitHub App to be installed on the repo. New k8s objects
  in the shared cluster ⇒ founder call.
- **(b) Retarget `guard.yml` to `ubuntu-latest`.** Zero infra. Contradicts the standing
  convention that private repos use our own runners, and spends free-tier private minutes.

**Recommendation: (a).** The convention exists for a reason and the delta is one helm
release identical to ten already running. (b) is the acceptable fallback if the App
install is a problem.

### G1 — `bin/require-real-ci.sh` — mechanize FM-149 + FM-150

The one piece of new code in Phase 0. It is the mechanism that would have caught this
entire incident, and it is built test-first.

**Contract.** Given a PR number, exit 0 **only if** every required check has
`status == completed` AND a **non-empty** `conclusion` AND that conclusion is `SUCCESS`.
Any check that is `queued`/`in_progress` for more than a configurable window, or that
reports an empty conclusion, is **RED**. Zero checks found is **RED** (R4).

**RED tests, authored first** (`bin/tests/test_require_real_ci.bats`, fixture JSON
captured from the live `gh` API — no network in tests):

| test | fixture | expected |
|---|---|---|
| T1 | all checks `completed/SUCCESS` | exit 0 |
| T2 | one check `queued`, no conclusion | exit 1, message names the check |
| T3 | one check `completed` with **empty** conclusion | exit 1 — *this is the live hindsight case* |
| T4 | **zero** checks returned | exit 1, "no checks reported" (R4) |
| T5 | one check `completed/FAILURE`, rest success | exit 1 |
| T6 | only GitGuardian succeeded, `guard` absent entirely | exit 1 — required-check list is explicit, not "whatever ran" |

T3, T4 and T6 are the discriminating trio: each reproduces a distinct way this repo
already went green while validating nothing. **Prove all six fail before writing the
script** (there is no script — they fail on absence; capture that as the baseline).

### G2 — Re-verify PR #1 against a live runner

Once D1 lands, push a trivial commit and confirm a run reaches `completed/success`.
**Then re-open PR #1's review**: it passed a review while its subject matter was broken,
so its pass carries no weight.

PR #1 *does* extend `guard.yml` to the full gate (numpy, pytest over `guard/tests/` +
`pipeline/tests/`, bats, `reconcile_l1.py`, plus `validate_l1.py` and
`--verify-enforcement`) — main still runs only three steps. Two things to re-check:

- **The two conditional steps are named "… when available" and guard on file existence.**
  A step that silently skips when its target is absent is the fail-silent-gate family
  (R4). Once C5/C4 land, those files always exist — so the conditional must be removed,
  not left as a permanent soft pass. Track this as a required follow-up on #1, or the
  workflow keeps a built-in way to certify less than it appears to.
- The job installs bats via `apt-get` on every run; confirm that actually works on the
  new scaleset image before trusting the first green.

**Phase 0 exit criteria** — all four mechanically checkable:
- `gh run list` shows ≥1 run `completed` with a non-empty conclusion.
- `bats bin/tests/test_require_real_ci.bats` green, and all 6 tests confirmed failing on
  the pre-change tree.
- `bin/require-real-ci.sh 1` correctly reports RED *today* (it should — #1 is UNSTABLE).
- `guard.yml` executes the full gate.

---

## Phase 1 — Mechanize the TDD contract *(~1 session, no dispatch)*

C6b's dispatch row read `baseline: guard 0` rather than `discriminating` — its new tests
passed against the unfixed tree, so they proved nothing, and the reviewer reproduced the
bug anyway. That is not a Codex failure; it is a missing mechanism.

### G3 — `bin/verify-discriminating.sh`

**Contract.** Given a branch, for each test file added or modified relative to
`merge-base(main, HEAD)`: check that file out into a scratch worktree at the merge-base
tree, run it, and **require it to FAIL**. If a new test passes against the pre-change
code, exit 1 naming the file. Emits a machine-readable row for the dispatch ledger:
`discriminating: N/M`.

**RED tests first** (`bin/tests/test_verify_discriminating.bats`):
- a genuinely discriminating test → exit 0
- a test that passes on merge-base (e.g. `assert true`) → exit 1, names the file
- a test file that *errors* on merge-base for an unrelated reason (import of a module the
  branch adds) → must count as discriminating, not as a false pass — and must say which
  reason it saw (R2 inversion)
- zero changed test files → exit 1 "no new tests" (R4), not a silent 0/0 pass

**Then wire it in** as a `--check` clause on every subsequent dispatch:
`python3 -m pytest … -q && bash bin/verify-discriminating.sh`.

**This is Law 1 applied to our own process** — the rule "prove the baseline is
discriminating" stops being a brief instruction and becomes a command that fails.

---

## Phase 2 — Land the standing queue *(serial, re-gate each time)*

Order is chosen by risk, lowest first, so the landing gate itself is exercised on cheap
packets before the expensive ones.

| order | PR | packet | state | action |
|---|---|---|---|---|
| 1 | #5 | C5 L1 schema validator | review pass | Land once `require-real-ci` is green. Add R4 test: zero-entry input must FAIL, not report "0 invalid". |
| 2 | #4 | C4 enforcement verifier | review pass | Land. Its measured output (24 phantom paths, 200 unenforced `machine` entries) becomes Phase 5 input. |
| 3 | #1 | C7 CI wiring | re-review required | Land only after Phase 0 proves the workflow executes. |
| 4 | #3 | C1 clustering | **unreviewed** | Adversarial cross-vendor review (Grok) before landing — see below. |
| 5 | #2 | C6 vendor sync | **review FAIL** | Do not land. Superseded by C6c. |

### PR #3 — adversarial review brief (the one place vendor diversity is reserved)

Everything downstream reads `clusters.jsonl`. Reviewer is told to **reject the premise**,
not list nits, and to find **both inversions by name**:

- an input where a genuinely novel failure mode lands inside an existing cluster
  (false positive → the guard will block real new entries → guard gets disabled);
- an input where a known duplicate falls outside every cluster (false negative → the
  entire point of the project silently does not work).

Plus: attack the tests. Can this suite pass while clustering is broken? The degeneracy
invariant (bad threshold ⇒ exit 1, write nothing) must be probed with a threshold that is
*plausible* rather than absurd. And the "both backends agree" claim must be re-derived,
not accepted from the PR body.

### C6c — sync rework *(dispatch, discriminating baseline REQUIRED)*

The reviewer reproduced: an unguarded `mkdir` under `set -e` inside the per-repo loop
aborts the whole 12-repo batch on one bad consumer; later repos are never attempted and
never reported. C6b did not fix it.

**RED tests first, all against temp repos (R9):**

| test | assertion |
|---|---|
| T1 | repo #3 of 12 has an unmakeable target dir → repos 4–12 are still attempted, and the summary reports 1 failure / 11 attempted. **Must fail on the current tree.** |
| T2 | batch summary counts `attempted`, `succeeded`, `failed`, and `attempted == 12` always. Zero-attempted ⇒ exit 1 (R4). |
| T3 | target file exists and lacks our authorship fragment → refuse, exit non-zero, write nothing (FM-147). |
| T4 | target path is namespaced (`docs/vendor/hindsight/…`), never a bare `docs/failure-modes.md` (FM-147). |
| T5 | undo journal written **before** the first write, listing every target with prior state (absent / untracked / tracked+hash); `--undo` restores exactly (FM-148, Law 3). |
| T6 | unrecognised argument ⇒ abort, no fallback to a default target (FM-146). **This is the exact incident.** |
| T7 | `--dry-run` is the default; `--apply` requires an explicit flag AND a non-empty `--consumers` path. |

---

### G3 — drop the ordering rule, add the append-only invariant *(founder-approved 2026-08-01)*

**Sequenced after #4 lands** — #4 is the only open PR that touches
`guard/failure_mode_catalog_guard.py` (#5 is pipeline-only). Doing this before #4 lands
guarantees a conflict in the same file.

**Measured basis.** The catalog is 150 rows, IDs FM-1…FM-150: **zero gaps, zero duplicates,
5 out-of-order transitions.** The guard has no gap check at all — `next_id()` is `max + 1`,
so position is never read. The ordering rule emits **5 warnings on every single run**,
including inside the pre-commit hook.

**Why order does not matter.** Nothing reads the catalog in ID order; lookup is grep-by-content.
The rule has never caught a defect and structurally cannot. It is also wrong on the merits: it
flags `FM-145 precedes FM-98`, which are the *recovered* rows deliberately placed beside
topically related entries. Grouping by subject is more useful than sorting by integer, so the
rule warns about the better arrangement, and it fights the natural append-at-the-end workflow.
This is `lesson-text-gates-cosmetic-strictness`. The cost is not zero: five lines of routine
noise per run trains everyone to skim guard output, which is exactly how an empty CI conclusion
went unnoticed for eight hours on 2026-08-01.

**Why gaps do not matter either — but the thing behind them does.** A gap is the correct
outcome of renumbering a duplicate (already done deliberately: FM-127 for a live duplicate
FM-28). But a gap is also the fingerprint of a **deleted row**, and deletion is this repo's
near-catastrophe — a fork "resolved" FM-REC-01..11 by deleting eleven real failure modes.
"No gaps" is a bad proxy for that: it fires on a legitimate renumber, and stays **silent** if
someone deletes a row *and* renumbers to close the hole. The property worth enforcing is that
**the ID set never shrinks.**

**The change.**
1. Delete the ordering rule and its 5 warnings.
2. Delete `test_out_of_order_is_a_warning_not_an_error`, replacing rather than relaxing it
   (repo CLAUDE.md: never relax a test to make a change pass). Its embedded reasoning —
   that fatally enforcing order would force a destructive renumbering — is correct and is
   preserved as the argument for *not reintroducing* the rule in fatal form; record it in the
   new test's docstring so the reasoning outlives the rule.
3. Add `--check-append-only`: assert the committed ID set is a **superset** of the previous
   commit's. This is the mechanism that would actually have caught the FM-REC deletion.

**RED tests first, both directions (R1, R2):**

| test | assertion |
|---|---|
| T1 | a commit adding FM-151 to the existing 150 → pass |
| T2 | a commit **deleting** FM-99 → **exit 1**, naming FM-99. *This is the FM-REC case.* |
| T3 | a commit renumbering FM-28 → FM-151 (a delete + an add) → **exit 1** — a renumber is a deletion of the old ID and must be declared, not inferred |
| T4 | `--force-renumber="<why>"` permits T3 and records the justification | 
| T5 | out-of-order rows produce **no output at all** — the rule is gone, not demoted again |
| T6 | prior commit unreadable / no parent (initial commit) ⇒ **exit 1, fail loud**, never "no baseline, so everything is fine" (R4) |

T6 is the one that matters most: the natural implementation of an append-only check
degrades to a silent pass exactly when it cannot find its baseline.

---

## Phase 3 — Wave 2: the packets that are the point

### C2 — recurrence report

Gate is a coordinator-authored ground-truth assertion (R3), not a Codex-written test.

**RED tests** (`pipeline/tests/test_recurrence_report.py`, fixture
`pipeline/tests/fixtures/recurrence_ground_truth.json`):
- the report surfaces a `completion-signal` cluster with **≥6 members**
  (OPS-11/16/21/23/28, MDL-18);
- a `shared-mutable-checkout` cluster with **≥7 members** (OPS-8/13/36/38/41/45/48);
- `fail-silent-gate` (CI-1 + FM-5/FM-8/orch-FM-7) and `dedup-identity-key`
  (ORC-1a/b/c) both present;
- ranking is by member count then date span, and each row prints member IDs, source
  repos, first/last seen;
- **empty clusters.jsonl ⇒ exit 1**, never an empty report (R4).

**If the report does not independently surface the ≥7× completion-signal cluster and the
7× shared-checkout cluster, clustering is wrong and Phase 4 must not open.** Synthesising
from bad clusters produces confident nonsense.

### C3 — duplicate-cause guard *(the decisive packet)*

`--check-duplicate-cause`: embed a proposed entry, match against `clusters.jsonl`, reject
on threshold hit, printing matching IDs and that cluster's recurrence count.
`--force-new-cause="<why>"` overrides and records the justification into the entry.

**Coordinator-authored fixtures, committed before dispatch (R3):**
- `guard/tests/fixtures/reworded_duplicates.jsonl` — ≥8 real catalogued failure modes
  rewritten in different words, different vocabulary, no shared distinctive tokens where
  avoidable. Each must be **rejected**, naming the right cluster.
- `guard/tests/fixtures/novel_causes.jsonl` — ≥8 genuinely new failure descriptions.
  Each must be **accepted**. This is the inversion guard (R2) and the reason the guard
  will still be enabled in a month.

**RED tests:**

| test | assertion |
|---|---|
| T1 | every row in `reworded_duplicates.jsonl` is rejected, and the message names the matching cluster + its recurrence count |
| T2 | every row in `novel_causes.jsonl` is accepted |
| T3 | `--force-new-cause="reason"` lands a rejected row **and writes the justification into the entry** — assert the text is in the catalog afterwards |
| T4 | `--force-new-cause=""` (empty reason) is refused |
| T5 | missing or empty `clusters.jsonl` ⇒ **exit 1, fail loud** — never "no clusters, so nothing is a duplicate" (R4). This is the single most likely silent-failure path in the whole project. |
| T6 | end-to-end: reword a real catalogued FM, attempt `bin/add-failure-mode.sh`, confirm the pre-commit path rejects it naming the existing cluster; then confirm the override lands it with justification recorded |

**Measured acceptance, stated as numbers before the packet is dispatched:** 0 false
negatives on the reworded set, 0 false positives on the novel set. Anything else and the
threshold is re-calibrated against the fixtures — the fixtures are not weakened.

---

## Phase 4 — Synthesis *(Workflow agents, pinned; not Codex)*

Judgment work. Every `agent()` call pins `model:` explicitly (opus/sonnet/haiku) — an
unpinned call is a bug.

- **W1** — family synthesis, `parallel()` ×4, each agent isolated to its own family's
  clusters, never the corpus. Families: agent/orchestration runtime · infra/ops ·
  measurement/research · content/publishing. → `L2/<family>.md` ×4.
- **W2** — global synthesis + memory reconciliation, single agent, input is the four
  family docs only. → `L3/invariants.md`, `L3/memory-reconciliation.diff`.
  **Promotion rule: ≥2 distinct source repos or it stays repo-level.** Assert
  mechanically that no L3 law has single-repo provenance. Memory files are a protected
  path — W2 emits a **diff only**, never a write.
- **W3** — enforcement conversion, `pipeline()` over classes. Each class resolves to
  `machine` (a named, committed, existing path) or `judgment` (explicitly unenforceable,
  with its procedural substitute). **Exactly two outcomes. "Documented" is not a state.**

---

## Phase 5 — Close the enforcement gap, then the harness corpus

C4 already measured the gap: **24 phantom enforcement paths** (claim a mechanism that
does not exist) and **200 `machine`-tagged entries with no enforcement at all**. Phantoms
are worse than gaps because they read as covered.

1. **Phantoms first.** Each of the 24 is either implemented or demoted to `null`
   (`enforcement: null` is a correct answer — repo CLAUDE.md). Wire
   `--verify-enforcement` into CI so a new phantom cannot land.
2. **Act independently of this project:** `SECURITY-INCIDENT-2026-01-18.md` names
   `/home/psimmons/.git/hooks/pre-commit` as its remediation. **Verified absent.** That is
   a live security gap with a documented-but-nonexistent fix, not a hindsight task.
3. **Then the harness corpus** (three-laws "one campaign, two corpora"): run the W3
   classifier over `CLAUDE.md` + the memory files.

### The measured ratio, and what it means for scope

`pipeline/harness/RATIO.md` (commit `971d1c1`) set the decision rule before measuring:
60% transformative, 15% a rounding error. Result over 145 normative rules, 9 isolated
agents, counts recomputed from JSONL rather than agent self-reports:

**mechanism 8.3% / partial 31.7% / judgment 59.3%.** Below the rounding-error line.

Two findings resize the plan: 4 of the 12 mechanisms already exist (the entire live
enforcement surface is one 354-line PreToolUse hook plus one settings value), so
buildable-new is **5.5%**; and all 8 high-confidence rows are `mechanism` — not one
`partial` is high confidence — so 40% is an eroding ceiling. Rejected hypothesis on
record: mechanizability does **not** track blast radius (5.6% destructive vs 9.2%
elsewhere).

**Law 1 therefore cannot fix context rot** — it removes ~8% of a corpus that is 0.025% of
spend. Simplifying context and mechanizing rules are independent programs. The leverage is
Laws 2 and 3, which also cover the irreducible 59%.

### D2 — the 8 unbuilt mechanisms *(founder call, open)*

Build them, or accept the ratio and put the effort into Laws 2/3?

**Recommendation: build them, but after Phase 3.** All eight are cheap and seven share the
PreToolUse trigger, so the marginal cost is small and they are the only high-confidence
rows in the corpus. But they are 5.5% of a small lever — they do not deserve to precede
the packets that make the registry actually reject a duplicate. Laws 2/3 get their own
plan once Phase 4 names the invariants.

---

## Verification ledger — what "done" means for this project

Not a claim, in every case a command. Nothing below is satisfied by a review pass.

| # | Assertion | Command |
|---|---|---|
| V1 | CI actually executes | `gh run list --repo petersimmons1972/hindsight --json status,conclusion` → a `completed` run with non-empty conclusion |
| V2 | No check is trusted while blank | `bash bin/require-real-ci.sh <pr>` |
| V3 | New tests discriminate | `bash bin/verify-discriminating.sh` → `discriminating: N/N` |
| V4 | Catalog is sound | `python3 guard/failure_mode_catalog_guard.py` → OK |
| V5 | Corpus coverage holds | `python3 pipeline/reconcile_l1.py` → **COMPLETE**, exit 0 (note its own printed scope limit: it cannot see non-enumerable content, and says so) |
| V6 | Recurrence is measured, not asserted | `pytest pipeline/tests/test_recurrence_report.py` — ground-truth families surface |
| V7 | **The decisive test** | reworded known FM is rejected naming its cluster; `--force-new-cause` lands it with justification recorded |
| V8 | No phantom mechanisms | `--verify-enforcement` → 0 phantoms |
| V9 | Sync is safe | dry-run resolves all 12 consumers; unrecognised arg aborts; undo journal restores |
| V10 | Provenance | no L3 law has single-repo provenance |

---

## Sequencing

```
D1 runner decision (founder)
 └─ Phase 0  G1 require-real-ci  +  live CI proof  +  #1 re-review
     └─ Phase 1  G2 verify-discriminating           [no dispatch; both are mine]
         └─ Phase 2  land #5 → #4 → #1 → #3(after adversarial review) ;  C6c replaces #2
             └─ Phase 3  C2 → C3          [C3 is the point of the project]
                 └─ Phase 4  W1 → W2 → W3
                     └─ Phase 5  phantoms → harness corpus → D2
```

Serial throughout (R8). One dispatch in flight at a time in this repo.

## Standing debts carried into this plan

- **A real audition slot.** Exempted three times, each defensibly — which is exactly how
  a gate stops meaning anything. Do it on ONE standalone mechanical packet. An unresolved
  audition blocks every dispatch in the repo, so never open one while a batch is in
  flight. **Candidate: G2 `verify-discriminating` in Phase 1** — standalone, mechanical,
  fully specified by its own test list, and nothing depends on it landing fast.
- **`cli-dispatch` covariate/probe leak** (3rd instance of this detector being wrong).
  Salvage script: `~/.claude/jobs/2c17b6f5/tmp/salvage.sh`. Worth filing upstream.
- **Stale `GH_TOKEN`** — App installation tokens expire hourly. Refresh inside scripts via
  `gh-app-token claude`; never the `$(...)` prefix on the command line.
