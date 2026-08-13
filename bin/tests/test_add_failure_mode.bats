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

# ── STUB WARNING: read this before trusting a green run of the tests below ────
# make_staged_repo replaces pipeline/reconcile_l1.py with a fixture whose whole
# body prints "COMPLETE: 0 enumerable entries unaccounted for". It exists to
# make ordering and undo assertions fast and deterministic, NOT to check the
# reconciler. SIX tests use it and therefore cannot observe any behaviour of the
# real reconciler at all:
#
#   1. canonical add runs extract L2 and reconcile in order and undo restores
#      generated artifacts
#   2. dot-dot canonical catalog alias still runs the whole loop
#   3. symlink canonical catalog alias still runs the whole loop
#   4. missing sibling topology fails before journal or write
#   5. pre-commit skips derived regeneration when canonical inputs are unchanged
#   6. pre-commit fails loud until regenerated artifacts are staged
#
# That is the shape of issue #73's own root cause: a stubbed reconciler hid the
# bug from the very tests that looked like they covered it. The stub is kept
# only where the reconciler is not the subject; every claim about what the add
# loop does WITH the reconciler is made by a test built on
# make_real_reconcile_repo, which copies the shipped script in verbatim.
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

@test "a mid-restore copy failure rolls every target back to its pre-undo state" {
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A "mid restore failure" --recurrence-of none
  [ "$status" -eq 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO: .* --undo //p' | tail -n 1)"
  [ -n "$journal" ]
  changed_catalog="$(file_digest "$CATALOG")"
  changed_ledger="$(file_digest "$LEDGER")"

  fakebin="$WORK/fakebin"
  fail_state="$WORK/cp-failed-once"
  mkdir -p "$fakebin"
  cat >"$fakebin/cp" <<'SH'
#!/usr/bin/env bash
destination="${@: -1}"
if [[ "$destination" == "$CP_FAIL_TARGET" && ! -e "$CP_FAIL_STATE" ]]; then
  : >"$CP_FAIL_STATE"
  echo "injected copy failure for $destination" >&2
  exit 73
fi
exec /bin/cp "$@"
SH
  chmod +x "$fakebin/cp"

  run env CATALOG="$CATALOG" PATH="$fakebin:$PATH" \
    CP_FAIL_TARGET="$LEDGER" CP_FAIL_STATE="$fail_state" \
    bash "$TOOL" --undo "$journal"

  [ "$status" -ne 0 ]
  [[ "$output" == *"copy failure"* ]]
  [ -e "$fail_state" ]
  [ "$(file_digest "$CATALOG")" = "$changed_catalog" ]
  [ "$(file_digest "$LEDGER")" = "$changed_ledger" ]
}

# ── Full loop against the REAL reconciler (issues #73 and #101) ───────────────
# Every full-loop test above stubs pipeline/reconcile_l1.py, so the loop's last
# step was only ever exercised as a fixture that prints COMPLETE. On a real
# checkout it exited 1 -- an unrelated sibling source was SHORT -- and the add
# rolled itself back, so the catalog could not be added to at all. These tests
# run the shipped reconciler: one proves an unrelated source's backlog remains
# visible but no longer blocks the add, the other proves the gate still fails
# the add when the source the add itself writes is short.
make_real_reconcile_repo() {
  make_staged_repo
  cp "$ROOT/pipeline/reconcile_l1.py" "$STAGE/pipeline/reconcile_l1.py"

  # fleet-orch ground truth is OPS-2 + CI-1 + FM-1 + OPS-99; its L1 extract is
  # missing OPS-99, so this source -- which the add never touches -- is SHORT.
  printf '%s\n' '## OPS-2' '## OPS-99' >"$WORK/fleet/orchestration/FAILURE-MODES.md"
  printf '%s\n' \
    '{"id":"OPS-1","instance":"fleet main entry","source_path":"fixture"}' \
    >"$STAGE/pipeline/L1/fleet-main.jsonl"
  printf '%s\n' \
    '{"id":"OPS-2","instance":"orch entry","source_path":"fixture"}' \
    '{"id":"CI-1","instance":"invariant entry","source_path":"fixture"}' \
    '{"id":"FM-1","instance":"coding entry","source_path":"fixture"}' \
    >"$STAGE/pipeline/L1/fleet-orch.jsonl"
  printf '%s\n' \
    '{"id":"FM-001","instance":"integration entry","source_path":"fixture"}' \
    >"$STAGE/pipeline/L1/claude-codex-integration.jsonl"

  # A faithful extractor: it derives homelab-canon from the catalog it was just
  # handed. LOSSY=1 makes it drop the newest row, which is how a real lossy
  # extraction presents to the reconciler.
  cat >"$STAGE/pipeline/extract_mechanical.py" <<'PY'
import json
import os
import re
from pathlib import Path
root = Path(__file__).resolve().parents[1]
ids = re.findall(r'^\| (FM-\d{2,3}) \|',
                 (root / "catalog/failure-modes.md").read_text(), re.M)
if os.environ.get("LOSSY") == "1":
    ids = ids[:-1]
(root / "pipeline/L1/homelab-canon.jsonl").write_text(
    "".join(json.dumps({"id": i, "instance": "canon row",
                        "source_path": "catalog"}) + "\n" for i in ids))
(root / "pipeline/L1/fleet-dispatch-schema.jsonl").write_text(
    json.dumps({"id": "fixture_failure", "instance": "schema class",
                "source_path": "migration"}) + "\n")
PY
  cat >"$STAGE/pipeline/cluster.py" <<'PY'
from pathlib import Path
root = Path(__file__).resolve().parents[1]
(root / "pipeline/L2/clusters.jsonl").write_text(
    '{"_meta":{"backend":"fixture"}}\n{"cluster_id":"c-001","members":["seed"]}\n')
PY
}

@test "the real-reconciler fixture uses the shipped script byte for byte" {
  # If this ever drifts, every test below is testing a copy of the reconciler
  # rather than the reconciler -- the stub problem wearing a different hat.
  make_real_reconcile_repo
  [ "$(file_digest "$STAGE/pipeline/reconcile_l1.py")" \
    = "$(file_digest "$ROOT/pipeline/reconcile_l1.py")" ]
  ! grep -Fq 'COMPLETE: 0 enumerable entries unaccounted for' \
    "$STAGE/pipeline/reconcile_l1.py"
}

@test "canonical add runs the whole loop against the real reconciler and undo restores every artifact" {
  # The unstubbed twin of "canonical add runs extract L2 and reconcile in
  # order...". Ordering is proved by evidence rather than by a trace file a
  # fixture wrote: the reconciler reports COMPLETE for homelab-canon, which is
  # only reachable if extract had already regenerated that L1 from the catalog
  # row this very add appended. A reconcile that ran first would be SHORT.
  make_real_reconcile_repo
  catalog_before="$(file_digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(file_digest "$STAGE/catalog/id-ledger.txt")"
  l1_canon_before="$(file_digest "$STAGE/pipeline/L1/homelab-canon.jsonl")"
  l1_schema_before="$(file_digest "$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl")"
  l2_before="$(file_digest "$STAGE/pipeline/L2/clusters.jsonl")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "full loop no stub" --recurrence-of none

  [ "$status" -eq 0 ]
  grep -Fq '| FM-002 |' "$STAGE/catalog/failure-modes.md"
  grep -Fq 'FM-002' "$STAGE/pipeline/L1/homelab-canon.jsonl"

  # Output only the shipped reconciler can produce: a per-source coverage table,
  # a resolved-source count, and the standing scope-limit footer. The stub
  # printed one line and none of this.  `fleet-orch` is intentionally SHORT,
  # but the add gate is only the canonical catalog the loop just regenerated.
  [[ "$output" == *"SHORT: 1 enumerable entries unaccounted for (5/5 sources resolved)"* ]]
  [[ "$output" == *"SCOPE LIMIT"* ]]
  [[ "$output" == *"homelab-canon"* ]]
  [[ "$output" == *"fleet-dispatch-schema"* ]]
  # The full health report must keep the sibling backlog visible; only the
  # exit-status gate is narrowed for this one canonical write (hindsight#101).
  [[ "$output" == *"fleet-main"* ]]
  [[ "$output" == *"fleet-orch"* ]]
  [[ "$output" == *"claude-codex-integration"* ]]
  [[ "$output" == *"OPS-99"* ]]
  [[ "$output" == *"GATE: COMPLETE across homelab-canon; exit 0"* ]]

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

@test "a sibling shortfall stays reported but does not block a canonical add" {
  make_real_reconcile_repo

  run env CATALOG="$STAGE/catalog/failure-modes.md" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "unrelated backlog must not block" \
      --recurrence-of none

  [ "$status" -eq 0 ]
  grep -Fq '| FM-002 |' "$STAGE/catalog/failure-modes.md"
  [ "$(tail -n 1 "$STAGE/catalog/id-ledger.txt")" = "FM-002" ]
  [[ "$output" != *"applying undo journal"* ]]
  # The full report retains the real sibling shortfall; it is explicitly
  # non-blocking only because this add did not write fleet-orch (hindsight#101).
  [[ "$output" == *"fleet-orch"* ]]
  [[ "$output" == *"OPS-99"* ]]
  [[ "$output" == *"GATE: COMPLETE across homelab-canon; exit 0"* ]]

  # And the drift it skipped is still detectable by the unscoped run: the fix
  # unblocks the add, it does not hide the backlog.
  run python3 "$STAGE/pipeline/reconcile_l1.py"
  [ "$status" -eq 1 ]
  [[ "$output" == *"SHORT"* ]]
  [[ "$output" == *"OPS-99"* ]]
}

@test "a short source that the add itself writes still fails the add and rolls back" {
  make_real_reconcile_repo
  catalog_before="$(file_digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(file_digest "$STAGE/catalog/id-ledger.txt")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" LOSSY=1 \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "lossy extraction must still fail" \
      --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"SHORT"* ]]
  [[ "$output" == *"GATE: SHORT across homelab-canon; blocking source(s): homelab-canon"* ]]
  [[ "$output" == *"applying undo journal"* ]]
  [ "$(file_digest "$STAGE/catalog/failure-modes.md")" = "$catalog_before" ]
  [ "$(file_digest "$STAGE/catalog/id-ledger.txt")" = "$ledger_before" ]
}

