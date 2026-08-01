# C7 — CI wiring

## Context

`.github/workflows/guard.yml` currently runs only the catalog guard and bats. The repo
has since grown a pipeline with its own validators, and none of them run in CI. An
uncovered validator is one nobody notices has stopped working — this repo's own history
includes a watchdog that reported OK through a four-day outage.

## Files
- **Modify** `.github/workflows/guard.yml`.
- **Create** `.github/workflows/` jobs as needed.

## Behaviour
On push and pull_request, on `runs-on: homelab-arc` (self-hosted; this is a private repo
and fleet convention is our own ARC runners), run:
1. `python3 guard/failure_mode_catalog_guard.py`
2. `python3 -m pytest guard/tests/ pipeline/tests/ -q`
3. `bats guard/tests/*.bats`
4. `python3 pipeline/reconcile_l1.py`
5. `python3 pipeline/validate_l1.py`   *(exists after C5 — guard with a file-existence
   check so this workflow is not broken while C5 is in flight)*
6. `python3 guard/failure_mode_catalog_guard.py --verify-enforcement` *(same treatment,
   arrives with C4)*

Steps must run independently so one failure does not mask the others, and each must
surface its own name in the job log. Do not chain them with `&&` into one step, and do
not pipe any of them — CI-17.

Install `bats` and `numpy` explicitly; do not assume the runner image has them.

## Acceptance (TDD)
Gate: `actionlint .github/workflows/*.yml && python3 guard/failure_mode_catalog_guard.py`
- `actionlint` clean.
- Every step named above present, each as its own step.
- No step reads an exit status through a pipe (grep the workflow to assert this and
  include that assertion in the gate if practical).
- Conditional guards present for the not-yet-existing validators so the workflow is
  green on today's tree.

## Constraints
Do not change repo settings, branch protection, or anything outside `.github/`.
Do not add third-party actions beyond `actions/checkout`.

## Out of scope
Making CI actually execute on GitHub (needs the remote, which the coordinator creates).

## Model
`--harness codex --effort medium`.
