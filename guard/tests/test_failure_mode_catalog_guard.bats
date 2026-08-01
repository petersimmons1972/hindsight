#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  TMPDIR="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR"
}

@test "repo-local pre-commit hook validates the canonical catalog" {
  run "$REPO_ROOT/.githooks/pre-commit"
  [ "$status" -eq 0 ]
  [[ "$output" == *"failure-mode-catalog: OK"* ]]
}

@test "guard rejects duplicate canonical IDs" {
  catalog="$TMPDIR/failure-modes-standard.md"
  cat >"$catalog" <<'EOF'
| ID | Bug class | Concrete instance | Check that catches it | Auto? |
|----|-----------|-------------------|-----------------------|-------|
| FM-01 | Example | one | one | Judgment |
| FM-01 | Example | two | two | Judgment |
EOF

  run python3 "$REPO_ROOT/guard/failure_mode_catalog_guard.py" "$catalog"
  [ "$status" -ne 0 ]
  [[ "$output" == *"duplicate canonical ID FM-01"* ]]
}
