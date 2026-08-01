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

@test "T8: --scratch-dir pointing at a pre-existing non-empty directory is refused, never deleted" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_trivial.py
  git -C "$FIXTURE" commit -q -m "add test"

  PRECIOUS="$BATS_TEST_TMPDIR/precious"
  mkdir -p "$PRECIOUS/important-subdir"
  echo 'PRECIOUS DATA' > "$PRECIOUS/keepme.txt"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$PRECIOUS"

  [ "$status" -ne 0 ]
  [ "$status" -ne 1 ]
  [ -f "$PRECIOUS/keepme.txt" ]
  [ -d "$PRECIOUS/important-subdir" ]
  [ "$(cat "$PRECIOUS/keepme.txt")" = "PRECIOUS DATA" ]
}

@test "T9: an empty pre-existing --scratch-dir is used, and only the created subdir is removed afterward" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_trivial.py
  git -C "$FIXTURE" commit -q -m "add test"

  EMPTYDIR="$BATS_TEST_TMPDIR/empty-scratch"
  mkdir -p "$EMPTYDIR"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$EMPTYDIR"

  [ "$status" -eq 1 ]
  # the pre-existing directory itself must survive (we didn't create it)
  [ -d "$EMPTYDIR" ]
  # but the worktree subdir created inside it must be gone
  [ ! -d "$EMPTYDIR/verify-discriminating-wt" ]
}

@test "T10: pytest absent (PATH stripped) aborts loudly, distinct exit code, never certifies" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_trivial.py
  git -C "$FIXTURE" commit -q -m "add trivial non-discriminating test"

  cd "$FIXTURE"
  run env PATH=/usr/bin:/bin "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -ne 0 ]
  [ "$status" -ne 1 ]
  [[ "$output" != *"discriminating: 1/1"* ]]
  [[ "$output" == *"pytest"* ]]
}

@test "T11: bats absent (PATH stripped) aborts loudly, distinct exit code, never certifies" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial.bats" <<'EOF'
#!/usr/bin/env bats
@test "always true" {
  [ 1 -eq 1 ]
}
EOF
  git -C "$FIXTURE" add test_trivial.bats
  git -C "$FIXTURE" commit -q -m "add non-discriminating bats test"

  cd "$FIXTURE"
  run env PATH=/usr/bin:/bin "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -ne 0 ]
  [ "$status" -ne 1 ]
  [[ "$output" != *"discriminating: 1/1"* ]]
  [[ "$output" == *"bats"* ]]
}

@test "T12: zero collected tests (empty placeholder file) is an ERROR, never a silent pass" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_empty.py" <<'EOF'
# TODO: write tests
EOF
  git -C "$FIXTURE" add test_empty.py
  git -C "$FIXTURE" commit -q -m "add placeholder test file with zero tests"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -ne 0 ]
  [[ "$output" != *"discriminating: 1/1"* ]]
  [[ "$output" == *"test_empty.py"* ]]
}

@test "T13: broken merge-base tree (unrelated conftest ImportError) refuses to certify" {
  cat > "$FIXTURE/conftest.py" <<'EOF'
import totally_missing_module_xyz
EOF
  git -C "$FIXTURE" add conftest.py
  git -C "$FIXTURE" commit -q -m "pre-existing broken conftest on main (unrelated bug)"

  git -C "$FIXTURE" checkout -q -b feature
  printf '' > "$FIXTURE/conftest.py"
  cat > "$FIXTURE/test_trivial.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add conftest.py test_trivial.py
  git -C "$FIXTURE" commit -q -m "fix conftest and add trivial test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -ne 0 ]
  [ "$status" -ne 1 ]
  [[ "$output" != *"discriminating: 1/1"* ]]
}

@test "T14: a genuinely discriminating .bats test is recognized and counted" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_feature.bats" <<'EOF'
#!/usr/bin/env bats
@test "readme says NEW" {
  grep -q NEW README.md
}
EOF
  printf 'NEW\n' > "$FIXTURE/README.md"
  git -C "$FIXTURE" add README.md test_feature.bats
  git -C "$FIXTURE" commit -q -m "add discriminating bats test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "T15: a non-discriminating .bats test (always passes) is rejected, named, exit 1" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial3.bats" <<'EOF'
#!/usr/bin/env bats
@test "always true" {
  [ 1 -eq 1 ]
}
EOF
  git -C "$FIXTURE" add test_trivial3.bats
  git -C "$FIXTURE" commit -q -m "add non-discriminating bats test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"test_trivial3.bats"* ]]
  [[ "$output" == *"discriminating: 0/1"* ]]
}

@test "T16: a genuinely discriminating test_*.sh test is recognized and counted" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_feature.sh" <<'EOF'
#!/usr/bin/env bash
set -e
grep -q NEW README.md
EOF
  printf 'NEW\n' > "$FIXTURE/README.md"
  git -C "$FIXTURE" add README.md test_feature.sh
  git -C "$FIXTURE" commit -q -m "add discriminating sh test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "T17: a non-discriminating test_*.sh test (always passes) is rejected, named, exit 1" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial4.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  git -C "$FIXTURE" add test_trivial4.sh
  git -C "$FIXTURE" commit -q -m "add non-discriminating sh test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"test_trivial4.sh"* ]]
  [[ "$output" == *"discriminating: 0/1"* ]]
}

@test "T18: ERRORED reason reflects the observed cause, not a hardcoded phrase" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_syntaxerr.py" <<'EOF'
def test_broken(:
EOF
  git -C "$FIXTURE" add test_syntaxerr.py
  git -C "$FIXTURE" commit -q -m "add test file with a syntax error (no absent dependency at all)"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
  [[ "$output" == *"test_syntaxerr.py: ERRORED"* ]]
  [[ "$output" != *"absent dependency on the pre-change tree"* ]]
  [[ "$output" == *"SyntaxError"* ]]
}

@test "T19: cosmetic edit to an already-passing test file does not block a PR with a genuinely discriminating new test" {
  cat > "$FIXTURE/test_unrelated.py" <<'EOF'
def test_arith():
    assert 2 + 2 == 4
EOF
  git -C "$FIXTURE" add test_unrelated.py
  git -C "$FIXTURE" commit -q -m "add already-passing test to main"

  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_unrelated.py" <<'EOF'
def test_arith():
    """docstring only change, cosmetic."""
    assert 2 + 2 == 4
EOF
  cat > "$FIXTURE/test_new_feature.py" <<'EOF'
def test_readme_updated():
    with open("README.md") as f:
        assert f.read().strip() == "NEW"
EOF
  printf 'NEW\n' > "$FIXTURE/README.md"
  git -C "$FIXTURE" add test_unrelated.py test_new_feature.py README.md
  git -C "$FIXTURE" commit -q -m "cosmetic docstring + genuinely discriminating new test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"test_new_feature.py: FAILED"* ]]
}

@test "T20: missing argument to --base exits with a distinct usage-error code, not a bash crash" {
  git -C "$FIXTURE" checkout -q -b feature
  cd "$FIXTURE"
  run "$SCRIPT" --base

  [ "$status" -eq 2 ]
  [[ "$output" != *"unbound variable"* ]]
}

@test "T21: missing argument to --scratch-dir exits with a distinct usage-error code, not a bash crash" {
  git -C "$FIXTURE" checkout -q -b feature
  cd "$FIXTURE"
  run "$SCRIPT" --scratch-dir

  [ "$status" -eq 2 ]
  [[ "$output" != *"unbound variable"* ]]
}