@test "reconcile refuses an unknown --source instead of certifying an empty scope" {
  run python3 "$ROOT/pipeline/reconcile_l1.py" --source no-such-source
  [ "$status" -eq 2 ]
  [[ "$output" == *"unknown --source"* ]]
}

@test "pre-commit does not block a catalog commit on an unrelated source's backlog" {
  # The hook is the third call site of the same wrong coupling: even after the
  # add succeeds, an unscoped reconcile here made the resulting COMMIT
  # impossible, so the catalog still could not be added to (issue #73).
  make_real_reconcile_repo
  git -C "$STAGE" init -q
  git -C "$STAGE" config user.name fixture
  git -C "$STAGE" config user.email fixture@example.invalid
  git -C "$STAGE" add .
  git -C "$STAGE" commit -q --no-verify -m baseline
  printf '%s\n' '| FM-002 | A | new | new | Judgment |' >>"$STAGE/catalog/failure-modes.md"
  printf '%s\n' 'FM-002' >>"$STAGE/catalog/id-ledger.txt"
  git -C "$STAGE" add catalog/failure-modes.md catalog/id-ledger.txt

  run bash "$STAGE/.githooks/pre-commit"
  # It still demands the regenerated artifacts be staged -- that gate is intact.
  [ "$status" -ne 0 ]
  [[ "$output" != *"SHORT"* ]]
  [[ "$output" == *"NOT CHECKED by this run"* ]]

  git -C "$STAGE" add pipeline/L1/homelab-canon.jsonl \
    pipeline/L1/fleet-dispatch-schema.jsonl pipeline/L2/clusters.jsonl
  run bash "$STAGE/.githooks/pre-commit"
  [ "$status" -eq 0 ]
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
