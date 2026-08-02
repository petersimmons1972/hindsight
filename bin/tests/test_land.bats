#!/usr/bin/env bats
# Contract tests for bin/land.sh — the only sanctioned way to merge in this repo.
#
# require-real-ci.sh has existed since Phase 0 and gated NOTHING: it was
# exercised only by its own bats suite in CI. PLAN-TDD R7 says landing runs it,
# never a human reading of `gh pr view`. This suite pins the lander that makes
# R7 a mechanism instead of a sentence (Law 1: a rule becomes a mechanism or a
# principle, never a third thing).
#
# Every case injects a rollup with --json-file so no test touches the network.

setup() {
  LAND="$BATS_TEST_DIRNAME/../land.sh"
  FIXTURES="$BATS_TEST_DIRNAME/fixtures"
}

# ---- the gate actually gates ------------------------------------------------

@test "L1: refuses to merge when the rollup is all-queued (the FM-149 shape)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t11_many_queued_one_success.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

@test "L2: refuses when a required check has an EMPTY conclusion (renders blank, not red)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t17_queued_with_success_conclusion.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

@test "L3: refuses on a malformed rollup rather than treating unparseable as clean" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t14_malformed_truncated.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

@test "L4: refuses on a null rollup (zero checks reported is an ERROR, not a pass)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t15_null_rollup.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

# ---- and it passes the good case, or it is just a brake ---------------------

@test "L5: an all-success rollup PASSES the gate (both directions, not just refusal)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  [[ "$output" == *"GATE PASSED"* ]]
}

# ---- dry-run is the default -------------------------------------------------

@test "L6: without --merge it does NOT merge, even on a green rollup" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  [[ "$output" == *"DRY RUN"* ]]
  [[ "$output" != *"Merging"* ]]
}

@test "L7: the undo for a merge is printed BEFORE the merge, not after (Law 3)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  # Assert the actual recovery COMMANDS, not the word "UNDO". Asserting the word
  # alone let a mutant that deleted the whole journal header survive, because
  # the "=== END UNDO ===" trailer still matched.
  [[ "$output" == *"git revert"* ]]
  [[ "$output" == *"gh pr reopen"* ]]
  [[ "$output" == *"refs/heads/"* ]]
  # and it must precede the verdict line, not trail it
  undo_line=$(printf '%s\n' "$output" | grep -n "git revert" | head -1 | cut -d: -f1)
  verdict_line=$(printf '%s\n' "$output" | grep -n "GATE PASSED" | head -1 | cut -d: -f1)
  [ -n "$undo_line" ] && [ -n "$verdict_line" ]
  [ "$undo_line" -lt "$verdict_line" ]
}

# ---- the refusal must not be defeatable by argument order -------------------

@test "L8: --merge before the json-file still refuses on a red rollup" {
  run bash "$LAND" 99 --merge --json-file "$FIXTURES/t11_many_queued_one_success.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

# ---- usage ------------------------------------------------------------------

@test "L9: no PR number is a usage error, not a merge" {
  run bash "$LAND"
  [ "$status" -ne 0 ]
  [[ "$output" != *"Merging"* ]]
}
