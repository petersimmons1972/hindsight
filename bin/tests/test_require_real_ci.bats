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

@test "T25: duplicate 'guard', COMPLETED/SUCCESS FIRST then QUEUED/null LAST -> exit 2 (good-before-bad: pins matches[:1] truncation, every other duplicate fixture puts the bad entry first)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t25_duplicate_guard_success_then_queued.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
}

@test "T26: duplicate 'guard', COMPLETED/SUCCESS FIRST then COMPLETED/FAILURE LAST -> exit 2 (good-before-bad, completed-bad variant)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t26_duplicate_guard_success_then_failure.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
  [[ "$output" == *"FAILURE"* ]]
}

@test "T27: multi-name --required, FIRST name SUCCESS but SECOND name FAILURE -> exit 2 (pins the required[:1] truncation; the only prior multi-name failure fails on the first name)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t27_second_required_name_fails.json" --required "guard,GitGuardian Security Checks"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'GitGuardian Security Checks'"* ]]
  [[ "$output" == *"FAILURE"* ]]
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

@test "naive timestamp -> elapsed/window diagnostic is still rendered (pins the tzinfo-normalization fix itself, not just the exit code): deleting 'if started.tzinfo is None: started = started.replace(tzinfo=timezone.utc)' makes elapsed_minutes() return None via the try/except, silently dropping this message while status stays 2" {
  NOW_NAIVE="$(date -u -d '-2 minutes' +%Y-%m-%dT%H:%M:%S)"
  DYN="$BATS_TEST_TMPDIR/dyn_naive_elapsed_diagnostic.json"
  cat > "$DYN" <<EOF
{"statusCheckRollup":[{"__typename":"CheckRun","name":"guard","status":"QUEUED","conclusion":null,"startedAt":"$NOW_NAIVE","completedAt":null}]}
EOF
  run "$SCRIPT" 999 --json-file "$DYN" --max-wait-minutes 60
  [ "$status" -eq 2 ]
  [[ "$output" == *"m elapsed, within --max-wait-minutes=60: still starting up"* ]]
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

# ---- F2 (round 5): four unpinned mutation-surviving behaviours ------------

@test "M31 pin: bad 'guard' sibling lacking __typename is still evaluated (entry-selection must never drop entries on an incidental field) -> exit 2, names FAILURE" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t29_bad_sibling_no_typename.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
  [[ "$output" == *"FAILURE"* ]]
}

@test "M27 pin: lowercase REST-shaped status='completed'/conclusion='success' -> exit 2 (exact-case contract on status; only literal 'COMPLETED' passes)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t30_rest_shaped_lowercase_case_exact.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard' is not complete (status='completed')"* ]]
}

@test "M28 pin (isolated from M27): status='COMPLETED' exact, conclusion='success' lowercase -> exit 2 (exact-case contract on conclusion specifically; t30 alone shares its status-check cause with M27 and does not isolate this one)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t31_completed_lowercase_conclusion.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"concluded 'success', not SUCCESS"* ]]
}

@test "M42 pin: python3 evaluator exits nonzero with EMPTY stdout -> script relays that exit code verbatim, never silently downgrades to 0" {
  FAKE_BIN="$BATS_TEST_TMPDIR/fakebin_m42"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/python3" <<'EOF'
#!/usr/bin/env bash
# Distinguish the two python3 invocations by ARGUMENT COUNT, not by
# grep-matching script text -- the real script's source itself now mentions
# "json.load(sys.stdin)" in a comment, which would false-match a text-based
# discriminator. The bash-side JSON pre-validation call is always exactly
# `python3 -c '<fixed short snippet>'` (2 args); the main evaluator call is
# always `python3 -c "$PY_SCRIPT" "$MAX_WAIT_MINUTES" "${TRIMMED_REQUIRED[@]}"`
# (4+ args: -c, script, max-wait, and at least one required name).
if [ "$#" -le 2 ]; then
  cat >/dev/null
  exit 0
fi
# Simulate the main evaluator failing with NO stdout output at all but a
# real, documented-range nonzero exit code (2) -- pins that require-real-ci.sh's
# final relay line surfaces this exit code verbatim. A mutant final line
# `if [ -n "$PY_OUT" ]; then exit "$PY_RC"; else exit 0; fi` takes the empty
# branch here and would wrongly exit 0.
cat >/dev/null
exit 2
EOF
  chmod +x "$FAKE_BIN/python3"
  PATH="$FAKE_BIN:$PATH" run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 2 ]
}

