#!/usr/bin/env bats
# Tests for bin/require-real-ci.sh
#
# Contract: exit 0 ONLY if every required check name is present at least once
# in the rollup, AND every entry bearing that name has status == COMPLETED
# with a non-empty conclusion == SUCCESS. Duplicate names are the NORMAL case
# in this repo (multiple CheckRun entries can share a name) — the fix must
# never collapse duplicates into "any one entry with this name passing wins".
#
# Exit codes: 1 = usage error, 2 = gate/contract failure.

setup() {
  SCRIPT="$BATS_TEST_DIRNAME/../require-real-ci.sh"
  FIXTURES="$BATS_TEST_DIRNAME/fixtures"
}

# ---- core contract -------------------------------------------------------

@test "T1: all required checks COMPLETED/SUCCESS -> exit 0" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
}

@test "T2: required check QUEUED with no conclusion -> exit 2, names the check" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t2_required_queued.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

@test "T3a (defensive, not GH-observed): COMPLETED with empty conclusion -> exit 2" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t3a_completed_empty_conclusion_defensive.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

@test "T3b (actual FM-150 shape): IN_PROGRESS with empty conclusion -> exit 2" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t3b_in_progress_empty_conclusion_fm150.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

@test "T4: empty rollup array -> exit 2, 'no checks reported'" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t4_empty_array.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"no checks reported"* ]]
}

@test "T5: required check COMPLETED/FAILURE, others SUCCESS -> exit 2" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t5_required_failure.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
  [[ "$output" == *"FAILURE"* ]]
}

@test "T6: required check absent entirely from rollup -> exit 2, exact reason (not just path match)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t6_required_check_absent.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"required check 'guard' is absent from the rollup entirely"* ]]
}

@test "T7: non-required check QUEUED but all required COMPLETED/SUCCESS -> exit 0 (inversion guard)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t7_non_required_queued.json" --required guard
  [ "$status" -eq 0 ]
}

@test "custom --required list is honored (comma-separated allowlist)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json" --required "guard,GitGuardian Security Checks"
  [ "$status" -eq 0 ]
}

@test "custom --required list still fails when one of the named checks is absent" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t6_required_check_absent.json" --required "guard,GitGuardian Security Checks"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

# ---- duplicate-name handling (THE confirmed HIGH defect) -----------------

@test "T8: duplicate 'guard' entries, ALL SUCCESS -> exit 0 (real PR #6 shape; duplicates are normal)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t8_duplicate_guard_all_success.json"
  [ "$status" -eq 0 ]
}

@test "T9: duplicate 'guard', COMPLETED/FAILURE first then COMPLETED/SUCCESS last -> exit 2 (genuinely discriminating: pre-repair last-wins dedupe falsely PASSes this)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t9_duplicate_guard_failure_then_success.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
  [[ "$output" == *"FAILURE"* ]]
}

@test "T10: duplicate 'guard', QUEUED listed first then SUCCESS -> exit 2 (literal FM-149/last-wins repro)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t10_duplicate_guard_mixed_queued_first.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

@test "T11: 10 QUEUED 'guard' entries + 1 SUCCESS 'guard' entry -> exit 2 (verbatim FM-149 catalog shape)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t11_many_queued_one_success.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

# ---- legacy StatusContext (context/state) shape ---------------------------

@test "T12: legacy StatusContext with state=SUCCESS -> exit 0 (must not be permanently reported RED)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t12_legacy_status_context_success.json"
  [ "$status" -eq 0 ]
}

@test "T13: legacy StatusContext with state=PENDING -> exit 2, names the check" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t13_legacy_status_context_pending.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

# ---- --max-wait-minutes window (distinguishes "not started" from "stuck") -

@test "T14: required check QUEUED, elapsed well within --max-wait-minutes -> exit 2 but message says still within window" {
  NOW_MINUS_2M="$(date -u -d '-2 minutes' +%Y-%m-%dT%H:%M:%SZ)"
  DYN="$BATS_TEST_TMPDIR/dyn_within_window.json"
  cat > "$DYN" <<EOF
{"statusCheckRollup":[{"__typename":"CheckRun","name":"guard","status":"QUEUED","conclusion":null,"startedAt":"$NOW_MINUS_2M","completedAt":null}]}
EOF
  run "$SCRIPT" 999 --json-file "$DYN" --max-wait-minutes 60
  [ "$status" -eq 2 ]
  [[ "$output" == *"within"* ]]
  [[ "$output" != *"exceeded"* ]]
}

@test "T15: required check QUEUED, elapsed beyond --max-wait-minutes -> exit 2, message flags it as stuck/exceeded" {
  NOW_MINUS_500M="$(date -u -d '-500 minutes' +%Y-%m-%dT%H:%M:%SZ)"
  DYN="$BATS_TEST_TMPDIR/dyn_exceeded_window.json"
  cat > "$DYN" <<EOF
{"statusCheckRollup":[{"__typename":"CheckRun","name":"guard","status":"QUEUED","conclusion":null,"startedAt":"$NOW_MINUS_500M","completedAt":null}]}
EOF
  run "$SCRIPT" 999 --json-file "$DYN" --max-wait-minutes 15
  [ "$status" -eq 2 ]
  [[ "$output" == *"exceeded"* ]]
}

