# INVARIANTS — the canonical blocks

Every file under `plans/` copies the two blocks below **verbatim**, as its §5 and §6.
`bin/check-plan-preamble.sh` asserts they are byte-identical to this file. Decomposition without
that lint recreates this repo's origin story: two copies of a governance artifact, both edited,
both drifting.

Change a rule **here**, then re-run the lint and update every plan in the same commit.

---

## §5 NON-NEGOTIABLES

Each is drawn from a measured failure in this repo. The Origin column is what stops them being
re-argued by someone who was not there.

| # | Rule | Origin |
|---|---|---|
| R1 | **Red first, and prove the red.** Every new test must be demonstrated failing against the pre-change tree before the implementation exists. A test that passes on the unfixed tree is not evidence — it is CI-18. | C6b shipped `baseline: guard 0` |
| R2 | **Both directions, always.** Every guard rule gets a test that it *fires on the bad case* and a test that it *stays silent on the good case*. A guard that rejects everything gets disabled within a day, and then you have neither. | `lesson-a-fix-can-invert-the-error`; three-laws "honest cost" |
| R3 | **Ground-truth fixtures are coordinator-authored**, committed before the packet is dispatched. An implementer may add tests; it may not author the acceptance fixture. | `lesson-validators-must-pass-ground-truth`; C1d (one agent authored both the markers and the sentences grading them) |
| R4 | **Empty / zero / missing input must FAIL LOUD**, never pass silently. Applies to every counter, parser and matcher. **The two zeros must be distinguishable**: "measured, found none" and "never measured" may not render the same. | CI-1, FM-150, fleet#152 `total == 0` |
| R5 | **No exit status through a pipe.** `${PIPESTATUS[0]}` or no pipe. | CI-17 |
| R6 | **Every tool that writes emits an undo journal before writing**, and exposes `--undo`. No implicit default target; an unrecognised argument aborts rather than falling back. | FM-146/147/148, Law 3 |
| R7 | **A green check is not evidence until its conclusion is non-empty.** Landing runs `bin/require-real-ci.sh`, never a human reading of `gh pr view`. | FM-149/150 |
| R8 | **Dispatches are serial in this repo.** `.dispatch/covariates` and `.dispatch/probes` are not pruned by `checkout_state_snapshot`, so concurrent dispatches cross-trip each other's leak detectors. Do not write to the shared checkout while one runs. | known env bug, 3rd instance; FM-162 |
| R9 | **No `--apply` of the sync tool against anything real** without founder sign-off. Dry-run plus temp-repo unit tests only. | 2026-08-01 incident: wrote into 11 live repos |
| FM-154 | **A fix that reaches green by editing the data its check reads is not a fix.** Re-run the check with the data reverted; if the verdict flips, the fix is in the data. | PR #8 manufactured its green |
| FM-155 | **A floor or a count must measure units of work actually PERFORMED, never units merely PRESENT.** A threshold satisfied by a tautological element enforces nothing. | C4c root that always resolves and verifies nothing |
| FM-158 | **A mechanism verified only in the developer's environment is unverified in the environment that gates.** Every mutation runs in BOTH environments; a result from one environment is not a result. | C4e ratchet was a no-op under CI's shallow checkout |

---

## §6 PROHIBITIONS

- **NEVER delete a catalog row, an L1 record, or an `id-ledger.txt` line to satisfy a validator.**
  If a row violates a rule, renumber or fix the rule — the rule is younger than the data. This is
  how eleven real failure modes (`FM-REC-01..11`) were nearly lost.
- **NEVER regenerate `catalog/id-ledger.txt`.** A regenerated baseline cannot detect a row that is
  already missing, which is the entire point of having one. Restore it from git instead.
- **NEVER hand-assign a failure-mode ID.** Use `bin/add-failure-mode.sh`, which sources the next ID
  from the guard.
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to
  fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER relax, weaken, delete or skip an existing test to make a change pass.** Replace it and
  assert the new contract in both directions, recording the old test's reasoning in the new test's
  docstring so the reasoning outlives the rule.
- **NEVER edit any file under `conf/` to make a check pass.** Editing scope-defining config to
  reach green is a documented attack on this repo's own tooling — the "config layer" of the
  manufactured-green ladder.
- **NEVER edit any file under `pipeline/L1/` to make a check pass.** That is FM-154, and it is the
  defect that produced this campaign's headline finding.
- **NEVER read a command's exit status through a pipe** (CI-17).
- **NEVER modify a file not listed in your plan's §7.** If the work appears to require one, STOP
  and report rather than widening scope.
- **Do not merge, push to `main`, or open a PR** unless your plan says so explicitly.

---

## Why "VOID, never relax"

When measurement shows an assertion cannot be satisfied by any implementation, **delete the
assertion and record why** — do not weaken it until it passes. A test no implementation can meet
reads as coverage while providing none, which is strictly worse than its absence. Applied to V7
(the reworded-duplicate gate) and to the `fail-silent-gate` family assertion.

Its converse: when a measured ceiling is real, **pin it as an exact-match assertion** (`0/35`,
`1/77`, "exactly 4 distinct clusters") rather than a `>=` floor, so drift forces conscious
re-measurement instead of passing quietly.
