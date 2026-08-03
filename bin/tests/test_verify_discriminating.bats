#!/usr/bin/env bats
# Attack specification for the HEAD-hunk-reversion discriminator.  These tests
# construct fresh repositories: no fixture changes the Hindsight checkout.

if [[ -z ${BATS_VERSION:-} ]]; then
  exec bats "$0"
fi

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$ROOT/bin/verify-discriminating.sh"
  REPO="$BATS_TEST_TMPDIR/repo"
  git init -q -b main "$REPO"
  git -C "$REPO" config user.email test@example.com
  git -C "$REPO" config user.name Test
  printf 'old\n' > "$REPO/value.txt"
  git -C "$REPO" add value.txt
  git -C "$REPO" commit -qm base
  git -C "$REPO" switch -qc feature
}

commit_fixture() { git -C "$REPO" add -A && git -C "$REPO" commit -qm fixture; }
run_verify() { run bash -c 'cd "$1" || exit; shift; exec "$@"' _ "$REPO" bash "$SCRIPT" --base main; }

@test "D1: reverts a changed implementation hunk at HEAD and certifies a behavioral test" {
  printf 'new\n' > "$REPO/value.txt"
  cat > "$REPO/test_value.py" <<'EOF'
def test_value():
    assert open("value.txt").read().strip() == "new"
EOF
  commit_fixture
  run_verify
  [ "$status" -eq 0 ]
  [[ "$output" == *"test_value.py: FAILED (discriminating"* ]]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "D2: names a test that still passes after implementation reversion" {
  printf 'new\n' > "$REPO/value.txt"
  cat > "$REPO/test_trivial.py" <<'EOF'
def test_trivial(): assert True
EOF
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"test_trivial.py: PASSED"* ]]
}

@test "D3: import-only red is rejected rather than certified" {
  cat > "$REPO/new_module.py" <<'EOF'
VALUE = 42
EOF
  cat > "$REPO/test_import_only.py" <<'EOF'
import new_module
def test_import_only(): assert new_module.VALUE == 42
EOF
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"test_import_only.py: IMPORT_CONFOUND"* ]]
  [[ "$output" == *"discriminating: 0/1"* ]]
}

@test "D4: no changed tests fails loudly rather than passing 0/0" {
  printf 'documentation only\n' >> "$REPO/value.txt"
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"no new tests"* ]]
  [[ "$output" != *"discriminating: 0/0"* ]]
}

@test "D5: a renamed and edited test is detected" {
  cat > "$REPO/test_old.py" <<'EOF'
def test_value(): assert open("value.txt").read().strip() == "old"
EOF
  git -C "$REPO" add test_old.py && git -C "$REPO" commit -qm old-test
  git -C "$REPO" mv test_old.py test_renamed.py
  sed -i 's/"old"/"new"/' "$REPO/test_renamed.py"
  printf 'new\n' > "$REPO/value.txt"
  commit_fixture
  run_verify
  [ "$status" -eq 0 ]
  [[ "$output" == *"test_renamed.py"* ]]
}

@test "D6: symlinked test files are rejected without execution" {
  ln -s ../value.txt "$REPO/test_link.py"
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"test_link.py: SYMLINK"* ]]
}

@test "D7: non-glob changes are reported, never silently ignored" {
  printf 'new\n' > "$REPO/value.txt"
  cat > "$REPO/check_feature.py" <<'EOF'
def test_value(): assert open("value.txt").read().strip() == "new"
EOF
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"unrecognized changed file: check_feature.py"* ]]
}

@test "D8: land wiring is load-bearing" {
  grep -q 'verify-discriminating.sh' "$ROOT/bin/land.sh"
}
