#!/usr/bin/env bats
#
# hindsight#192 — a --supersedes correction must write BOTH sides of the claim.
#
# The exchange tombstoned the target ("SUPERSEDED by FM-NNN") but never wrote the
# reciprocal "Supersedes FM-NNN" onto the superseding row, so the guard the
# exchange runs against its own staging refused every time and --supersedes could
# never publish. Kept in its own file rather than appended to
# test_add_failure_mode.bats, which has an open PR against it.

setup() {
  export TMPDIR="$BATS_TEST_TMPDIR"
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  TOOL="$ROOT/bin/add-failure-mode.sh"
  WORK="$(mktemp -d)"
  CATALOG="$WORK/failure-modes.md"
  CORPUS_DIR="$WORK/corpus"

  cp "$ROOT/catalog/failure-modes.md" "$CATALOG"
  cp "$ROOT/catalog/id-ledger.txt" "$WORK/id-ledger.txt"
  mkdir -p "$CORPUS_DIR"
  printf '%s\n' \
    '{"id":"known-1","instance":"an unrelated fixture row","source_path":"fixture.jsonl"}' \
    >"$CORPUS_DIR/records.jsonl"

  TARGET="$(grep -oE '^\| FM-[0-9]+' "$CATALOG" | tail -n 1 | tr -d '| ')"
}

teardown() {
  rm -rf "$WORK"
}

@test "--supersedes publishes, and the superseding row claims Supersedes on the target" {
  run env CATALOG="$CATALOG" CORPUS="$CORPUS_DIR" \
    bash "$TOOL" --supersedes "$TARGET" -c G -t MEDIUM --disposition advisory \
    --ladder-rung prose-rule --recurrence-of none \
    "a corrected check statement" "a corrected concrete instance"

  # Before the fix this exited 1 with
  #   "supersession mismatch: <target> is tombstoned as SUPERSEDED by <new>,
  #    but <new> does not claim Supersedes <target>"
  # and the exchange rolled back, leaving the catalog unchanged.
  [ "$status" -eq 0 ]

  new_id="$(grep -oE '^\| FM-[0-9]+' "$CATALOG" | tail -n 1 | tr -d '| ')"
  [ "$new_id" != "$TARGET" ]

  # Both sides of the claim are present, on the right rows.
  grep -qE "^\| ${TARGET} \|.*SUPERSEDED by ${new_id} " "$CATALOG"
  grep -qE "^\| ${new_id} \|.*Supersedes ${TARGET} " "$CATALOG"

  # And the guard that refused the staged exchange now accepts the published state.
  run python3 "$ROOT/guard/failure_mode_catalog_guard.py" "$CATALOG"
  [ "$status" -eq 0 ]
}
