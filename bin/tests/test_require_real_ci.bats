#!/usr/bin/env bats
# Tests for bin/require-real-ci.sh
#
# Contract: exit 0 ONLY if every required check has status == COMPLETED AND a
# non-empty conclusion AND that conclusion is SUCCESS. Empty rollup, missing
# required check, empty conclusion, non-SUCCESS conclusion, or QUEUED/IN_PROGRESS
# required checks must all exit non-zero and NAME the offending check.
#
# A non-required check being incomplete must NOT block (T7, the inversion guard).

setup() {
  SCRIPT="$BATS_TEST_DIRNAME/../require-real-ci.sh"
  FIXTURES="$BATS_TEST_DIRNAME/fixtures"
}

@test "T1: all required checks COMPLETED/SUCCESS -> exit 0" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
}

@test "T2: required check QUEUED with no conclusion -> exit 1, names the check" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t2_required_queued.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"guard"* ]]
}

@test "T3: required check COMPLETED but conclusion is empty -> exit 1 (the live hindsight case)" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t3_completed_empty_conclusion.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"guard"* ]]
}

@test "T4: empty rollup array -> exit 1, 'no checks reported'" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t4_empty_array.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"no checks reported"* ]]
}

@test "T5: required check COMPLETED/FAILURE, others SUCCESS -> exit 1" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t5_required_failure.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"guard"* ]]
  [[ "$output" == *"FAILURE"* ]]
}

@test "T6: only GitGuardian present, guard absent entirely -> exit 1" {
  run "$SCRIPT" 999 --json-file "$FIXTURES/t6_guard_absent.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"guard"* ]]
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
  run "$SCRIPT" 999 --json-file "$FIXTURES/t6_guard_absent.json" --required "guard,GitGuardian Security Checks"
  [ "$status" -ne 0 ]
  [[ "$output" == *"guard"* ]]
}
