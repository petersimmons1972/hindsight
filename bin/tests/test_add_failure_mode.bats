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
  for test_worktree in "${STALE_WORKTREE:-}" "${CLEAN_WORKTREE:-}" "${DIRECT_WORKTREE:-}"; do
    if [[ -n "$test_worktree" && -d "$test_worktree" && -n "${STAGE:-}" && -d "$STAGE/.git" ]]; then
      git -C "$STAGE" worktree remove --force "$test_worktree" || true
    fi
  done
  chmod u+rwx "$WORK/unreadable" 2>/dev/null || true
  rm -rf "$WORK"
}

file_digest() {
  sha256sum "$1" | awk '{print $1}'
}

@test "help prints usage and exits successfully without writing" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" bash "$TOOL" --help

  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage:"* ]]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
}

@test "missing recurrence decision prints advisory candidates and writes nothing" {
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "a terminal SUCCESS was treated as proof the work finished"

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
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "new failure description" --recurrence-of none

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

@test "printed UNDO command propagates CRITICALITY override so verbatim rollback owns the override path" {
  crit="$WORK/override-criticality.jsonl"
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"

  run env CATALOG="$CATALOG" CRITICALITY="$crit" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A -t HIGH --disposition advisory --ladder-rung prose-rule \
    "printed undo must own a criticality override" --recurrence-of none

  [ "$status" -eq 0 ]
  [ -f "$crit" ]
  add_output="$output"
  undo_line="$(printf '%s\n' "$add_output" | grep '^UNDO: ' | tail -n 1)"
  [ -n "$undo_line" ]
  undo_cmd="${undo_line#UNDO: }"
  [ -n "$undo_cmd" ]

  # Follow the printed command verbatim — the defect is that this exits 1
  # when CRITICALITY was overridden and the printer omitted it.
  run bash -c "$undo_cmd"
  [ "$status" -eq 0 ]
  [ ! -e "$crit" ]
  [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
  [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  [[ "$undo_line" == *"CRITICALITY="* ]]
}

@test "cluster decision is recorded while every other value aborts without writes" {
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "clustered failure description" --recurrence-of c-001
  [ "$status" -eq 0 ]
  grep -F 'clustered failure description' "$CATALOG" | grep -Fq 'recurrence_of: c-001'

  cp "$ROOT/catalog/failure-modes.md" "$CATALOG"
  cp "$ROOT/catalog/id-ledger.txt" "$LEDGER"
  catalog_before="$(file_digest "$CATALOG")"
  ledger_before="$(file_digest "$LEDGER")"
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "invalid recurrence description" --recurrence-of bogus
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
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "repeated recurrence option" \
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
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "unknown cluster recurrence" --recurrence-of c-999

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
      bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "x" --recurrence-of none
    [ "$status" -ne 0 ]
    [[ "$output" == *"$corpus"* ]]
    [ "$(file_digest "$CATALOG")" = "$catalog_before" ]
    [ "$(file_digest "$LEDGER")" = "$ledger_before" ]
  done
}

@test "a populated corpus with zero candidates is a successful measured lookup" {
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "quartz zephyr" --recurrence-of none

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
#
# Unlike reconcile_l1.py, L2 is deliberately not stubbed: the canonical write
# now releases an embedding snapshot, replays the real cluster module, ratchets
# recall baselines, and verifies the result.  The controlled release command is
# replaced only by the same honest offline stand-in used by
# test_add_failure_mode_release.py; it imports the staged real cluster.py and
# produces a deterministic snapshot without contacting an embedding host.
install_honest_release_fixture() {
  cat >"$STAGE/pipeline/capture_embedding_snapshot.py" <<'PY'
#!/usr/bin/env python3
"""Offline honest stand-in for the controlled embedding-snapshot release."""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np

repo = Path(__file__).resolve().parents[1]
snapshot = repo / "pipeline/L2/embedding-snapshot.json"
clusters_path = repo / "pipeline/L2/clusters.jsonl"
l1 = repo / "pipeline/L1"
code = repo / "pipeline/cluster.py"

spec = importlib.util.spec_from_file_location("hindsight_release_cluster", code)
cl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cl
spec.loader.exec_module(cl)

entries = cl.load_entries(l1)
dimensions = int(cl.HTTP_BACKEND_IDENTITY["dimensions"])


def deterministic_vector(entry_id):
    seed = int.from_bytes(hashlib.sha256(entry_id.encode("utf-8")).digest()[:8], "big")
    vector = np.random.default_rng(seed).normal(size=dimensions)
    vector /= np.linalg.norm(vector)
    return [round(float(value), 6) for value in vector]


embeddings = {entry.id: deterministic_vector(entry.id) for entry in entries}
l1_digest = cl.l1_corpus_digest(l1)
cluster_digest = cl.cluster_code_config_digest(code)
snapshot.write_text(json.dumps({
    "schema": cl.SNAPSHOT_SCHEMA,
    "provenance": {"l1_sha256": l1_digest, "cluster_sha256": cluster_digest},
    "backend": dict(cl.HTTP_BACKEND_IDENTITY),
    "embeddings": embeddings,
    "similarity_text_sha256": {
        entry.id: cl.similarity_text_digest(entry) for entry in entries
    },
}) + "\n", encoding="utf-8")

matrix = cl.load_embedding_snapshot(
    snapshot, entries, cl.HTTP_BACKEND_IDENTITY,
    expected_l1_digest=l1_digest, expected_cluster_digest=cluster_digest,
)
threshold = cl.default_threshold("http")
clusters = cl.cluster_entries(sorted(entries, key=lambda entry: entry.id), matrix,
                              backend_name="http", threshold=threshold)


class _Identity:
    name = "http"


cl.write_clusters(clusters_path, clusters, _Identity(), threshold, len(entries))
trace = os.environ.get("TRACE")
if trace:
    with open(trace, "a", encoding="utf-8") as handle:
        handle.write("release\n")
print(f"release stand-in: {len(entries)} entries, {len(clusters)} clusters")
PY
  chmod +x "$STAGE/pipeline/capture_embedding_snapshot.py"
}

make_staged_repo() {
  STAGE="$WORK/stage"
  mkdir -p "$STAGE/bin" "$STAGE/.githooks" "$STAGE/guard" \
    "$STAGE/catalog" "$STAGE/pipeline/L1" "$STAGE/pipeline/L2" \
    "$STAGE/pipeline/tests/fixtures" \
    "$WORK/fleet/orchestration" "$WORK/fleet-dispatch/migrations" \
    "$WORK/claude-codex/docs"
  cp "$TOOL" "$STAGE/bin/add-failure-mode.sh"
  cp "$ROOT/bin/verify-hook-worktree.sh" "$STAGE/bin/verify-hook-worktree.sh"
  cp "$ROOT/.githooks/pre-commit" "$STAGE/.githooks/pre-commit"
  # The copied hook's direct cluster invocation is a live HTTP operation in a
  # production checkout. Keep its regeneration/staging contract hermetic here
  # by selecting the shipped cluster module's explicit offline backend; the
  # canonical add tests above still exercise the HTTP-snapshot release path.
  sed -i 's|pipeline/cluster.py"|pipeline/cluster.py" --backend tfidf|' \
    "$STAGE/.githooks/pre-commit"
  cp "$ROOT/bin/similar-causes.py" "$STAGE/bin/similar-causes.py"
  cp "$ROOT/bin/synthesize-pointer.py" "$STAGE/bin/synthesize-pointer.py"
  cp "$ROOT/pipeline/cluster.py" "$STAGE/pipeline/cluster.py"
  cp "$ROOT/pipeline/replay_l2.py" "$STAGE/pipeline/replay_l2.py"
  cp "$ROOT/pipeline/replay_pins.py" "$STAGE/pipeline/replay_pins.py"
  cp "$ROOT/pipeline/recall_baselines.py" "$STAGE/pipeline/recall_baselines.py"
  cp "$ROOT/pipeline/tests/test_replay_l2.py" "$STAGE/pipeline/tests/test_replay_l2.py"
  cp "$ROOT/pipeline/tests/test_replay_l2_mutations.py" \
    "$STAGE/pipeline/tests/test_replay_l2_mutations.py"
  cp "$ROOT/pipeline/tests/fixtures/recurrence_ground_truth.json" \
    "$STAGE/pipeline/tests/fixtures/recurrence_ground_truth.json"
  printf '%s\n' '| FM-001 | A | old | old | Judgment |' >"$STAGE/catalog/failure-modes.md"
  printf '%s\n' 'FM-001' >"$STAGE/catalog/id-ledger.txt"
  printf '%s\n' \
    '{"id":"seed-a","instance":"terminal success proof finished","source_path":"fixture","source_anchor":"fixture:1","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    '{"id":"seed-b","instance":"configuration parser preserved an unsafe default","source_path":"fixture","source_anchor":"fixture:2","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    '{"id":"seed-c","instance":"rollback journal did not restore generated evidence","source_path":"fixture","source_anchor":"fixture:3","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    '{"id":"seed-d","instance":"dependency timeout was reported as a completed verdict","source_path":"fixture","source_anchor":"fixture:4","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    '{"id":"seed-e","instance":"a duplicate key folded separate occurrences together","source_path":"fixture","source_anchor":"fixture:5","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    >"$STAGE/pipeline/L1/seed.jsonl"
  printf '%s\n' '{"id":"FM-001","instance":"old canonical row","source_path":"catalog","source_anchor":"catalog:1","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    >"$STAGE/pipeline/L1/homelab-canon.jsonl"
  printf '%s\n' '{"id":"fixture_failure","instance":"old schema row","source_path":"migration","source_anchor":"migration:1","check":null,"enforcement":null,"auto":"machine","first_seen":null}' \
    >"$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl"
  printf '%s\n' '{"schema":"hindsight.recall-baselines/v1","baselines":{},"overrides":[]}' \
    >"$STAGE/pipeline/L2/recall-baselines.json"
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
(root / "pipeline/L1/homelab-canon.jsonl").write_text(
    '{"id":"FM-002","instance":"new canonical row","source_path":"catalog","source_anchor":"catalog:2","check":null,"enforcement":null,"auto":"judgment","first_seen":null}\n')
(root / "pipeline/L1/fleet-dispatch-schema.jsonl").write_text(
    '{"id":"fixture_failure","instance":"new schema row","source_path":"migration","source_anchor":"migration:1","check":null,"enforcement":null,"auto":"machine","first_seen":null}\n')
with open(os.environ["TRACE"], "a") as handle:
    handle.write("extract\n")
PY
  install_honest_release_fixture
  # Seed a replayable baseline so recurrence validation, undo, and the real
  # replay check all start from the same production-format L2 artifacts.
  python3 "$STAGE/pipeline/capture_embedding_snapshot.py" >/dev/null
  cat >"$STAGE/pipeline/reconcile_l1.py" <<'PY'
import os
from pathlib import Path
trace = Path(os.environ["TRACE"]).read_text().splitlines()
if trace not in (["extract", "release"], ["extract"]):
    raise SystemExit("catalog regeneration order broken")
with open(os.environ["TRACE"], "a") as handle:
    handle.write("reconcile\n")
print("COMPLETE: 0 enumerable entries unaccounted for")
PY
}

@test "canonical add runs extract L2 and reconcile in order and undo restores generated artifacts" {
  make_staged_repo
  trace="$WORK/trace"
  python3 - "$STAGE/pipeline/L2/recall-baselines.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["reconciled_floors"] = {
    "released": {
        "fixture-floor": {
            "together": 2,
            "members": 3,
            "fraction": 2 / 3,
            "cause": "reviewed staged reconciliation evidence",
        }
    }
}
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  cp "$STAGE/pipeline/L2/recall-baselines.json" "$WORK/recall-baselines-before-add.json"
  catalog_before="$(file_digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(file_digest "$STAGE/catalog/id-ledger.txt")"
  l1_canon_before="$(file_digest "$STAGE/pipeline/L1/homelab-canon.jsonl")"
  l1_schema_before="$(file_digest "$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl")"
  l2_before="$(file_digest "$STAGE/pipeline/L2/clusters.jsonl")"
  recall_baselines_before="$(file_digest "$STAGE/pipeline/L2/recall-baselines.json")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory --ladder-rung prose-rule "terminal success proof finished" --recurrence-of none

  [ "$status" -eq 0 ]
  add_output="$output"
  [ "$(tr '\n' ' ' <"$trace")" = "extract release reconcile " ]
  [[ "$output" == *"COMPLETE"* ]]
  [[ "$output" == *"replay-l2: PASS"* ]]
  run python3 "$STAGE/pipeline/recall_baselines.py" --backend released
  [ "$status" -eq 0 ]
  run python3 - "$STAGE/pipeline/L2/recall-baselines.json" "$WORK/recall-baselines-before-add.json" <<'PY'
import json
import sys
from pathlib import Path

after = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["reconciled_floors"]
before = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["reconciled_floors"]
assert json.dumps(after, sort_keys=True, separators=(",", ":")).encode() == \
       json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
PY
  [ "$status" -eq 0 ]
  journal="$(printf '%s\n' "$add_output" | sed -n 's/^UNDO: .* --undo //p' | tail -n 1)"
  [ -n "$journal" ]

  run env CATALOG="$STAGE/catalog/failure-modes.md" \
    bash "$STAGE/bin/add-failure-mode.sh" --undo "$journal"
  [ "$status" -eq 0 ]
  [ "$(file_digest "$STAGE/catalog/failure-modes.md")" = "$catalog_before" ]
  [ "$(file_digest "$STAGE/catalog/id-ledger.txt")" = "$ledger_before" ]
  [ "$(file_digest "$STAGE/pipeline/L1/homelab-canon.jsonl")" = "$l1_canon_before" ]
  [ "$(file_digest "$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl")" = "$l1_schema_before" ]
  [ "$(file_digest "$STAGE/pipeline/L2/clusters.jsonl")" = "$l2_before" ]
  [ "$(file_digest "$STAGE/pipeline/L2/recall-baselines.json")" = "$recall_baselines_before" ]
}

@test "canonical add does not forward the retired recall-drop environment override" {
  make_staged_repo
  trace="$WORK/recall-floor-trace"

  # This staged copy receives the former escape hatch. Before #121's
  # reconciliation, HINDSIGHT_ALLOW_RECALL_DROP_REASON added --allow-drop here.
  sed -i '/^from __future__ import annotations$/a import sys\nif "--allow-drop" in sys.argv: raise SystemExit("retired override was forwarded")' \
    "$STAGE/pipeline/recall_baselines.py"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$trace" \
    HINDSIGHT_ALLOW_RECALL_DROP_REASON="must-not-reach-the-release-tool" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory --ladder-rung prose-rule \
    "the known recalled floor needs no override" --recurrence-of none

  [ "$status" -eq 0 ]
  [[ "$output" != *"retired override was forwarded"* ]]
  [ "$(tr '\n' ' ' <"$trace")" = "extract release reconcile " ]
}

@test "canonical add without -t is rejected before any write" {
  make_staged_repo
  catalog_before="$(file_digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(file_digest "$STAGE/catalog/id-ledger.txt")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$WORK/no-tier-trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A --disposition advisory --ladder-rung prose-rule "missing tier" --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"-t/--tier is required"* ]]
  [ "$(file_digest "$STAGE/catalog/failure-modes.md")" = "$catalog_before" ]
  [ "$(file_digest "$STAGE/catalog/id-ledger.txt")" = "$ledger_before" ]
  [ ! -e "$WORK/no-tier-trace" ]
}

@test "-t rejects an unknown tier value" {
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" -c A -t URGENT --disposition advisory --ladder-rung prose-rule "bogus tier" --recurrence-of none
  [ "$status" -ne 0 ]
  [[ "$output" == *"CRITICAL, HIGH, MEDIUM, or LOW"* ]]
}

@test "canonical add records tier in criticality.jsonl and undo reverts it" {
  make_staged_repo
  trace="$WORK/tier-trace"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t CRITICAL --disposition advisory --ladder-rung prose-rule "tier recorded at filing time" --recurrence-of none

  [ "$status" -eq 0 ]
  [ -f "$STAGE/catalog/criticality.jsonl" ]
  add_output="$output"
  run python3 -c "
import json
row = json.loads(open('$STAGE/catalog/criticality.jsonl').read().splitlines()[-1])
assert row['fm_id'] == 'FM-002', row
assert row['tier'] == 'CRITICAL', row
assert row['generality'] == 'NARROW', row
assert row['scored_by'] == 'add-failure-mode.sh (write-time)', row
"
  [ "$status" -eq 0 ]

  journal="$(printf '%s\n' "$add_output" | sed -n 's/^UNDO: .* --undo //p' | tail -n 1)"
  [ -n "$journal" ]
  run env CATALOG="$STAGE/catalog/failure-modes.md" \
    bash "$STAGE/bin/add-failure-mode.sh" --undo "$journal"
  [ "$status" -eq 0 ]
  [ ! -s "$STAGE/catalog/criticality.jsonl" ]
}

@test "canonical add regenerates POINTER.md/HIGH.md and undo reverts them too" {
  make_staged_repo
  trace="$WORK/pointer-trace"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t CRITICAL --disposition advisory --ladder-rung prose-rule "pointer sync on write" --recurrence-of none

  [ "$status" -eq 0 ]
  [ -f "$STAGE/docs/POINTER.md" ]
  [ -f "$STAGE/docs/HIGH.md" ]
  grep -Fq 'FM-002' "$STAGE/docs/POINTER.md"

  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO: .* --undo //p' | tail -n 1)"
  [ -n "$journal" ]
  run env CATALOG="$STAGE/catalog/failure-modes.md" \
    bash "$STAGE/bin/add-failure-mode.sh" --undo "$journal"
  [ "$status" -eq 0 ]
  [ ! -e "$STAGE/docs/POINTER.md" ]
  [ ! -e "$STAGE/docs/HIGH.md" ]
}

@test "dot-dot canonical catalog alias still runs the whole loop" {
  make_staged_repo
  trace="$WORK/dotdot-trace"

  run env CATALOG="$STAGE/catalog/../catalog/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory --ladder-rung prose-rule "dot dot alias" --recurrence-of c-001

  [ "$status" -eq 0 ]
  [ "$(tr '\n' ' ' <"$trace")" = "extract release reconcile " ]
  [[ "$output" == *"COMPLETE"* ]]
}

@test "symlink canonical catalog alias still runs the whole loop" {
  make_staged_repo
  ln -s "$STAGE/catalog" "$WORK/catalog-link"
  trace="$WORK/symlink-trace"

  run env CATALOG="$WORK/catalog-link/failure-modes.md" TRACE="$trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory --ladder-rung prose-rule "symlink alias" --recurrence-of c-001

  [ "$status" -eq 0 ]
  [ "$(tr '\n' ' ' <"$trace")" = "extract release reconcile " ]
  [[ "$output" == *"COMPLETE"* ]]
}

@test "missing sibling topology fails before journal or write" {
  make_staged_repo
  rm "$WORK/fleet-dispatch/migrations/0017_failure_class.sql"
  catalog_before="$(file_digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(file_digest "$STAGE/catalog/id-ledger.txt")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" TRACE="$WORK/topology-trace" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A --disposition advisory --ladder-rung prose-rule "missing topology" --recurrence-of c-001

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
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "tampered undo" --recurrence-of none
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
    bash "$TOOL" -c A --disposition advisory --ladder-rung prose-rule "mid restore failure" --recurrence-of none
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
    '{"id":"OPS-1","instance":"fleet main entry","source_path":"fixture","source_anchor":"fixture:1","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    >"$STAGE/pipeline/L1/fleet-main.jsonl"
  printf '%s\n' \
    '{"id":"OPS-2","instance":"orch entry","source_path":"fixture","source_anchor":"fixture:2","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    '{"id":"CI-1","instance":"invariant entry","source_path":"fixture","source_anchor":"fixture:3","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    '{"id":"FM-1","instance":"coding entry","source_path":"fixture","source_anchor":"fixture:4","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
    >"$STAGE/pipeline/L1/fleet-orch.jsonl"
  printf '%s\n' \
    '{"id":"claude-fm-001","instance":"integration entry","source_path":"fixture","source_anchor":"FM-001","check":null,"enforcement":null,"auto":"judgment","first_seen":null}' \
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
                        "source_path": "catalog", "source_anchor": "catalog:1",
                        "check": None, "enforcement": None, "auto": "judgment",
                        "first_seen": None}) + "\n" for i in ids))
(root / "pipeline/L1/fleet-dispatch-schema.jsonl").write_text(
    json.dumps({"id": "fixture_failure", "instance": "schema class",
                "source_path": "migration", "source_anchor": "migration:1",
                "check": None, "enforcement": None, "auto": "machine",
                "first_seen": None}) + "\n")
PY
}

@test "the full-loop fixture uses the shipped L2 and reconciler modules byte for byte" {
  # If these ever drift, every test below is testing a copy of a production
  # dependency rather than that dependency -- the stub problem wearing a
  # different hat. The release command is the one intentional stand-in.
  make_real_reconcile_repo
  [ "$(file_digest "$STAGE/pipeline/reconcile_l1.py")" \
    = "$(file_digest "$ROOT/pipeline/reconcile_l1.py")" ]
  [ "$(file_digest "$STAGE/pipeline/cluster.py")" \
    = "$(file_digest "$ROOT/pipeline/cluster.py")" ]
  [ "$(file_digest "$STAGE/pipeline/replay_l2.py")" \
    = "$(file_digest "$ROOT/pipeline/replay_l2.py")" ]
  [ "$(file_digest "$STAGE/pipeline/recall_baselines.py")" \
    = "$(file_digest "$ROOT/pipeline/recall_baselines.py")" ]
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
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory --ladder-rung prose-rule "full loop no stub" --recurrence-of none

  [ "$status" -eq 0 ]
  grep -Fq '| FM-002 |' "$STAGE/catalog/failure-modes.md"
  grep -Fq 'FM-002' "$STAGE/pipeline/L1/homelab-canon.jsonl"

  # Output only the shipped reconciler can produce: a per-source coverage table,
  # a resolved-source count, and the standing scope-limit footer. The stub
  # printed one line and none of this.  `fleet-orch` is intentionally SHORT,
  # but the add gate is only the canonical catalog the loop just regenerated.
  [[ "$output" == *"SHORT: 1 enumerable entries unaccounted for; 0 canonical row(s) text-divergent (5/5 sources resolved)"* ]]
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

@test "two concurrent canonical adds serialize instead of corrupting each other (hindsight#187)" {
  # hindsight#187: two add-failure-mode.sh filings from one session were
  # reverted because nothing serialized ID allocation, the catalog/L1/L2
  # writes, and the undo trap across concurrent invocations. The loser's
  # post-write entry_count check (pipeline/replay_l2.py) saw a stale count
  # and the EXIT trap restored the undo journal, silently discarding a
  # filing that had actually landed. Use the real (unstubbed) ID guard here
  # -- the ordering-only fixture above pins --next-id to a constant and
  # cannot exercise the race at all.
  make_real_reconcile_repo
  cp "$ROOT/guard/failure_mode_catalog_guard.py" "$STAGE/guard/failure_mode_catalog_guard.py"

  out1="$WORK/concurrent-out-1.txt"
  out2="$WORK/concurrent-out-2.txt"
  (
    env CATALOG="$STAGE/catalog/failure-modes.md" \
      bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory \
        --ladder-rung prose-rule "concurrent writer one" --recurrence-of none \
      >"$out1" 2>&1
    echo $? >"$WORK/concurrent-status-1"
  ) &
  pid1=$!
  (
    env CATALOG="$STAGE/catalog/failure-modes.md" \
      bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory \
        --ladder-rung prose-rule "concurrent writer two" --recurrence-of none \
      >"$out2" 2>&1
    echo $? >"$WORK/concurrent-status-2"
  ) &
  pid2=$!
  wait "$pid1"
  wait "$pid2"

  status1="$(cat "$WORK/concurrent-status-1")"
  status2="$(cat "$WORK/concurrent-status-2")"
  [ "$status1" -eq 0 ] || { cat "$out1" >&2; false; }
  [ "$status2" -eq 0 ] || { cat "$out2" >&2; false; }

  # Narrow on purpose: this asserts neither writer REPORTED a rollback (the
  # hindsight#187 symptom -- the loser's entry_count check reverting a landed
  # write). It is not an assertion that no journal was emitted: a normal
  # successful add always emits an UNDO: command, by design.
  ! grep -qi "undo journal" "$out1" "$out2"
  ! grep -qi "operation failed" "$out1" "$out2"

  # Don't hardcode the guard's zero-padding width (FM-002 vs FM-02): assert
  # on the numeric sequence instead. Both new rows must land, as consecutive
  # numeric IDs immediately following the FM-001 seed, with no duplicates.
  mapfile -t nums < <(grep -oE '^\| FM-[0-9]+ \|' "$STAGE/catalog/failure-modes.md" \
    | grep -oE '[0-9]+' | sort -n -u)
  [ "${#nums[@]}" -eq 3 ]
  [ "${nums[0]}" -eq 1 ]
  [ "${nums[1]}" -eq 2 ]
  [ "${nums[2]}" -eq 3 ]

  mapfile -t ledger_nums < <(grep -oE 'FM-[0-9]+' "$STAGE/catalog/id-ledger.txt" \
    | grep -oE '[0-9]+' | sed 's/^0*//' | sort -n -u)
  [ "${#ledger_nums[@]}" -eq 3 ]
  [ "${ledger_nums[0]}" -eq 1 ]
  [ "${ledger_nums[1]}" -eq 2 ]
  [ "${ledger_nums[2]}" -eq 3 ]

  run python3 "$STAGE/pipeline/replay_l2.py"
  [ "$status" -eq 0 ]
}

# Mirror of the lock-identity rule in bin/add-failure-mode.sh. Kept in the test
# so a silent change to the derivation shows up as a failing row rather than as
# two processes quietly agreeing on the wrong thing.
expected_lock_path() {
  local runtime="$1" catalog="$2" id key
  if id="$(realpath -e -- "$catalog" 2>/dev/null)" && [ -n "$id" ]; then
    :
  else
    id="$(realpath -e -- "$(dirname -- "$catalog")")/$(basename -- "$catalog")"
  fi
  key="$(printf '%s' "$id" | sha256sum)"
  printf '%s/hindsight-add-failure-mode.%s.d/catalog-%s.lock' \
    "$runtime" "$UID" "${key%% *}"
}

@test "a symlink planted at the lock path is refused, not followed (hindsight#188)" {
  # The first lock implementation put the lock at a predictable path under a
  # world-writable directory and opened it with `>`, so any local user could
  # pre-plant a symlink there and have this script truncate the target.
  #
  # STAGE is deliberately NOT git-initialised: the lock path no longer depends
  # on git at all, and the earlier version of this row `git init`-ed the stage
  # and therefore only ever exercised the git-common-dir branch it was written
  # to cover (hindsight#188 review r1, low finding).
  make_staged_repo

  victim="$WORK/victim-lock-target.txt"
  printf '%s\n' 'must-survive' >"$victim"

  fake_runtime="$WORK/fake-runtime"
  mkdir -p "$fake_runtime"
  chmod 700 "$fake_runtime"

  catalog="$STAGE/catalog/failure-modes.md"
  lock_path="$(expected_lock_path "$fake_runtime" "$catalog")"
  mkdir -p -m 700 "$(dirname "$lock_path")"
  ln -s "$victim" "$lock_path"

  run env XDG_RUNTIME_DIR="$fake_runtime" CATALOG="$catalog" \
    bash "$STAGE/bin/add-failure-mode.sh" --help

  [ "$status" -ne 0 ]
  [[ "$output" == *"refusing unsafe lock path"* ]]
  [[ "$output" == *"is a symlink"* ]]

  # The symlink still points where it did, and its target was not touched.
  [ -L "$lock_path" ]
  [ "$(cat "$victim")" = "must-survive" ]
}

@test "lock identity is the catalog realpath: symlinked and relative paths collapse, different catalogs do not (hindsight#188)" {
  # The derivation must be stable across spellings of the same catalog (two
  # concurrent runs have to agree on one string) and distinct across different
  # catalogs (unrelated sandboxes must not contend). No git anywhere here:
  # git is no longer consulted, which is the point.
  runtime="$WORK/id-runtime"
  mkdir -p -m 700 "$runtime"

  mkdir -p "$WORK/id-a/catalog" "$WORK/id-b/catalog"
  touch "$WORK/id-a/catalog/failure-modes.md" "$WORK/id-b/catalog/failure-modes.md"
  ln -s "$WORK/id-a/catalog/failure-modes.md" "$WORK/id-a/aliased.md"
  [ ! -d "$WORK/id-a/.git" ]

  probe_lock() {
    env XDG_RUNTIME_DIR="$runtime" CATALOG="$1" \
      bash -x "$ROOT/bin/add-failure-mode.sh" --help 2>&1 \
      | grep -oE "$runtime/[^ ']*\.lock" | head -1
  }

  direct="$(probe_lock "$WORK/id-a/catalog/failure-modes.md")"
  via_symlink="$(probe_lock "$WORK/id-a/aliased.md")"
  via_relative="$(probe_lock "$WORK/id-a/catalog/../catalog/failure-modes.md")"
  other="$(probe_lock "$WORK/id-b/catalog/failure-modes.md")"

  [ -n "$direct" ]
  [ "$direct" = "$via_symlink" ]
  [ "$direct" = "$via_relative" ]
  [ "$direct" != "$other" ]

  # And it matches the rule this test file states independently.
  [ "$direct" = "$(expected_lock_path "$runtime" "$WORK/id-a/catalog/failure-modes.md")" ]
}

@test "concurrent adds to DIFFERENT catalogs do not block each other (hindsight#188 release-shard regression)" {
  # Regression guard for the r1 blocker: when the lock fell back to a single
  # per-UID path for every non-git sandbox, the release shard's three xdist
  # workers -- each in its own `.git`-stripped tmp copy, sharing no catalog,
  # ledger, journal, L1, L2 or pointer file -- serialized against one another
  # and ran past the 60-minute job bound.
  #
  # Deterministic by construction rather than timed: one process HOLDS the lock
  # for catalog A, then A is probed (must block until the timeout) and B is
  # probed (must return promptly). Probe A dies if the flock is removed; probe
  # B dies if the identity collapses to one lock again.
  runtime="$WORK/pair-runtime"
  mkdir -p -m 700 "$runtime"

  mkdir -p "$WORK/pair-a/catalog" "$WORK/pair-b/catalog"
  touch "$WORK/pair-a/catalog/failure-modes.md" "$WORK/pair-b/catalog/failure-modes.md"

  cat_a="$WORK/pair-a/catalog/failure-modes.md"
  cat_b="$WORK/pair-b/catalog/failure-modes.md"
  lock_a="$(expected_lock_path "$runtime" "$cat_a")"
  mkdir -p -m 700 "$(dirname "$lock_a")"
  : >"$lock_a"

  # Hold A's lock for the duration of both probes.
  flock -x "$lock_a" sleep 30 &
  holder=$!
  # Wait until the holder actually owns it, so the probes are never racing the
  # holder's own startup.
  for _ in $(seq 1 100); do
    flock -n -x "$lock_a" true || break
    sleep 0.1
  done
  run flock -n -x "$lock_a" true
  [ "$status" -ne 0 ]

  # Same catalog as the holder: must block until timeout (124).
  run env XDG_RUNTIME_DIR="$runtime" CATALOG="$cat_a" \
    timeout 5 bash "$ROOT/bin/add-failure-mode.sh" --help
  status_same="$status"

  # Different catalog: must NOT be blocked by the holder.
  run env XDG_RUNTIME_DIR="$runtime" CATALOG="$cat_b" \
    timeout 5 bash "$ROOT/bin/add-failure-mode.sh" --help
  status_other="$status"

  kill "$holder" 2>/dev/null || true
  wait "$holder" 2>/dev/null || true

  [ "$status_same" -eq 124 ]
  [ "$status_other" -ne 124 ]
}

@test "three non-git sandbox copies select three distinct locks, not one per-UID lock (hindsight#188)" {
  # The release shard copies the repo with `.git` excluded (COPY_IGNORE) into a
  # pytest tmp dir per test and runs `-n 3 --dist=load`. At the previous head
  # every such copy failed `git rev-parse` and selected the identical per-UID
  # lock file. This asserts the mechanism itself: three independent non-git
  # copies must now resolve to three different lock identities.
  runtime="$WORK/shard-runtime"
  mkdir -p -m 700 "$runtime"

  paths="$WORK/shard-lock-paths.txt"
  : >"$paths"
  for i in 1 2 3; do
    copy="$WORK/shard-copy-$i"
    mkdir -p "$copy/bin" "$copy/catalog"
    cp "$ROOT/bin/add-failure-mode.sh" "$copy/bin/add-failure-mode.sh"
    touch "$copy/catalog/failure-modes.md"
    [ ! -e "$copy/.git" ]
    env XDG_RUNTIME_DIR="$runtime" CATALOG="$copy/catalog/failure-modes.md" \
      bash -x "$copy/bin/add-failure-mode.sh" --help 2>&1 \
      | grep -oE "$runtime/[^ ']*\.lock" | head -1 >>"$paths"
  done

  [ "$(wc -l <"$paths")" -eq 3 ]
  [ "$(sort -u "$paths" | wc -l)" -eq 3 ]
}

@test "a sibling shortfall stays reported but does not block a canonical add" {
  make_real_reconcile_repo

  run env CATALOG="$STAGE/catalog/failure-modes.md" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory --ladder-rung prose-rule "unrelated backlog must not block" \
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
    bash "$STAGE/bin/add-failure-mode.sh" -c A -t HIGH --disposition advisory --ladder-rung prose-rule "lossy extraction must still fail" \
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
  # The hook must only verify the controlled L2 release; it must not derive a
  # replacement partition through the live backend.  Produce that release here
  # but deliberately leave its artifacts unstaged for the first hook run.
  run env TRACE="$WORK/hook-release-trace" python3 "$STAGE/pipeline/extract_mechanical.py"
  [ "$status" -eq 0 ]
  run env TRACE="$WORK/hook-release-trace" python3 "$STAGE/pipeline/capture_embedding_snapshot.py"
  [ "$status" -eq 0 ]

  run bash -c 'cd "$1" && bash "$2"' _ "$STAGE" "$STAGE/.githooks/pre-commit"
  # It still demands the regenerated artifacts be staged -- that gate is intact.
  [ "$status" -ne 0 ]
  [[ "$output" != *"SHORT"* ]]
  [[ "$output" == *"NOT CHECKED by this run"* ]]

  git -C "$STAGE" add pipeline/L1/homelab-canon.jsonl \
    pipeline/L1/fleet-dispatch-schema.jsonl pipeline/L2/embedding-snapshot.json \
    pipeline/L2/clusters.jsonl
  run bash -c 'cd "$1" && bash "$2"' _ "$STAGE" "$STAGE/.githooks/pre-commit"
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

  run env TRACE="$trace" bash -c 'cd "$1" && bash "$2"' \
    _ "$STAGE" "$STAGE/.githooks/pre-commit"

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
  run env TRACE="$trace" python3 "$STAGE/pipeline/extract_mechanical.py"
  [ "$status" -eq 0 ]
  run env TRACE="$trace" python3 "$STAGE/pipeline/capture_embedding_snapshot.py"
  [ "$status" -eq 0 ]
  : >"$trace"

  run env TRACE="$trace" bash -c 'cd "$1" && bash "$2"' \
    _ "$STAGE" "$STAGE/.githooks/pre-commit"

  [ "$status" -ne 0 ]
  [[ "$output" == *"pipeline/L1/homelab-canon.jsonl"* ]]
  [[ "$output" == *"pipeline/L1/fleet-dispatch-schema.jsonl"* ]]
  [[ "$output" == *"pipeline/L2/embedding-snapshot.json"* ]]
  [[ "$output" == *"pipeline/L2/clusters.jsonl"* ]]
  [[ "$output" == *"stage"* ]]

  git -C "$STAGE" add pipeline/L1/homelab-canon.jsonl \
    pipeline/L1/fleet-dispatch-schema.jsonl pipeline/L2/embedding-snapshot.json \
    pipeline/L2/clusters.jsonl
  : >"$trace"
  run env TRACE="$trace" bash -c 'cd "$1" && bash "$2"' \
    _ "$STAGE" "$STAGE/.githooks/pre-commit"
  [ "$status" -eq 0 ]
  [ -z "$(git -C "$STAGE" diff --name-only)" ]
}

@test "pre-commit uses the linked worktree from its checked-out hook" {
  make_staged_repo
  git -C "$STAGE" init -q
  git -C "$STAGE" config user.name fixture
  git -C "$STAGE" config user.email fixture@example.invalid
  git -C "$STAGE" add .
  git -C "$STAGE" commit -q --no-verify -m baseline
  git -C "$STAGE" config core.hooksPath "$STAGE/.githooks"

  stale_worktree="$WORK/stale-worktree"
  STALE_WORKTREE="$stale_worktree"
  git -C "$STAGE" worktree add -q -b stale-worktree "$stale_worktree"
  printf '%s\n' '| FM-002 | A | new | new | Judgment |' >>"$stale_worktree/catalog/failure-modes.md"
  printf '%s\n' 'FM-002' >>"$stale_worktree/catalog/id-ledger.txt"
  git -C "$stale_worktree" add catalog/failure-modes.md catalog/id-ledger.txt
  trace="$WORK/stale-trace"
  run env TRACE="$trace" bash -c 'cd "$1" && python3 pipeline/extract_mechanical.py && python3 pipeline/capture_embedding_snapshot.py' \
    _ "$stale_worktree"
  [ "$status" -eq 0 ]
  : >"$trace"

  # The generated artifacts are deliberately left unstaged. The checked-out
  # hook must regenerate in this linked worktree and reject the stale staging
  # area.
  run env TRACE="$trace" bash -c 'cd "$1" && bash "$2"' \
    _ "$stale_worktree" "$stale_worktree/.githooks/pre-commit"
  [ "$status" -ne 0 ]
  [[ "$output" == *"not staged"* ]]

  git -C "$STAGE" worktree remove --force "$stale_worktree"
}

@test "pre-commit ignores dirty generated artifacts in a sibling checkout" {
  make_staged_repo
  git -C "$STAGE" init -q
  git -C "$STAGE" config user.name fixture
  git -C "$STAGE" config user.email fixture@example.invalid
  git -C "$STAGE" add .
  git -C "$STAGE" commit -q --no-verify -m baseline
  git -C "$STAGE" config core.hooksPath "$STAGE/.githooks"

  clean_worktree="$WORK/clean-worktree"
  CLEAN_WORKTREE="$clean_worktree"
  git -C "$STAGE" worktree add -q -b clean-worktree "$clean_worktree"
  printf '%s\n' '| FM-002 | A | new | new | Judgment |' >>"$clean_worktree/catalog/failure-modes.md"
  printf '%s\n' 'FM-002' >>"$clean_worktree/catalog/id-ledger.txt"
  git -C "$clean_worktree" add catalog/failure-modes.md catalog/id-ledger.txt
  clean_trace="$WORK/clean-trace"
  run env TRACE="$clean_trace" bash -c 'cd "$1" && python3 pipeline/extract_mechanical.py && python3 pipeline/capture_embedding_snapshot.py' \
    _ "$clean_worktree"
  [ "$status" -eq 0 ]
  git -C "$clean_worktree" add pipeline/L1/homelab-canon.jsonl \
    pipeline/L1/fleet-dispatch-schema.jsonl pipeline/L2/embedding-snapshot.json \
    pipeline/L2/clusters.jsonl

  # A dirty main checkout must not make a correctly staged linked worktree
  # abort.  The old hook sees this catalog and generated-artifact drift instead.
  printf '%s\n' '| FM-002 | A | main | main | Judgment |' >>"$STAGE/catalog/failure-modes.md"
  printf '%s\n' 'main-checkout-drift' >>"$STAGE/pipeline/L2/clusters.jsonl"
  : >"$clean_trace"
  run env TRACE="$clean_trace" bash -c 'cd "$1" && bash "$2"' \
    _ "$clean_worktree" "$clean_worktree/.githooks/pre-commit"
  [ "$status" -eq 0 ]

  git -C "$STAGE" worktree remove --force "$clean_worktree"
}

@test "staged-copy add and direct pre-commit invocation work in a linked worktree" {
  make_staged_repo
  git -C "$STAGE" init -q
  git -C "$STAGE" config user.name fixture
  git -C "$STAGE" config user.email fixture@example.invalid
  git -C "$STAGE" add .
  git -C "$STAGE" commit -q --no-verify -m baseline
  git -C "$STAGE" config core.hooksPath "$STAGE/.githooks"

  linked_worktree="$WORK/direct-worktree"
  DIRECT_WORKTREE="$linked_worktree"
  git -C "$STAGE" worktree add -q -b direct-worktree "$linked_worktree"
  trace="$WORK/direct-trace"
  run env TRACE="$trace" bash -c 'cd "$1" && bash bin/add-failure-mode.sh -c A -t HIGH --disposition advisory --ladder-rung prose-rule "direct hook fixture" --recurrence-of none' \
    _ "$linked_worktree"
  [ "$status" -eq 0 ]
  git -C "$linked_worktree" add catalog/failure-modes.md catalog/id-ledger.txt \
    catalog/criticality.jsonl pipeline/L1/homelab-canon.jsonl \
    pipeline/L1/fleet-dispatch-schema.jsonl pipeline/L2/embedding-snapshot.json \
    pipeline/L2/clusters.jsonl
  : >"$trace"

  run env TRACE="$trace" bash -c 'cd "$1" && bash "$2"' \
    _ "$linked_worktree" "$linked_worktree/.githooks/pre-commit"
  [ "$status" -eq 0 ]

  git -C "$STAGE" worktree remove --force "$linked_worktree"
}

@test "pre-commit fails loud when criticality.jsonl changes but pointer files are stale" {
  make_staged_repo
  mkdir -p "$STAGE/docs"
  printf '%s\n' '{"fm_id":"FM-001","tier":"CRITICAL","generality":"BROAD","rationale":"seed","evidence":"seed","mechanize_action":"n/a","scored_by":"seed","date":"2026-01-01"}' \
    >"$STAGE/catalog/criticality.jsonl"
  ( cd "$STAGE" && python3 bin/synthesize-pointer.py >/dev/null )
  git -C "$STAGE" init -q
  git -C "$STAGE" config user.name fixture
  git -C "$STAGE" config user.email fixture@example.invalid
  git -C "$STAGE" add .
  git -C "$STAGE" commit -q --no-verify -m baseline

  # Hand-edit criticality.jsonl without regenerating the pointer files -- the
  # exact drift a hand-edit (rather than add-failure-mode.sh) can introduce.
  # The tier flips CRITICAL -> HIGH so the rendered output actually changes
  # (POINTER.md loses the entry, HIGH.md gains it), not just an unrendered
  # field like rationale.
  printf '%s\n' '{"fm_id":"FM-001","tier":"HIGH","generality":"BROAD","rationale":"hand-edited","evidence":"hand-edited, not resynthesized","mechanize_action":"n/a","scored_by":"hand-edit","date":"2026-01-02"}' \
    >"$STAGE/catalog/criticality.jsonl"
  git -C "$STAGE" add catalog/criticality.jsonl

  run bash -c 'cd "$1" && bash "$2"' _ "$STAGE" "$STAGE/.githooks/pre-commit"
  [ "$status" -ne 0 ]
  [[ "$output" == *"docs/POINTER.md / docs/HIGH.md are stale"* ]]

  ( cd "$STAGE" && python3 bin/synthesize-pointer.py >/dev/null )
  git -C "$STAGE" add docs/POINTER.md docs/HIGH.md
  run bash -c 'cd "$1" && bash "$2"' _ "$STAGE" "$STAGE/.githooks/pre-commit"
  [ "$status" -eq 0 ]
}
