#!/usr/bin/env bats
# S4.2 — ladder-rung-at-filing.
#
# Mirror test_disposition_at_filing.bats: require a failure-elimination ladder
# rung (or an infeasible reason) on every new filing. Do not weaken these to
# make an implementation pass.

setup() {
  export TMPDIR="$BATS_TEST_TMPDIR"
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  TOOL="$ROOT/bin/add-failure-mode.sh"
  WORK="$(mktemp -d)"
  CATALOG="$WORK/failure-modes.md"
  LEDGER="$WORK/id-ledger.txt"
  CORPUS_DIR="$WORK/corpus"
  CLUSTERS_FILE="$WORK/clusters.jsonl"
  CRITICALITY="$WORK/criticality.jsonl"

  cp "$ROOT/catalog/failure-modes.md" "$CATALOG"
  cp "$ROOT/catalog/id-ledger.txt" "$LEDGER"
  mkdir -p "$CORPUS_DIR"
  printf '%s\n' \
    '{"id":"known-1","instance":"a terminal SUCCESS was treated as proof the work finished","source_path":"fixture.jsonl"}' \
    >"$CORPUS_DIR/records.jsonl"
  printf '%s\n' '{"cluster_id":"c-001"}' >"$CLUSTERS_FILE"
}

teardown() {
  rm -rf "$WORK"
}

file_digest() {
  sha256sum "$1" | awk '{print $1}'
}

add_env() {
  env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" CLUSTERS="$CLUSTERS_FILE" "$@"
}

@test "omitting both ladder-rung flags exits nonzero naming --ladder-rung" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run add_env bash "$TOOL" -c A --disposition advisory \
    "missing ladder rung description" --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"--ladder-rung"* ]]
  [[ "$output" == *"structural"* ]]
  [[ "$output" == *"mechanical-gate"* ]]
  [[ "$output" == *"prose-rule"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  [ ! -f "$CRITICALITY" ]
}

@test "an invalid ladder-rung enum exits nonzero and names the closed set" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run add_env bash "$TOOL" -c A --disposition advisory --ladder-rung human-check \
    "invalid ladder rung description" --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"--ladder-rung"* ]]
  [[ "$output" == *"structural"* ]]
  [[ "$output" == *"mechanical-gate"* ]]
  [[ "$output" == *"prose-rule"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  [ ! -f "$CRITICALITY" ]
}

@test "filing with --ladder-rung prose-rule records ladder_rung in criticality.jsonl" {
  expected_id="$(python3 "$ROOT/guard/failure_mode_catalog_guard.py" --next-id "$CATALOG")"

  run add_env bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule \
    "prose rule ladder filing" --recurrence-of none

  [ "$status" -eq 0 ]
  [ -f "$CRITICALITY" ]
  run python3 -c "
import json, sys
path = sys.argv[1]
fm_id = sys.argv[2]
row = json.loads(open(path, encoding='utf-8').read().splitlines()[-1])
assert row['fm_id'] == fm_id, row
assert row['ladder_rung'] == 'prose-rule', row
assert 'ladder_rung_reason' not in row, row
" "$CRITICALITY" "$expected_id"
  [ "$status" -eq 0 ]
}

@test "filing with --ladder-rung-infeasible records infeasible plus reason" {
  expected_id="$(python3 "$ROOT/guard/failure_mode_catalog_guard.py" --next-id "$CATALOG")"

  run add_env bash "$TOOL" -c A --disposition advisory \
    --ladder-rung-infeasible "no structural fix or gate is nameable yet" \
    "infeasible ladder filing" --recurrence-of none

  [ "$status" -eq 0 ]
  [ -f "$CRITICALITY" ]
  run python3 -c "
import json, sys
path = sys.argv[1]
fm_id = sys.argv[2]
row = json.loads(open(path, encoding='utf-8').read().splitlines()[-1])
assert row['fm_id'] == fm_id, row
assert row['ladder_rung'] == 'infeasible', row
assert row['ladder_rung_reason'] == 'no structural fix or gate is nameable yet', row
" "$CRITICALITY" "$expected_id"
  [ "$status" -eq 0 ]
}

@test "providing both ladder-rung flags exits nonzero without writing" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run add_env bash "$TOOL" -c A --disposition advisory \
    --ladder-rung prose-rule \
    --ladder-rung-infeasible "should not also be set" \
    "both ladder flags" --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"exactly one"* ]] || [[ "$output" == *"--ladder-rung"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  [ ! -f "$CRITICALITY" ]
}

@test "empty --ladder-rung-infeasible reason exits nonzero" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run add_env bash "$TOOL" -c A --disposition advisory \
    --ladder-rung-infeasible "" \
    "empty infeasible reason" --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"--ladder-rung-infeasible"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  [ ! -f "$CRITICALITY" ]
}

@test "help text documents ladder-rung flags and the presence-not-truth limit" {
  run bash "$TOOL" -h
  [ "$status" -eq 0 ]
  [[ "$output" == *"--ladder-rung"* ]]
  [[ "$output" == *"--ladder-rung-infeasible"* ]]
  [[ "$output" == *"presence and shape"* ]]
  [[ "$output" == *"forgetting"* ]]
  [[ "$output" == *"evasion"* ]]
}