# ---- F1 (round 5): oversized rollup must not silently fail to run ---------
# Linux caps a single argv element at MAX_ARG_STRLEN (131072 bytes), independent
# of ARG_MAX. Passing RAW_JSON as a python3 argv string makes execve() itself
# fail before python3 starts once the rollup crosses that: the shell prints
# "Argument list too long" and the exit code is 126 -- undocumented, and no
# PASS:/FAIL: line reaches stdout. This must not happen: the gate must still
# evaluate every entry and exit 2 on the bad one, however large the rollup.
@test "F1: >128KB rollup (465 gh-shaped entries, last one QUEUED/null) -> exit 2, names 'guard', never exit 126" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t28_oversized_rollup_argv_limit.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"'guard'"* ]]
  [[ "$output" == *"FAIL:"* ]]
}

@test "error path: gh CLI fetch failure (no --json-file, gh exits nonzero) -> exit 1, names the gh failure specifically (M41: pins the RC!=0 branch itself, not just that SOME exit-1 path was hit -- a mutated 'if [ \$RC -ne 0 ]' -> 'if false' survives on status alone, because the captured stderr text then separately fails the JSON pre-check and also produces exit 1)" {
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
  [[ "$output" == *"gh pr view failed"* ]]
}

# ---- F3 (round 6): mutation survivors — the absent-KEY paths ---------------
# Every pre-existing fixture spells `"conclusion": null` / `"status": ...`
# EXPLICITLY, so `entry.get("conclusion")` and `entry.get("status")` were only
# ever exercised on keys that are PRESENT. A mutant supplying a default —
# `entry.get("conclusion", "SUCCESS")` / `entry.get("status", "COMPLETED")` —
# is therefore invisible to the whole suite, while turning a check that
# reported nothing at all into a green one. That is FM-149/FM-150 verbatim:
# a check with no conclusion is RED, never green.

@test "S1 pin: 'conclusion' key ABSENT (not null) on a COMPLETED required check -> exit 2, never defaults to SUCCESS" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t32_conclusion_key_absent.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"required check 'guard' is COMPLETED but has an empty/missing conclusion"* ]]
}

@test "S2 pin: 'status' key ABSENT on a required check -> exit 2, never defaults to COMPLETED" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t33_status_key_absent.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"required check 'guard' is not complete (status=None)"* ]]
}

# ---- F3: an empty allowlist must never pass vacuously ---------------------
# With nothing required, "every required check succeeded" is vacuously true and
# the gate reports PASS on a rollup that is entirely QUEUED. The allowlist
# checks are the only thing standing between `--required ""` and a green
# verdict on a red PR.

@test "S3 pin: --required '' on an all-QUEUED rollup -> usage error, never a vacuous PASS" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t2_required_queued.json" --required ""
  [ "$status" -eq 1 ]
  [[ "$output" == *"empty allowlist"* ]]
  [[ "$output" != *"PASS:"* ]]
}

@test "S4 pin: --required '  ' (whitespace only) on an all-QUEUED rollup -> rejected, not silently skipped" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t2_required_queued.json" --required "  "
  [ "$status" -eq 1 ]
  [[ "$output" == *"empty check name"* ]]
  [[ "$output" != *"PASS:"* ]]
}

@test "S3b pin: a whitespace-only name among real ones ('guard, ,x') is rejected too" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json" --required "guard, ,GitGuardian Security Checks"
  [ "$status" -eq 1 ]
  [[ "$output" == *"empty check name"* ]]
  [[ "$output" != *"PASS:"* ]]
}

