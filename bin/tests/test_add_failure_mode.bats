#!/usr/bin/env bats

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  TOOL="$ROOT/bin/add-failure-mode.sh"
  WORK="$(mktemp -d)"
  CATALOG="$WORK/failure-modes.md"
  LEDGER="$WORK/id-ledger.txt"
  CORPUS_DIR="$WORK/corpus"

  cp "$ROOT/catalog/failure-modes.md" "$CATALOG"
  cp "$ROOT/catalog/id-ledger.txt" "$LEDGER"
  mkdir -p "$CORPUS_DIR"
  printf '%s\n' \
    '{"id":"known-1","instance":"a terminal SUCCESS was treated as proof the work finished","source_path":"fixture.jsonl"}' \
    >"$CORPUS_DIR/records.jsonl"
}

teardown() {
  chmod u+rwx "$WORK/unreadable" 2>/dev/null || true
  rm -rf "$WORK"
}

file_digest() {
  sha256sum "$1" | awk '{print $1}'
}

@test "missing recurrence decision prints advisory candidates and writes nothing" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "a terminal SUCCESS was treated as proof the work finished"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Candidates for human review. This tool does not determine duplication."* ]]
  [[ "$output" == *"known-1"* ]]
  [[ "$output" == *"--recurrence-of c-NNN"* ]]
  [[ "$output" == *"--recurrence-of none"* ]]
  ! printf '%s\n' "$output" | grep -qiE 'duplicate|rejected|blocked|refused'
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
}

@test "none decision uses guard ID appends one ledger line and can undo both writes" {
  expected_id="$(python3 "$ROOT/guard/failure_mode_catalog_guard.py" --next-id "$CATALOG")"
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"
  lines_before="$(wc -l <"$LEDGER")"

  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "new failure description" --recurrence-of none

  [ "$status" -eq 0 ]
  grep -Fq "| $expected_id |" "$CATALOG"
  grep -F "| $expected_id |" "$CATALOG" | grep -Fq 'recurrence_of: none'
  [ "$(tail -n 1 "$LEDGER")" = "$expected_id" ]
  [ "$(wc -l <"$LEDGER")" -eq $((lines_before + 1)) ]
  add_output="$output"
  run python3 "$ROOT/guard/failure_mode_catalog_guard.py" "$CATALOG"
  [ "$status" -eq 0 ]

  journal="$(printf '%s\n' "$add_output" | sed -n 's/^UNDO: .* --undo //p' | tail -n 1)"
  [ -n "$journal" ]
  run env CATALOG="$CATALOG" bash "$TOOL" --undo "$journal"
  [ "$status" -eq 0 ]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
}

