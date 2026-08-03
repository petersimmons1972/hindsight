# DECISIONS — founder rulings and their application state

Every ruling carries a state: **APPLIED** · **HALF-APPLIED** · **OPEN**. That third column is the
point of this file. Issue #18 sat for a day as a ruling that was *recorded but not implemented* —
"half-applied" had nowhere to live, so it read as done.

A HALF-APPLIED ruling is worse than an unapplied one: it reads as covered.

| # | date | ruling | state | evidence / next |
|---|---|---|---|---|
| 1 | 2026-08-01 | **D1 runner** — create an ARC scaleset for this repo rather than retargeting to GitHub-hosted | APPLIED | `arc-hindsight` installed, ns `arc-runners-hindsight`; 20 queued runs drained; first real CI signal in the repo's history. Undo: `helm uninstall arc-hindsight -n arc-runners-hindsight` |
| 2 | 2026-08-01 | **D2 the 8 unbuilt mechanisms** — build them, after Phase 3 | OPEN, **relocated** | They are PreToolUse hooks and belong in `~/.claude`, not this repo (Law 2: reach follows context). Out of scope here; needs its own small plan in the harness |
| 3 | 2026-08-02 | **Next push: build the recurrence spine** (clusterer → recurrence report → L2/L3), over "wire up what exists" and over "keep hardening" | APPLIED through L2 | C1c landed (PR #13), L2 pinned, C2 landed (PR #17), `pipeline/L2/recurrence-report.md` committed. **L3 remains** — `plans/06` |
| 4 | 2026-08-02 | **V8 enforcement step stays ADVISORY, but must print the count** | **HALF-APPLIED** | The ruling is recorded; the count is not implemented. The step is advisory *and silent*, strictly less than what was authorised. `plans/01` closes it — and measurement on 2026-08-02 found it is worse than "silent": the CI path prints `phantoms: 0` where 0 means *not measured*, and never loads the phantom ledger at all |
| 5 | 2026-08-02 | **PR #2 (vendor sync): repair, do not close** — dry-run default, undo before act, red-first tests | OPEN | `plans/04`, issue #22. Keeps the capability, removes the blast radius that wrote into 11 live repos |
| 6 | 2026-08-02 | **G2 / PR #10: rebuild, do not land and do not drop** — re-derive from an attack spec written before any implementation, cross-vendor | OPEN | `plans/07`, issue #23. Also discharges the standing audition debt |
| 7 | 2026-08-02 | **Direction: rewire, then finish.** The rejectionist case (freeze as a read-only measurement product) was considered and declined — its critique of Phases 4/5 is accepted as *shape* wrong, not worthless | APPLIED | `PLAN.md` "Scope correction". The word "gate" changed referent when C3 was cancelled by measurement, and no phase had been re-derived from the new one |
| 8 | 2026-08-02 | **Sequencing: #19 before #21**, departing from ruling 3's stated next task | APPLIED | Surfaced as a deviation and approved, not slipped in. Recurrence recorded at write time is the only measurable signal; post-hoc matching runs at 1/77 recall. L3 built first would need re-deriving |
| 9 | 2026-08-02 | **Enforcement relocates to source repos.** Six rounds failed at increasing subtlety and the bypass got *shorter* each round | APPLIED as design | `plans/05`. hindsight cannot see another repo's filesystem; no seventh round fixes that. PR #12 closes only once the capability has moved |
| 10 | 2026-08-02 | **Plan 03 scope: arms reported separately, never pooled.** Ruled as two arms; **amended by ruling 15 to three** when the phantom census produced Arm C | OPEN | `plans/03` §3. Discharged by packet P2 (PREREG) |
| 11 | 2026-08-02 | **Detection asymmetry: pre-register the bias direction**, do not re-measure the pre-period. Pre-period recurrence is visible only through the 1/77-recall clusterer; post-period comes from write-time `recurrence_of`, whose recall is strictly higher, so post-period counts are biased *upward* -- conservative against REDUCED and uninformative for a null. Any drop smaller than the declared bias reads UNDERPOWERED by rule | OPEN | `plans/03` §4 D8. Packet P2 |
| 12 | 2026-08-02 | **Repair `first_seen` before any denominator.** 242 of 484 L1 rows carry no date. Git-derive from each row's `source_anchor` in its own source repo; ingest-date fallback for the remainder, flagged per row so a fallback date is never read as organic logging | OPEN | Packet P0. Prerequisite for every denominator |
| 13 | 2026-08-02 | **Arm B: recover ship dates first.** No mechanism records one -- `enforcement` is `{file, kind}` only -- so backdating a trend is not currently possible. Build `mechanisms.jsonl` by git archaeology across the 3 owning repos, *then* decide whether a trend is reachable | OPEN | Packet P1. Recorded in advance: most of the 8 today (13 if the 5 stale paths are repaired) are expected to have too little post-period span |
| 14 | 2026-08-02 | **The comparator is a size-matched POOL**, not one family: all families at n≥5 carrying zero enforcement claims of any kind (real, phantom or malformed). Only this rule regenerates the 15 and keeps the pool disjoint from Arm C | OPEN | `plans/03` §3. Matching gap on record: largest pool family is n=11 against a test family at n=22 |
| 15 | 2026-08-02 | **Claimed-only families become a third arm, CLAIMED-ONLY.** Composition: 7 genuine phantoms plus 2 malformed enforcement values. c-013 (n=22) named two enforcement mechanisms and c-001 (n=13) named one — all three are verified genuine phantoms, files that were never built. If they recur like no-claim families the effect is mechanical; if like real-mechanism families, the effect was attention, not mechanization | OPEN | `plans/03` §3. Needs no counters and no ship dates -- the cheapest arm and the sharpest RELOCATED-adjacent evidence available today |
| 16 | 2026-08-02 | **Arm A is selected by rule plus holdout**, never a hand-picked list: every family at n≥5 as of the freeze commit, randomly split by a seed committed in PREREG, prior art suppressed for the held-out half | OPEN | Packet P2a -- **time-critical**: the holdout must ship before post-period data accumulates, or Arm A has no control. Known cost: for ~11 families prior art is deliberately not surfaced for 90 days |
| 17 | 2026-08-02 | **Counters: full cross-repo instrumentation** at the 6 distinct real mechanism paths across 3 repos, transported by the repaired sync channel | OPEN | Packet P3, depends on `plans/04` (#22). Until it lands **RELOCATED is unreachable** and must not be approximated |
| 18 | 2026-08-02 | **D2/D3 scope per arm.** The fire-count requirement binds Arm B only. Arm A's counter is hindsight's own ingest log; Arm C is exempt by construction — a family whose only enforcement claim is not real has nothing that could fire | OPEN | `plans/03` §4 D2/D3. Each arm declares its own evidence requirement in PREREG (packet P2) |
| 19 | 2026-08-02 | **REDUCED is tested against Arm A's randomised holdout alone.** The 15-family size-matched pool is a descriptive reference for Arms B and C and can never change a verdict | OPEN | `plans/03` §4 decision rule. The pool is not randomised, so a failure against it would be uninformative |
| 20 | 2026-08-02 | **The arm axes are independent; the overlap is declared, not removed.** Arm A varies whether hindsight surfaces prior art (randomised, within-repo); Arms B and C vary whether a cross-repo mechanism exists (observational). A family may appear in both | OPEN | `plans/03` §3. PREREG names each family's arm memberships and reports them alongside its result |
| 21 | 2026-08-02 | **Arm B's floor drops to n≥3**, doubling it from 3 families to 6 — c-043 (10), c-045 (7), c-063 (6), c-082 (3), c-104 (3), c-191 (3) — across fleet, fleet-dispatch and substack | OPEN | `plans/03` §3. At n≥5 the arm sat one family above the ≥2 decision-rule floor, so one failed instrumentation collapsed it |

## Standing debts

- **A real audition slot**, exempted three times — which is exactly how a gate stops meaning
  anything. Discharged by `plans/07` (#23). Never open one while a batch is in flight.
- **`cli-dispatch` covariate/probe leak**, third instance of that detector being wrong. File
  upstream and record the issue number here — an unfiled third instance of a wrong detector is
  itself the recurrence this project exists to measure.

## Open questions needing a ruling, not a decision

- **Resolved 2026-08-02 — Plan 03 measurement inputs.** Recorded as rulings 10–17 above. The four
  inputs the packet was blocked on are now named, and two of the founder's first answers were
  withdrawn under measurement (there is no cross-repo history to backdate against, and no mechanism
  carries a ship date). Superseded questions are kept nowhere; the rulings table is the record.
- **Round 7 scope.** The fleet record says `harden-until-attack-round-clean` is owed a clean round;
  the 2026-08-02 hindsight ruling says hardening rounds are over and a clean fresh-mutant round no
  longer gates new build. Different repos, possibly both true — nothing on record says so. **Which
  scope did the ruling cover?**