# ---- F3: the undocumented-exit-code guard itself --------------------------
# The M42 pin only simulates python3 exiting 2 — an IN-RANGE code — so the
# out-of-range branch this block exists for (the exit-126 argv-limit incident:
# "the gate silently did not run") was never entered by any test. An evaluator
# crash means "I could not verify", which must never relay as "it is fine".

_fake_python3_exiting() {  # $1 = exit code the evaluator should simulate
  FAKE_BIN="$BATS_TEST_TMPDIR/fakebin_s5_$1"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/python3" <<EOF
#!/usr/bin/env bash
# Same discriminator as the M42 pin: the bash-side JSON pre-validation call is
# \`python3 -c '<snippet>'\` (2 args); the real evaluator gets 4+.
if [ "\$#" -le 2 ]; then
  cat >/dev/null
  exit 0
fi
cat >/dev/null
exit $1
EOF
  chmod +x "$FAKE_BIN/python3"
}

@test "S5/S10 pin: python3 evaluator exits 1 (undocumented, out of the 0/2 contract) -> exit 2 and says so, never 0" {
  _fake_python3_exiting 1
  PATH="$FAKE_BIN:$PATH" run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"undocumented code 1"* ]]
  [[ "$output" != *"PASS:"* ]]
}

@test "S10 pin: python3 evaluator exits 126 (the FM-149 argv-limit code) -> exit 2, labelled, never leaked verbatim" {
  _fake_python3_exiting 126
  PATH="$FAKE_BIN:$PATH" run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"undocumented code 126"* ]]
  [[ "$output" != *"PASS:"* ]]
}

@test "S11 pin: --max-wait-minutes abc is rejected as a usage error (exit 1) before it can reach int() in the evaluator" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json" --max-wait-minutes abc
  [ "$status" -eq 1 ]
  [[ "$output" == *"--max-wait-minutes must be a non-negative integer, got: abc"* ]]
}

# ---- F5: how a required check NAME is matched was entirely unpinned ---------
# An independent re-sweep with fresh mutants found three separate mutations of
# the one name comparison that each turn a red PR green while passing all 79
# tests. GitHub check names are case-sensitive, so a renamed or re-cased job
# must NOT satisfy a required gate -- otherwise a check that never ran reports
# green and land.sh merges on it. That is FM-149's class exactly.

@test "R1 pin: a rollup entry differing only in CASE does not satisfy the required name" {
  run bash "$SCRIPT" 999 --json-file "$FIXTURES/t34_name_case_mismatch.json" --required guard
  [ "$status" -eq 2 ]
  [[ "$output" == *"absent from the rollup entirely"* ]]
  [[ "$output" != *"PASS:"* ]]
}

@test "R2 pin: a rollup entry padded with whitespace does not satisfy the required name" {
  # The script trims the REQUIRED names on purpose; it must not trim the ROLLUP
  # names. Nothing tested that asymmetry, so a mutant adding .strip() to the
  # rollup side passed 79/79.
  run bash "$SCRIPT" 999 --json-file "$FIXTURES/t35_name_whitespace_padded.json" --required guard
  [ "$status" -eq 2 ]
  [[ "$output" == *"absent from the rollup entirely"* ]]
  [[ "$output" != *"PASS:"* ]]
}

@test "R3 pin: the exact name still matches (both directions, so R1/R2 cannot be satisfied by refusing everything)" {
  run bash "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json" --required guard
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS:"* ]]
}

# ---- F6: remaining ci-gate mutation survivors -----------------------------

@test "R11 pin: lowercase legacy StatusContext state is not SUCCESS" {
  legacy="$BATS_TEST_TMPDIR/lowercase_legacy_state.json"
  printf '%s\n' '{"statusCheckRollup":[{"__typename":"StatusContext","context":"guard","state":"success"}]}' > "$legacy"
  run "$SCRIPT" 999 --json-file "$legacy"
  [ "$status" -eq 2 ]
  [[ "$output" == *"legacy status context) is not SUCCESS (state='success')"* ]]
}

