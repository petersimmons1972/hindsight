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

## Standing debts

- **A real audition slot**, exempted three times — which is exactly how a gate stops meaning
  anything. Discharged by `plans/07` (#23). Never open one while a batch is in flight.
- **`cli-dispatch` covariate/probe leak**, third instance of that detector being wrong. File
  upstream and record the issue number here — an unfiled third instance of a wrong detector is
  itself the recurrence this project exists to measure.

## Open questions needing a ruling, not a decision

- **Round 7 scope.** The fleet record says `harden-until-attack-round-clean` is owed a clean round;
  the 2026-08-02 hindsight ruling says hardening rounds are over and a clean fresh-mutant round no
  longer gates new build. Different repos, possibly both true — nothing on record says so. **Which
  scope did the ruling cover?**