@test "T16: status=QUEUED with conclusion already SUCCESS -> exit 2 (pins the status!=COMPLETED branch specifically, isolated from the empty-conclusion branch)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t17_queued_with_success_conclusion.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

# ---- naive (timezone-less) timestamp handling (round-3 HIGH regression) ---
# elapsed_minutes() must never let a naive/unparseable startedAt escape the
# guarded path and downgrade a gate failure (exit 2) to a usage error (exit
# 1) -- that's the one exit code the tool documents as "skip the gate".

@test "naive timestamp (no timezone, T-separated) -> still exit 2, never exit 1" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t18_naive_timestamp_no_tz.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

@test "naive timestamp (date only) -> still exit 2, never exit 1" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t19_naive_timestamp_date_only.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

@test "naive timestamp (space-separated, no timezone) -> still exit 2, never exit 1" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t20_naive_timestamp_space_separated.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

# ---- mutation-bar fixtures: status/conclusion strictness -------------------

@test "IN_PROGRESS with conclusion=SUCCESS -> exit 2 (FM-150-observed status; pins exact COMPLETED match, not an allowlist)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t21_in_progress_success_conclusion.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard' is not complete (status='IN_PROGRESS')"* ]]
}

@test "conclusion=CANCELLED -> exit 2 (only SUCCESS may pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t22_conclusion_cancelled.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'CANCELLED', not SUCCESS"* ]]
}

@test "conclusion=SKIPPED -> exit 2 (only SUCCESS may pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t22_conclusion_skipped.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'SKIPPED', not SUCCESS"* ]]
}

@test "conclusion=NEUTRAL -> exit 2 (only SUCCESS may pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t22_conclusion_neutral.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'NEUTRAL', not SUCCESS"* ]]
}

@test "conclusion=STARTUP_FAILURE -> exit 2 (only SUCCESS may pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t22_conclusion_startup_failure.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'STARTUP_FAILURE', not SUCCESS"* ]]
}

@test "conclusion=TIMED_OUT -> exit 2 (only SUCCESS may pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t22_conclusion_timed_out.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'TIMED_OUT', not SUCCESS"* ]]
}

@test "conclusion=ACTION_REQUIRED -> exit 2 (only SUCCESS may pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t22_conclusion_action_required.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'ACTION_REQUIRED', not SUCCESS"* ]]
}

@test "conclusion=STALE -> exit 2 (only SUCCESS may pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t22_conclusion_stale.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'STALE', not SUCCESS"* ]]
}

@test "required check present with no status/conclusion/state fields -> exit 2, FAIL LOUD (not a silent pass)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t23_unrecognized_entry_shape.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard' has an unrecognized entry shape"* ]]
}

@test "exact required-name matching: 'guard-extra' present does not satisfy required 'guard' -> exit 2, absent" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t24_prefix_name_no_exact_match.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"required check 'guard' is absent from the rollup entirely"* ]]
}

@test "FM-150 diagnostic message is pinned verbatim (COMPLETED + empty conclusion), not just the exit code" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t3a_completed_empty_conclusion_defensive.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"required check 'guard' is COMPLETED but has an empty/missing conclusion"* ]]
}

# ---- exit-code contract, pinned -------------------------------------------

@test "exit-code contract: missing <pr-number> is a usage error -> exit exactly 1" {
  run "$SCRIPT" --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 1 ]
}

@test "exit-code contract: unknown option is a usage error -> exit exactly 1" {
  run "$SCRIPT" 999 --bogus-flag foo --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 1 ]
}

@test "exit-code contract: --json-file pointing at a nonexistent path -> exit exactly 1" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/does_not_exist.json"
  [ "$status" -eq 1 ]
}

@test "exit-code contract: gate/contract failure -> exit exactly 2, never 1" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t5_required_failure.json"
  [ "$status" -eq 2 ]
}

# ---- error paths: malformed / missing / wrong-shape input ------------------

@test "error path: malformed/truncated JSON -> exit 1, message says not valid JSON" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t14_malformed_truncated.json"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not valid JSON"* ]]
}

@test "error path: statusCheckRollup is null -> exit 2, 'no checks reported'" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t15_null_rollup.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"no checks reported"* ]]
}

@test "error path: statusCheckRollup is not a list (an object) -> exit 2, 'no checks reported'" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t16_non_list_rollup.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"no checks reported"* ]]
}

@test "error path: gh CLI fetch failure (no --json-file, gh exits nonzero) -> exit 1" {
  FAKE_BIN="$BATS_TEST_TMPDIR/fakebin"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/gh" <<'EOF'
#!/usr/bin/env bash
echo "HTTP 404: Not Found (owner/repo not found)" >&2
exit 1
EOF
  chmod +x "$FAKE_BIN/gh"
  PATH="$FAKE_BIN:$PATH" run "$SCRIPT" 999
  [ "$status" -eq 1 ]
}
