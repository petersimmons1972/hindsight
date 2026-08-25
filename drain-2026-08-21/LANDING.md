## hindsight#170 Design A — accidental bats silencing guard

Closes the **accidental/careless** case of silencing
`Run bin/ tool bats tests (require-real-ci, land)` via `if: false` (optionally
with a coincident `INTENDED_WORKFLOW_SHA256` rewrite). The tools shard now
emits a TAP artifact and a same-job consumer
(`bin/verify_bats_report.py`) fails loudly if the report is missing, empty,
under-count, failing, or title-forged against live `bin/tests/*.bats` `@test`
strings.

**Does not close** the fully-coordinated adversarial case (edit producer +
consumer + pin together). That remains open as hindsight#171 pending the
founder-level CODEOWNERS/external-enforcer decision. Link both #170 and #171;
do **not** use an unqualified `Closes #170`.

### Changes
- `.github/workflows/guard.yml`: producer writes `.bats-report/report.tap` with
  `set -o pipefail`; new consumer step (same `if: matrix.shard == 'tools'`, no
  `continue-on-error`)
- `bin/verify_bats_report.py`: live floor + title cross-ref + not-ok reject
- `guard/tests/test_ci_offline_replay.py`: pin updated; exact-pins both step blocks
- `bin/tests/test_verify_bats_report.py`: adversarial suite
- `drain-2026-08-21/gates/leaf-hindsight170.{md,check.sh}` + evidence: 5-variant
  mutation gate (ops-plans path was EACCES from this lane; authored in-repo at
  the same relative path)

### Measured
- Negatives on unfixed tree: B/C/E green with pin rewrite; D N/A (no consumer)
- Positives on fixed tree: A–E all caught (`leaf-hindsight170-check.sh` exit 0)
- Suite: catalog guard OK; pytest 609 passed; bats guard/tests 10/10; workflow
  contract OK; live `@test` floor 300 (not hardcoded)
