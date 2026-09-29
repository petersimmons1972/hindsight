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

@test "repo-local pre-commit rejects a catalog change when L2 replay fails" {
  repo="$TMPDIR/repo"
  fake_bin="$TMPDIR/bin"
  fake_python_log="$TMPDIR/python.log"
  mkdir -p "$repo/.githooks" "$repo/bin" "$repo/catalog" "$repo/pipeline/L1" \
    "$repo/pipeline/L2" "$fake_bin"
  cp "$REPO_ROOT/.githooks/pre-commit" "$repo/.githooks/pre-commit"
  cp "$REPO_ROOT/bin/verify-hook-worktree.sh" "$repo/bin/verify-hook-worktree.sh"
  chmod +x "$repo/.githooks/pre-commit"

  printf 'baseline\n' >"$repo/catalog/failure-modes.md"
  : >"$repo/catalog/id-ledger.txt"
  : >"$repo/catalog/criticality.jsonl"
  : >"$repo/pipeline/L1/homelab-canon.jsonl"
  : >"$repo/pipeline/L2/embedding-snapshot.json"
  : >"$repo/pipeline/L2/clusters.jsonl"

  git -C "$repo" init -q
  git -C "$repo" add .
  git -C "$repo" -c user.name=test -c user.email=test@example.invalid commit -qm baseline
  printf 'changed\n' >"$repo/catalog/failure-modes.md"

  cat >"$fake_bin/python3" <<'EOF'
#!/usr/bin/env sh
printf '%s\n' "$*" >>"${FAKE_PYTHON_LOG:?}"
case "$1" in
  */pipeline/replay_l2.py)
    printf 'replay-l2: error: partition mismatch\n' >&2
    exit 1
    ;;
esac
EOF
  chmod +x "$fake_bin/python3"

  run bash -c 'cd "$1" && PATH="$2:$PATH" FAKE_PYTHON_LOG="$3" bash "$4"' \
    _ "$repo" "$fake_bin" "$fake_python_log" "$repo/.githooks/pre-commit"
  [ "$status" -ne 0 ]
  [[ "$output" == *"replay-l2: error: partition mismatch"* ]]
  grep -Fq "$repo/pipeline/replay_l2.py" "$fake_python_log"
  grep -Fq 'pipeline/L2/embedding-snapshot.json' "$repo/.githooks/pre-commit"
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
