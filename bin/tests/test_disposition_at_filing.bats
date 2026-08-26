#!/usr/bin/env bats
# hindsight#116 — disposition-at-filing.
#
# These tests were written against the unmodified add-failure-mode.sh and
# shown to fail for the asserted reason before the flag existed. Do not
# weaken them to make an implementation pass.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  TOOL="$ROOT/bin/add-failure-mode.sh"
  REPORT="$ROOT/bin/report-guard-backlog.py"
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
  # CATALOG/CORPUS/CLUSTERS isolate every write from the real catalog and L2.
  env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" CLUSTERS="$CLUSTERS_FILE" "$@"
}

@test "an invalid disposition exits nonzero and names the closed set" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run add_env bash "$TOOL" -c A --disposition bogus --ladder-rung prose-rule \
    "invalid disposition description" --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"mechanize"* ]]
  [[ "$output" == *"brief-inject"* ]]
  [[ "$output" == *"advisory"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  [ ! -f "$CRITICALITY" ]
}

@test "a missing disposition exits nonzero and names the closed set" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run add_env bash "$TOOL" -c A \
    "missing disposition description" --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"disposition"* ]]
  [[ "$output" == *"mechanize"* ]]
  [[ "$output" == *"brief-inject"* ]]
  [[ "$output" == *"advisory"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  [ ! -f "$CRITICALITY" ]
}

@test "recurrence of a cluster force-promotes advisory to mechanize" {
  expected_id="$(python3 "$ROOT/guard/failure_mode_catalog_guard.py" --next-id "$CATALOG")"

  run add_env bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule \
    "recurring cluster force promote" --recurrence-of c-001

  [ "$status" -eq 0 ]
  [ -f "$CRITICALITY" ]
  [[ "$output" == *"disposition"* ]]
  [[ "$output" == *"mechanize"* ]]
  run python3 -c "
import json, sys
path = sys.argv[1]
fm_id = sys.argv[2]
row = json.loads(open(path, encoding='utf-8').read().splitlines()[-1])
assert row['fm_id'] == fm_id, row
assert row['disposition'] == 'mechanize', row
" "$CRITICALITY" "$expected_id"
  [ "$status" -eq 0 ]
}

@test "recurrence of none records the requested advisory disposition" {
  expected_id="$(python3 "$ROOT/guard/failure_mode_catalog_guard.py" --next-id "$CATALOG")"

  run add_env bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule \
    "novel advisory filing" --recurrence-of none

  [ "$status" -eq 0 ]
  run python3 -c "
import json, sys
path = sys.argv[1]
fm_id = sys.argv[2]
row = json.loads(open(path, encoding='utf-8').read().splitlines()[-1])
assert row['fm_id'] == fm_id, row
assert row['disposition'] == 'advisory', row
" "$CRITICALITY" "$expected_id"
  [ "$status" -eq 0 ]
}

@test "the guard backlog lists mechanize+null and excludes mechanize+enforced" {
  cat >"$CRITICALITY" <<'JSONL'
{"fm_id":"FM-001","disposition":"mechanize"}
{"fm_id":"FM-002","disposition":"mechanize"}
{"fm_id":"FM-003","disposition":"advisory"}
{"fm_id":"FM-004","tier":"HIGH","generality":"NARROW"}
JSONL
  mkdir -p "$WORK/l1"
  cat >"$WORK/l1/records.jsonl" <<'JSONL'
{"id":"hc-FM-001","enforcement":null,"instance":"unenforced mechanize","source_path":"fixture","auto":"judgment"}
{"id":"hc-FM-002","enforcement":{"file":"guard/test_enforced.py","kind":"test"},"instance":"enforced mechanize","source_path":"fixture","auto":"machine"}
{"id":"hc-FM-003","enforcement":null,"instance":"unenforced advisory","source_path":"fixture","auto":"judgment"}
{"id":"hc-FM-004","enforcement":null,"instance":"unenforced no disposition","source_path":"fixture","auto":"judgment"}
JSONL

  run python3 "$REPORT" --criticality "$CRITICALITY" --l1 "$WORK/l1"

  [ "$status" -eq 0 ]
  [[ "$output" == *"FM-001"* ]]
  ! [[ "$output" == *"FM-002"* ]]
  ! [[ "$output" == *"FM-003"* ]]
  ! [[ "$output" == *"FM-004"* ]]
}
