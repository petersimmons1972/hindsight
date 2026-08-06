#!/usr/bin/env bats

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORK="$(mktemp -d)"
}

teardown() {
  rm -rf "$WORK"
}

digest() {
  sha256sum "$1" | awk '{print $1}'
}

make_real_fixture() {
  STAGE="$WORK/stage"
  mkdir -p "$STAGE/bin" "$STAGE/guard" "$STAGE/catalog" \
    "$STAGE/pipeline/L1" "$STAGE/pipeline/L2" "$WORK/fleet/orchestration" \
    "$WORK/fleet-dispatch/migrations" "$WORK/claude-codex/docs"

  cp "$ROOT/bin/add-failure-mode.sh" "$STAGE/bin/add-failure-mode.sh"
  cp "$ROOT/bin/similar-causes.py" "$STAGE/bin/similar-causes.py"
  cp "$ROOT/pipeline/reconcile_l1.py" "$STAGE/pipeline/reconcile_l1_impl.py"

  cat >"$STAGE/pipeline/reconcile_l1.py" <<'PY'
import os
import runpy
import sys
from pathlib import Path

with Path(os.environ["RECONCILE_TRACE"]).open("a", encoding="utf-8") as handle:
    handle.write("\t".join(sys.argv[1:]) + "\n")
runpy.run_path(str(Path(__file__).with_name("reconcile_l1_impl.py")), run_name="__main__")
PY

  cat >"$STAGE/guard/failure_mode_catalog_guard.py" <<'PY'
import sys
if "--next-id" in sys.argv:
    print("FM-002")
PY

  cat >"$STAGE/pipeline/extract_mechanical.py" <<'PY'
import json
import os
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
ids = re.findall(r"^\| (FM-\d{2,3}) \|", (root / "catalog/failure-modes.md").read_text(), re.M)
if os.environ.get("LOSSY") == "1":
    ids = ids[:-1]
(root / "pipeline/L1/homelab-canon.jsonl").write_text(
    "".join(json.dumps({"id": value, "instance": "canon", "source_path": "fixture"}) + "\n" for value in ids)
)
(root / "pipeline/L1/fleet-dispatch-schema.jsonl").write_text(
    json.dumps({"id": "fixture_failure", "instance": "schema", "source_path": "fixture"}) + "\n"
)
PY

  cat >"$STAGE/pipeline/cluster.py" <<'PY'
from pathlib import Path
root = Path(__file__).resolve().parents[1]
(root / "pipeline/L2/clusters.jsonl").write_text('{"_meta": {"backend": "fixture"}}\n')
PY

  printf '%s\n' '| ID | Class | Instance | Lesson | Enforcement |' \
    '| FM-001 | A | old | old | Judgment |' >"$STAGE/catalog/failure-modes.md"
  printf '%s\n' 'FM-001' >"$STAGE/catalog/id-ledger.txt"
  printf '%s\n' '{"id":"seed","instance":"terminal success proof","source_path":"fixture"}' \
    >"$STAGE/pipeline/L1/seed.jsonl"
  printf '%s\n' '{"id":"FM-001"}' >"$STAGE/pipeline/L1/homelab-canon.jsonl"
  printf '%s\n' '{"id":"fixture_failure"}' >"$STAGE/pipeline/L1/fleet-dispatch-schema.jsonl"
  printf '%s\n' '{"_meta":{"backend":"fixture"}}' >"$STAGE/pipeline/L2/clusters.jsonl"
  mkdir -p "$WORK/corpus"
  printf '%s\n' '{"id":"known-1","instance":"known","source_path":"fixture"}' \
    >"$WORK/corpus/records.jsonl"

  # homelab-canon is complete; fleet-orch is independently SHORT by OPS-99.
  printf '%s\n' '## OPS-1' >"$WORK/fleet/FAILURE-MODES.md"
  printf '%s\n' '## OPS-2' '## OPS-99' >"$WORK/fleet/orchestration/FAILURE-MODES.md"
  printf '%s\n' '## CI-1' >"$WORK/fleet/CODING-INVARIANTS.md"
  printf '%s\n' '## FM-1' >"$WORK/fleet/CODING-FAILURE-MODES.md"
  printf '%s\n' '{"id":"OPS-1"}' >"$STAGE/pipeline/L1/fleet-main.jsonl"
  printf '%s\n' '{"id":"OPS-2"}' '{"id":"CI-1"}' '{"id":"FM-1"}' \
    >"$STAGE/pipeline/L1/fleet-orch.jsonl"
  printf '%s\n' '## FM-001' >"$WORK/claude-codex/docs/integration-failure-modes.md"
  printf '%s\n' '{"id":"FM-001"}' >"$STAGE/pipeline/L1/claude-codex-integration.jsonl"
  printf '%s\n' "CHECK (failure_class IN ('fixture_failure'))" \
    >"$WORK/fleet-dispatch/migrations/0017_failure_class.sql"
}

