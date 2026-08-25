# Gates: hindsight#170 — Design A bats producer/consumer (accidental silencing)

Scope: close the **accidental/careless** silencing of
`.github/workflows/guard.yml`'s "Run bin/ tool bats tests (require-real-ci, land)"
step. A PR that sets `if: false` on that step (and, for the coordinated form,
updates `INTENDED_WORKFLOW_SHA256`) must no longer leave the tools shard green
without a real TAP artifact that cross-checks live `@test` titles.

**Does NOT close** the fully-coordinated adversarial case (edit producer +
consumer + pin together) — that remains open as hindsight#171.

Worktree: the hindsight checkout under test (derive via `git rev-parse
--show-toplevel`; origin must be hindsight). Runnable transcription:
`leaf-hindsight170-check.sh` (never stage this `.md` as `--check-script`;
FM-440).

> Note: intended home is `ops-plans/drain-2026-08-21/gates/`. This lane could
> not write there (EACCES); files live under the hindsight worktree at the same
> relative path so the gate is still runnable and reviewable.

Negative controls measured on the **unfixed** tree at
`1d4b960` / workflow sha256 `7c0a8984…` (2026-08-25): see EVIDENCE under each
variant. Positive controls measured on the **fixed** tree after Design A lands.

Exit convention for the `.sh` transcription: `0` = all five PASS;
`1` = a mutant was not caught (or control not green); `2` = mutation did not
apply.

---

- [x] Mutation A — `if: false` alone on the bin-bats producer
  NEGATIVE (unfixed): producer skipped → tools job still exits 0 for that step;
  full pytest pin goes RED because workflow bytes moved without pin update
  (`pin_ok=False`). Job-level bats silence is real; pin catches the careless
  form only.
  POSITIVE (fixed): producer skipped → consumer runs →
  `verify_bats_report.py` fails on missing `.bats-report/report.tap` even if
  the pin were updated (consumer is independent of the pin).
  EVIDENCE: see `leaf-hindsight170-check.sh` output / `../evidence/h170-mutA.out`

- [x] Mutation B — `if: false` on producer + `INTENDED_WORKFLOW_SHA256` updated
  NEGATIVE (unfixed): `suite_green=True` (producer skipped, pin rewritten to
  match) — the original issue shape.
  POSITIVE (fixed): consumer fails on missing TAP. Separately, the
  offline-replay test's exact producer/consumer step-block pins also stay red
  after a sha256-only rewrite (stronger than the brief's sha256-only pin).
  EVIDENCE: `../evidence/h170-mutB.out`

- [x] Mutation C — TAP-stub forgery (count matches floor, titles fake)
  NEGATIVE (unfixed): no consumer → forged producer exits 0 → green when pin
  updated.
  POSITIVE (fixed): consumer title cross-ref RED on synthetic `fake test N`
  lines.
  EVIDENCE: `../evidence/h170-mutC.out`

- [x] Mutation D — consumer shard-gate replaced with `if: false`, OR
  `continue-on-error: true` added (shared `if: matrix.shard == 'tools'` is
  required structure; this variant mutates *away* from it)
  NEGATIVE (unfixed): no consumer exists — silence is the default
  (`suite_green=True`).
  POSITIVE (fixed): (D1) consumer `if: false` → exact step-block pin in
  `test_ci_offline_replay.py` RED and `INTENDED_WORKFLOW_SHA256` RED without a
  coincident pin rewrite; (D2) `continue-on-error: true` on consumer → same.
  A mutant that also rewrites the pin is #171, not this gate.
  EVIDENCE: `../evidence/h170-mutD.out`

- [x] Mutation E — producer piped without `pipefail` while the suite is red
  NEGATIVE (unfixed): `bats … | tee` without pipefail → step exit 0, no
  consumer → green when pin updated.
  POSITIVE (fixed): even if the step exit is swallowed, TAP retains `not ok`
  lines and/or `set -o pipefail` makes the producer fail; consumer also RED
  on `not ok`.
  EVIDENCE: `../evidence/h170-mutE.out`

## Residual gap (merge-blocking documentation)

This leaf closes accidental/careless coverage loss only. A PR that edits the
producer, the consumer, and `INTENDED_WORKFLOW_SHA256` together still defeats
the in-repo checks. Tracked by hindsight#171 (CODEOWNERS / external enforcer).
Do **not** use an unqualified `Closes #170` — state the residual gap and link
both #170 and #171.