@test "R6 pin: a second positional argument is a usage error, never a replacement PR" {
  run "$SCRIPT" 123 456 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 1 ]
  [[ "$output" == *"unexpected extra argument: 456"* ]]
}

@test "R8 pin: contract FAIL verdict stays on stdout, never becomes an evaluator crash" {
  run bash -c '"$1" "$2" --json-file "$3" 2>/dev/null' _ "$SCRIPT" 999 "$FIXTURES/t2_required_queued.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"FAIL: required check 'guard' is not complete"* ]]
  [[ "$output" != *"undocumented code"* ]]
}

@test "R3 pin: exactly-at-window check is reported exceeded, not still starting up" {
  # The evaluator reads its clock directly. Freeze that clock in a wrapper so
  # this probes the equality boundary instead of a nearby, flaky wall-clock
  # value; the real interpreter still evaluates the production program.
  fixed_time="2026-08-01T12:00:00+00:00"
  boundary="$BATS_TEST_TMPDIR/exact_wait_boundary.json"
  printf '%s\n' '{"statusCheckRollup":[{"name":"guard","status":"QUEUED","conclusion":null,"startedAt":"2026-08-01T11:45:00Z"}]}' > "$boundary"
  fake_bin="$BATS_TEST_TMPDIR/fixed-clock-bin"
  mkdir -p "$fake_bin"
  cat > "$fake_bin/python3" <<EOF
#!/usr/bin/env bash
if [ "\$#" -le 2 ]; then
  exec /usr/bin/python3 "\$@"
fi
script="\$2"
script="\$(printf '%s' "\$script" | sed "s|now = datetime.now(timezone.utc)|now = datetime.fromisoformat('$fixed_time')|")"
exec /usr/bin/python3 -c "\$script" "\${@:3}"
EOF
  chmod +x "$fake_bin/python3"
  PATH="$fake_bin:$PATH" run "$SCRIPT" 999 --json-file "$boundary" --max-wait-minutes 15
  [ "$status" -eq 2 ]
  [[ "$output" == *"15.0m elapsed, exceeded --max-wait-minutes=15"* ]]
  [[ "$output" != *"still starting up"* ]]
}

@test "R4 pin: createdAt supplies the stuck-check elapsed diagnostic when startedAt is absent" {
  created_only="$BATS_TEST_TMPDIR/created_at_only.json"
  printf '%s\n' '{"statusCheckRollup":[{"name":"guard","status":"QUEUED","conclusion":null,"createdAt":"2020-01-01T00:00:00Z"}]}' > "$created_only"
  run "$SCRIPT" 999 --json-file "$created_only" --max-wait-minutes 15
  [ "$status" -eq 2 ]
  [[ "$output" == *"m elapsed, exceeded --max-wait-minutes=15"* ]]
}

@test "R5 pin: empty --max-wait-minutes is a documented usage error" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json" --max-wait-minutes ''
  [ "$status" -eq 1 ]
  [[ "$output" == *"must be a non-negative integer, got:"* ]]
  [[ "$output" != *"undocumented code"* ]]
}

@test "R7 pin: an empty JSON file reports the explicit no-JSON guard" {
  empty="$BATS_TEST_TMPDIR/empty_rollup.json"
  : > "$empty"
  run "$SCRIPT" 999 --json-file "$empty"
  [ "$status" -eq 1 ]
  [[ "$output" == *"no JSON produced (empty --json-file or empty gh response)"* ]]
}

@test "R10 pin: non-dict rollup siblings are ignored rather than crashing evaluation" {
  mixed="$BATS_TEST_TMPDIR/null_sibling.json"
  printf '%s\n' '{"statusCheckRollup":[null,{"name":"guard","status":"COMPLETED","conclusion":"SUCCESS"}]}' > "$mixed"
  run "$SCRIPT" 999 --json-file "$mixed"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS: all required checks (guard)"* ]]
  [[ "$output" != *"Traceback"* ]]
}

@test "R15 pin: exactly two duplicate names report their failed-entry count" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t26_duplicate_guard_success_then_failure.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"1 of 2 entries named 'guard' failed the contract"* ]]
}