@test "canonical add scopes reconciliation to homelab-canon and ignores unrelated SHORT drift" {
  make_real_fixture
  trace="$WORK/reconcile-args"
  catalog_before="$(digest "$STAGE/catalog/failure-modes.md")"

  run python3 "$STAGE/pipeline/reconcile_l1_impl.py"
  [ "$status" -eq 1 ]
  [[ "$output" == *"SHORT"* ]]
  [[ "$output" == *"OPS-99"* ]]

  run env CATALOG="$STAGE/catalog/failure-modes.md" CORPUS="$WORK/corpus" \
    RECONCILE_TRACE="$trace" bash "$STAGE/bin/add-failure-mode.sh" -c A \
    "healthy canonical add" --recurrence-of none

  [ "$status" -eq 0 ]
  [ "$(<"$trace")" = $'--source\thomelab-canon' ]
  [ "$(digest "$STAGE/catalog/failure-modes.md")" != "$catalog_before" ]
  grep -Fq '| FM-002 |' "$STAGE/catalog/failure-modes.md"
  [[ "$output" != *"applying undo journal"* ]]
}

@test "selected canonical shortfall still rolls the add back" {
  make_real_fixture
  catalog_before="$(digest "$STAGE/catalog/failure-modes.md")"
  ledger_before="$(digest "$STAGE/catalog/id-ledger.txt")"

  run env CATALOG="$STAGE/catalog/failure-modes.md" CORPUS="$WORK/corpus" \
    LOSSY=1 RECONCILE_TRACE="$WORK/reconcile-args" \
    bash "$STAGE/bin/add-failure-mode.sh" -c A "lossy canonical add" \
    --recurrence-of none

  [ "$status" -ne 0 ]
  [[ "$output" == *"SHORT"* ]]
  [[ "$output" == *"applying undo journal"* ]]
  [ "$(digest "$STAGE/catalog/failure-modes.md")" = "$catalog_before" ]
  [ "$(digest "$STAGE/catalog/id-ledger.txt")" = "$ledger_before" ]
}

@test "full-corpus workflow uses all private sources and fails without its read token" {
  run python3 - "$ROOT/.github/workflows/guard.yml" <<'PY'
import re
import sys
from pathlib import Path

import yaml

workflow = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
jobs = workflow.get("jobs", {})
errors = []
required_repos = {
    "petersimmons1972/fleet",
    "petersimmons1972/fleet-dispatch",
    "petersimmons1972/claude-codex",
}

def steps_for(job):
    return job.get("steps", [])

full_jobs = []
for job_id, job in jobs.items():
    runs = "\n".join(str(step.get("run", "")) for step in steps_for(job))
    if "pipeline/reconcile_l1.py" in runs and "--source" not in runs:
        full_jobs.append((job_id, job, runs))

if not full_jobs:
    errors.append("no separate unscoped full-corpus reconcile job")
else:
    for job_id, job, runs in full_jobs:
        if "--allow-partial" in runs:
            errors.append(f"{job_id}: full-corpus reconcile uses --allow-partial")

private_repos = set()
checkout_tokens = []
candidate_jobs = [entry[1] for entry in full_jobs] or list(jobs.values())
for job in candidate_jobs:
    for step in steps_for(job):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            values = step.get("with", {}) or {}
            repo = values.get("repository")
            if repo:
                private_repos.add(repo)
            checkout_tokens.append(str(values.get("token", "")))

missing_repos = sorted(required_repos - private_repos)
if missing_repos:
    errors.append("missing private sibling checkouts: " + ", ".join(missing_repos))
if not any("secrets.CROSS_REPO_READ_TOKEN" in token for token in checkout_tokens):
    errors.append("no checkout is bound to secrets.CROSS_REPO_READ_TOKEN")

all_runs = "\n".join(
    str(step.get("run", ""))
    for job in jobs.values()
    for step in steps_for(job)
)
if not re.search(r"CROSS_REPO_READ_TOKEN", all_runs) or not re.search(
    r"(?:-z|:-|parameter expansion).*exit 1|exit 1.*(?:-z|:-|parameter expansion)",
    all_runs,
    re.S,
):
    errors.append("missing explicit nonzero failure when CROSS_REPO_READ_TOKEN is absent")

if errors:
    print("\n".join(errors))
    raise SystemExit(1)
PY

  [ "$status" -eq 0 ]
}