@test "cluster decision is recorded while every other value aborts without writes" {
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "clustered failure description" --recurrence-of c-001
  [ "$status" -eq 0 ]
  grep -F 'clustered failure description' "$CATALOG" | grep -Fq 'recurrence_of: c-001'

  cp "$ROOT/catalog/failure-modes.md" "$CATALOG"
  cp "$ROOT/catalog/id-ledger.txt" "$LEDGER"
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "invalid recurrence description" --recurrence-of bogus
  [ "$status" -ne 0 ]
  [[ "$output" == *"c-NNN"* ]]
  [[ "$output" == *"none"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
}

@test "an invalid recurrence occurrence cannot be hidden by a later valid occurrence" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "repeated recurrence option" \
      --recurrence-of bogus --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"c-NNN"* ]]
  [[ "$output" == *"none"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
}

@test "a well-formed recurrence ID must exist in the clusters artifact" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "unknown cluster recurrence" --recurrence-of c-999

  [ "$status" -ne 0 ]
  [[ "$output" == *"c-999"* ]]
  [[ "$output" == *"clusters"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
}

@test "empty missing and unreadable corpora fail loudly before any write" {
  empty="$WORK/empty"
  unreadable="$WORK/unreadable"
  missing="$WORK/missing"
  mkdir -p "$empty" "$unreadable"
  printf '%s\n' '{"id":"x","instance":"x","source_path":"x"}' >"$unreadable/records.jsonl"
  chmod 000 "$unreadable"
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  for corpus in "$empty" "$missing" "$unreadable"; do
    run env CATALOG="$CATALOG" CORPUS="$corpus" \
      bash "$TOOL" -c A "x" --recurrence-of none
    [ "$status" -ne 0 ]
    [[ "$output" == *"$corpus"* ]]
    [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
    [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  done
}

@test "a populated corpus with zero candidates is a successful measured lookup" {
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "quartz zephyr" --recurrence-of none

  [ "$status" -eq 0 ]
  [[ "$output" == *"Candidates for human review. This tool does not determine duplication."* ]]
  [[ "$output" == *"measured; no advisory candidates found"* ]]
  ! [[ "$output" == *"Corpus is empty"* ]]
}

make_staged_repo() {
  STAGE="$WORK/stage"
  mkdir -p "$STAGE/bin" "$STAGE/.githooks" "$STAGE/guard" \
    "$STAGE/catalog" "$STAGE/pipeline/L1" "$STAGE/pipeline/L2" \
    "$WORK/fleet/orchestration" "$WORK/fleet-dispatch/migrations" \
    "$WORK/claude-codex/docs"
  cp "$TOOL" "$STAGE/bin/add-failure-mode.sh"
  cp "$ROOT/.githooks/pre-commit" "$STAGE/.githooks/pre-commit"
  cp "$ROOT/bin/similar-causes.py" "$STAGE/bin/similar-causes.py"
  printf '%s\n' '| FM-001 | A | old | old | Judgment |' >"$STAGE/catalog/failure-modes.md"
  printf '%s\n' 'FM-001' >"$STAGE/catalog/id-ledger.txt"
  printf '%s\n' '{"id":"seed","instance":"terminal success proof finished","source_path":"fixture"}' \
    >"$STAGE/pipeline/L1/seed.jsonl"
  printf '%s\n' 'old-l1-canon' >"$STAGE/pipeline/L1/homelab-canon.jsonl"
  printf '%s\n' 'old-l1-schema' >"$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl"
  printf '%s\n' \
    '{"_meta":{"backend":"fixture"}}' \
    '{"cluster_id":"c-001","members":["seed"]}' \
    >"$STAGE/pipeline/L2/clusters.jsonl"
  printf '%s\n' '## OPS-1' >"$WORK/fleet/FAILURE-MODES.md"
  printf '%s\n' '## OPS-2' >"$WORK/fleet/orchestration/FAILURE-MODES.md"
  printf '%s\n' '## CI-1' >"$WORK/fleet/CODING-INVARIANTS.md"
  printf '%s\n' '## FM-1' >"$WORK/fleet/CODING-FAILURE-MODES.md"
  printf '%s\n' "CHECK (failure_class IN ('fixture_failure'))" \
    >"$WORK/fleet-dispatch/migrations/0017_failure_class.sql"
  printf '%s\n' '## FM-001' >"$WORK/claude-codex/docs/integration-failure-modes.md"

  cat >"$STAGE/guard/failure_mode_catalog_guard.py" <<'PY'
import sys
if "--next-id" in sys.argv:
    print("FM-002")
PY
  cat >"$STAGE/pipeline/extract_mechanical.py" <<'PY'
import os
from pathlib import Path
root = Path(__file__).resolve().parents[1]
catalog = root / "catalog/failure-modes.md"
if "FM-002" not in catalog.read_text():
    raise SystemExit("catalog row missing before extract")
(root / "pipeline/L1/homelab-canon.jsonl").write_text("new-l1-canon\n")
(root / "pipeline/L1/fleet-dispatch-schema.jsonl").write_text("new-l1-schema\n")
with open(os.environ["TRACE"], "a") as handle:
    handle.write("extract\n")
PY
  cat >"$STAGE/pipeline/cluster.py" <<'PY'
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
if len(sys.argv) != 1:
    raise SystemExit("the ingest loop must use the repository's default L2 backend")
if Path(os.environ["TRACE"]).read_text().splitlines() != ["extract"]:
    raise SystemExit("extract did not run first")
(root / "pipeline/L2/clusters.jsonl").write_text("new-l2\n")
with open(os.environ["TRACE"], "a") as handle:
    handle.write("l2\n")
PY
  cat >"$STAGE/pipeline/reconcile_l1.py" <<'PY'
import os
from pathlib import Path
if Path(os.environ["TRACE"]).read_text().splitlines() != ["extract", "l2"]:
    raise SystemExit("catalog to extract to L2 order broken")
with open(os.environ["TRACE"], "a") as handle:
    handle.write("reconcile\n")
print("COMPLETE: 0 enumerable entries unaccounted for")
PY
}

@test "canonical add runs extract L2 and reconcile in order and undo restores generated artifacts" {
  make_staged_repo
  trace="$WORK/trace"
  catalog_before="$(file_digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(file_digest "$STAGE/catalog/id-ledger.txt")"
  l1_canon_before="$(file_digest "$STAGE/pipeline/L1/homelab-canon.jsonl")"
  l1_schema_before="$(file_digest "$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl")"
  l2_before="$(file_digest "$STAGE/pipeline/L2/clusters.jsonl")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "terminal success proof finished" --recurrence-of none

  [ "$status" -eq 0 ]
  [ "$(tr '\n' ' ' <"$trace")" = "extract l2 reconcile " ]
  [[ "$output" == *"COMPLETE"* ]]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO: .* --undo //p' | tail -n 1)"
  [ -n "$journal" ]

  run env CATALOG="$STAGE/catalog/failure-modes.md" \
    bash "$STAGE/bin/add-failure-mode.sh" --undo "$journal"
  [ "$status" -eq 0 ]
  [ "$(file_digest "$STAGE/catalog/failure-modes.md")" = "$catalog_before" ]
  [ "$(file_digest "$STAGE/catalog/id-ledger.txt")" = "$ledger_before" ]
  [ "$(file_digest "$STAGE/pipeline/L1/homelab-canon.jsonl")" = "$l1_canon_before" ]
  [ "$(file_digest "$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl")" = "$l1_schema_before" ]
  [ "$(file_digest "$STAGE/pipeline/L2/clusters.jsonl")" = "$l2_before" ]
}

@test "dot-dot canonical catalog alias still runs the whole loop" {
  make_staged_repo
  trace="$WORK/dotdot-trace"

  run env CATALOG="$STAGE/catalog/../catalog/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "dot dot alias" --recurrence-of c-001

  [ "$status" -eq 0 ]
  [ "$(tr '\n' ' ' <"$trace")" = "extract l2 reconcile " ]
  [[ "$output" == *"COMPLETE"* ]]
}

@test "symlink canonical catalog alias still runs the whole loop" {
  make_staged_repo
  ln -s "$STAGE/catalog" "$WORK/catalog-link"
  trace="$WORK/symlink-trace"

  run env CATALOG="$WORK/catalog-link/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "symlink alias" --recurrence-of c-001

  [ "$status" -eq 0 ]
  [ "$(tr '\n' ' ' <"$trace")" = "extract l2 reconcile " ]
  [[ "$output" == *"COMPLETE"* ]]
}

@test "missing sibling topology fails before journal or write" {
  make_staged_repo
  rm "$WORK/fleet-dispatch/migrations/0017_failure_class.sql"
  catalog_before="$(file_digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(file_digest "$STAGE/catalog/id-ledger.txt")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$WORK/topology-trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "missing topology" --recurrence-of c-001

  [ "$status" -ne 0 ]
  [[ "$output" == *"fleet-dispatch/migrations/0017_failure_class.sql"* ]]
  [[ "$output" != *"UNDO:"* ]]
  [ "$(file_digest "$STAGE/catalog/failure-modes.md")" = "$catalog_before" ]
  [ "$(file_digest "$STAGE/catalog/id-ledger.txt")" = "$ledger_before" ]
  [ ! -e "$WORK/topology-trace" ]
}

@test "tampered undo manifest is rejected atomically before any restore" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "tampered undo" --recurrence-of none
  [ "$status" -eq 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO: .* --undo //p' | tail -n 1)"
  [ -n "$journal" ]
  changed_catalog="$(file_digest "$CATALOG")"
  changed_ledger="$(file_digest "$LEDGER")"
  [ "$changed_catalog" != "$catalog_before" ]
  [ "$changed_ledger" != "$ledger_before" ]
  victim="$WORK/not-owned.txt"
  printf '%s\n' 'must survive' >"$victim"
  printf 'absent\t%s\t-\n' "$victim" >>"$journal/manifest.tsv"

  run env CATALOG="$CATALOG" bash "$TOOL" --undo "$journal"

  [ "$status" -ne 0 ]
  [[ "$output" == *"undo journal"* ]]
  [ "$(<"$victim")" = "must survive" ]
  [ "$(file_digest "$CATALOG")" = "$changed_catalog" ]
  [ "$(file_digest "$LEDGER")" = "$changed_ledger" ]
}

@test "pre-commit skips derived regeneration when canonical inputs are unchanged" {
  make_staged_repo
  git -C "$STAGE" init -q
  git -C "$STAGE" config user.name fixture
  git -C "$STAGE" config user.email fixture@example.invalid
  git -C "$STAGE" add .
  git -C "$STAGE" commit -q --no-verify -m baseline
  trace="$WORK/unchanged-trace"

  run env TRACE="$trace" bash "$STAGE/.githooks/pre-commit"

  [ "$status" -eq 0 ]
  [ ! -e "$trace" ]
  [ -z "$(git -C "$STAGE" status --short)" ]
}

@test "pre-commit fails loud until regenerated artifacts are staged" {
  make_staged_repo
  git -C "$STAGE" init -q
  git -C "$STAGE" config user.name fixture
  git -C "$STAGE" config user.email fixture@example.invalid
  git -C "$STAGE" add .
  git -C "$STAGE" commit -q --no-verify -m baseline
  printf '%s\n' '| FM-002 | A | new | new | Judgment |' >>"$STAGE/catalog/failure-modes.md"
  printf '%s\n' 'FM-002' >>"$STAGE/catalog/id-ledger.txt"
  git -C "$STAGE" add catalog/failure-modes.md catalog/id-ledger.txt
  trace="$WORK/changed-trace"

  run env TRACE="$trace" bash "$STAGE/.githooks/pre-commit"

  [ "$status" -ne 0 ]
  [[ "$output" == *"pipeline/L1/homelab-canon.jsonl"* ]]
  [[ "$output" == *"pipeline/L1/fleet-dispatch-schema.jsonl"* ]]
  [[ "$output" == *"pipeline/L2/clusters.jsonl"* ]]
  [[ "$output" == *"stage"* ]]

  git -C "$STAGE" add pipeline/L1/homelab-canon.jsonl \
    pipeline/L1/fleet-dispatch-schema.jsonl pipeline/L2/clusters.jsonl
  : >"$trace"
  run env TRACE="$trace" bash "$STAGE/.githooks/pre-commit"
  [ "$status" -eq 0 ]
  [ -z "$(git -C "$STAGE" diff --name-only)" ]
}
