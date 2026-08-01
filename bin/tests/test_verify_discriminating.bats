#!/usr/bin/env bats
# Tests for bin/verify-discriminating.sh — the tool that proves a new test
# actually discriminates (fails pre-change, i.e. would have caught CI-18).
#
# All fixtures are throwaway git repos built fresh in setup(), under
# $BATS_TEST_TMPDIR. Never touch the real hindsight repo's history.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/bin/verify-discriminating.sh"
  FIXTURE="$BATS_TEST_TMPDIR/fixture"
  SCRATCH="$BATS_TEST_TMPDIR/scratch"

  mkdir -p "$FIXTURE"
  git -C "$FIXTURE" init -q -b main
  git -C "$FIXTURE" config user.email test@example.com
  git -C "$FIXTURE" config user.name "Test"
  printf 'OLD\n' > "$FIXTURE/README.md"
  git -C "$FIXTURE" add README.md
  git -C "$FIXTURE" commit -q -m "base commit"
}

@test "T1: added test fails on base and passes on branch -> discriminating" {
  git -C "$FIXTURE" checkout -q -b feature

  printf 'NEW\n' > "$FIXTURE/README.md"
  cat > "$FIXTURE/test_readme.py" <<'EOF'
def test_readme_updated():
    with open("README.md") as f:
        assert f.read().strip() == "NEW"
EOF
  git -C "$FIXTURE" add README.md test_readme.py
  git -C "$FIXTURE" commit -q -m "update readme and add discriminating test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "T2: added test passes on base (asserts true) -> not discriminating, exit 1, names file" {
  git -C "$FIXTURE" checkout -q -b feature

  cat > "$FIXTURE/test_trivial.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_trivial.py
  git -C "$FIXTURE" commit -q -m "add trivial (non-discriminating) test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"test_trivial.py"* ]]
  [[ "$output" == *"discriminating: 0/1"* ]]
}

@test "T3: added test errors on base (imports branch-only module) -> discriminating, reported ERRORED not FAILED" {
  git -C "$FIXTURE" checkout -q -b feature

  cat > "$FIXTURE/test_needs_new_module.py" <<'EOF'
import new_branch_only_module

def test_uses_new_module():
    assert new_branch_only_module.value() == 42
EOF
  git -C "$FIXTURE" add test_needs_new_module.py
  git -C "$FIXTURE" commit -q -m "add test that depends on a branch-only module"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
  [[ "$output" == *"test_needs_new_module.py: ERRORED"* ]]
  [[ "$output" != *"test_needs_new_module.py: FAILED"* ]]
}

@test "T4: branch changes only non-test files -> exit 1, 'no new tests to verify', never 0/0" {
  git -C "$FIXTURE" checkout -q -b feature

  printf 'OLD\nmore docs\n' > "$FIXTURE/README.md"
  git -C "$FIXTURE" add README.md
  git -C "$FIXTURE" commit -q -m "docs-only change"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"no new tests to verify"* ]]
  [[ "$output" != *"discriminating: 0/0"* ]]
}

@test "T5: two added tests, one discriminating and one not -> exit 1, names ONLY the non-discriminating one" {
  git -C "$FIXTURE" checkout -q -b feature

  cat > "$FIXTURE/test_good.py" <<'EOF'
def test_fails_on_base():
    assert 1 + 1 == 3
EOF
  cat > "$FIXTURE/test_bad.py" <<'EOF'
def test_always_passes():
    assert True
EOF
  git -C "$FIXTURE" add test_good.py test_bad.py
  git -C "$FIXTURE" commit -q -m "add one discriminating and one non-discriminating test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"discriminating: 1/2"* ]]
  [[ "$output" == *"test_bad.py: PASSED"* ]]
  [[ "$output" != *"test_good.py: PASSED"* ]]
}

@test "T6: modifying an existing test so it now fails on base -> discriminating (modified counts too)" {
  # test_existing.py is committed to main BEFORE branching, so it is part
  # of the merge-base — this exercises the "modified", not just "added", path.
  cat > "$FIXTURE/test_existing.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_existing.py
  git -C "$FIXTURE" commit -q -m "add initially-trivial test to main"

  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_existing.py" <<'EOF'
def test_readme_is_long():
    with open("README.md") as f:
        assert len(f.read()) > 100
EOF
  git -C "$FIXTURE" add test_existing.py
  git -C "$FIXTURE" commit -q -m "modify existing test to be discriminating"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "T7: scratch worktree is removed afterward, including when the run exits 1" {
  git -C "$FIXTURE" checkout -q -b feature

  cat > "$FIXTURE/test_trivial2.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_trivial2.py
  git -C "$FIXTURE" commit -q -m "add non-discriminating test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [ ! -d "$SCRATCH" ]
}
