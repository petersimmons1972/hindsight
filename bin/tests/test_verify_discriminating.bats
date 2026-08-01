#!/usr/bin/env bats
# Tests for bin/verify-discriminating.sh — the tool that refuses to certify
# a new/modified test unless it actually fails at merge-base. Re-scoped
# design: refuse in every ambiguous case, never classify why something
# failed. See the script's own header comment for the full rationale.
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

# --- core contract: added test, fail vs pass at base ----------------------

@test "T1: added test fails at base -> discriminating, exit 0" {
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

@test "T2: added test passes at base -> refuse, exit 1, names the file" {
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
  # mutation bar (a): a passing-at-base test must never be counted as
  # discriminating.
  [[ "$output" != *"discriminating: 1/1"* ]]
}

@test "T7: modified test still passes at base -> refuse, no exemption" {
  cat > "$FIXTURE/test_helper.py" <<'EOF'
def test_helper():
    assert True
EOF
  git -C "$FIXTURE" add test_helper.py
  git -C "$FIXTURE" commit -q -m "add baseline helper test"

  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_helper.py" <<'EOF'
# cosmetic comment added
def test_helper():
    assert True
EOF
  git -C "$FIXTURE" add test_helper.py
  git -C "$FIXTURE" commit -q -m "cosmetic edit to existing test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"test_helper.py"* ]]
  [[ "$output" != *"discriminating: 1/1"* ]]
}

# --- refuse, never a vacuous pass ------------------------------------------

@test "T3: no test files added or modified -> refuse, never 0/0 pass" {
  git -C "$FIXTURE" checkout -q -b feature
  printf 'NEW\n' > "$FIXTURE/README.md"
  git -C "$FIXTURE" add README.md
  git -C "$FIXTURE" commit -q -m "non-test change only"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  # mutation bar (c): must not become a 0/0 pass.
  [ "$status" -eq 1 ]
  [[ "$output" != *"0/0"* ]]
}

@test "T6: pytest collects zero tests -> refuse, exit 1" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_empty.py" <<'EOF'
# placeholder file with no test functions
EOF
  git -C "$FIXTURE" add test_empty.py
  git -C "$FIXTURE" commit -q -m "add placeholder test file"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"test_empty.py"* ]]
  [[ "$output" != *"discriminating: 1/1"* ]]
}

@test "T6b: bats file with zero @test blocks -> refuse, exit 1" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/empty.bats" <<'EOF'
#!/usr/bin/env bats
# no @test blocks here
EOF
  git -C "$FIXTURE" add empty.bats
  git -C "$FIXTURE" commit -q -m "add placeholder bats file"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [[ "$output" == *"empty.bats"* ]]
  [[ "$output" != *"discriminating: 1/1"* ]]
}

# --- non-python, non-pytest fixtures (round 1/2 only ever used python) ----

@test "T8: added .bats test fails at base -> discriminating, exit 0" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/new.bats" <<'EOF'
#!/usr/bin/env bats
@test "this is red at merge-base" {
  [ -f "$BATS_TEST_DIRNAME/marker.txt" ]
}
EOF
  printf 'present\n' > "$FIXTURE/marker.txt"
  git -C "$FIXTURE" add new.bats marker.txt
  git -C "$FIXTURE" commit -q -m "add discriminating bats test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "T9: added test_*.sh test fails at base -> discriminating, exit 0" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_feature.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[ -f "$(dirname "$0")/feature-flag.txt" ]
EOF
  git -C "$FIXTURE" add test_feature.sh
  git -C "$FIXTURE" commit -q -m "add discriminating shell test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "T9b: *_test.py suffix pattern is detected -> discriminating, exit 0" {
  git -C "$FIXTURE" checkout -q -b feature
  printf 'NEW\n' > "$FIXTURE/README.md"
  cat > "$FIXTURE/readme_test.py" <<'EOF'
def test_readme_updated():
    with open("README.md") as f:
        assert f.read().strip() == "NEW"
EOF
  git -C "$FIXTURE" add README.md readme_test.py
  git -C "$FIXTURE" commit -q -m "suffix-pattern discriminating test"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

# --- runner absent: checked up front, distinct exit code -------------------

@test "T4: required runner (bats) absent -> refuse, distinct exit 3, not miscounted as discriminating" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/new.bats" <<'EOF'
#!/usr/bin/env bats
@test "irrelevant, never actually run" {
  false
}
EOF
  git -C "$FIXTURE" add new.bats
  git -C "$FIXTURE" commit -q -m "add bats test while bats is unavailable"

  # bats-core's own test runner prepends its libexec dir to PATH (which
  # also contains a "bats" executable) in addition to the normal install
  # location, so excluding a single directory is not enough — strip every
  # PATH entry that provides a "bats" binary.
  stripped_path=""
  IFS=':' read -ra parts <<< "$PATH"
  for p in "${parts[@]}"; do
    [[ -x "$p/bats" ]] && continue
    stripped_path="${stripped_path:+$stripped_path:}$p"
  done

  cd "$FIXTURE"
  run env PATH="$stripped_path" bash "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  # mutation bar (d): exit 127 (or a missing runner generally) must never
  # be miscounted as a discriminating result.
  [ "$status" -eq 3 ]
  [[ "$output" != *"discriminating: 1/1"* ]]
}

# --- merge-base tree itself is broken --------------------------------------

@test "T5: merge-base tree is broken (conftest ImportError) -> refuse, exit 4" {
  cat > "$FIXTURE/conftest.py" <<'EOF'
import nonexistent_module_for_verify_discriminating_test
EOF
  git -C "$FIXTURE" add conftest.py
  git -C "$FIXTURE" commit -q -m "base tree has a broken conftest"

  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_new.py" <<'EOF'
def test_new_thing():
    assert True
EOF
  git -C "$FIXTURE" add test_new.py
  git -C "$FIXTURE" commit -q -m "add test on top of a broken base"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 4 ]
}

# --- scratch-dir safety ------------------------------------------------------

@test "T10: --scratch-dir refuses a non-empty pre-existing path" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_trivial.py
  git -C "$FIXTURE" commit -q -m "add trivial test"

  mkdir -p "$SCRATCH"
  printf 'do not touch me\n' > "$SCRATCH/precious.txt"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 2 ]
  [ -f "$SCRATCH/precious.txt" ]
  [[ "$(cat "$SCRATCH/precious.txt")" == "do not touch me" ]]
}

@test "T11: default scratch path (no --scratch-dir) works via mktemp and cleans up" {
  git -C "$FIXTURE" checkout -q -b feature
  printf 'NEW\n' > "$FIXTURE/README.md"
  cat > "$FIXTURE/test_readme.py" <<'EOF'
def test_readme_updated():
    with open("README.md") as f:
        assert f.read().strip() == "NEW"
EOF
  git -C "$FIXTURE" add README.md test_readme.py
  git -C "$FIXTURE" commit -q -m "discriminating test, default scratch path"

  tmproot="$BATS_TEST_TMPDIR/tmproot"
  mkdir -p "$tmproot"

  cd "$FIXTURE"
  TMPDIR="$tmproot" run "$SCRIPT" --base main

  [ "$status" -eq 0 ]
  [[ "$output" == *"discriminating: 1/1"* ]]
  [ -z "$(ls -A "$tmproot" 2>/dev/null)" ]
}

@test "T12: pre-existing empty --scratch-dir: subdir removed, root left behind on SUCCESS" {
  git -C "$FIXTURE" checkout -q -b feature
  printf 'NEW\n' > "$FIXTURE/README.md"
  cat > "$FIXTURE/test_readme.py" <<'EOF'
def test_readme_updated():
    with open("README.md") as f:
        assert f.read().strip() == "NEW"
EOF
  git -C "$FIXTURE" add README.md test_readme.py
  git -C "$FIXTURE" commit -q -m "discriminating test"

  mkdir -p "$SCRATCH"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 0 ]
  [ -d "$SCRATCH" ]
  [ ! -e "$SCRATCH/verify-discriminating-wt" ]
}

@test "T12b: pre-existing empty --scratch-dir: subdir removed, root left behind on REFUSAL" {
  git -C "$FIXTURE" checkout -q -b feature
  cat > "$FIXTURE/test_trivial.py" <<'EOF'
def test_always_true():
    assert True
EOF
  git -C "$FIXTURE" add test_trivial.py
  git -C "$FIXTURE" commit -q -m "non-discriminating test"

  mkdir -p "$SCRATCH"

  cd "$FIXTURE"
  run "$SCRIPT" --base main --scratch-dir "$SCRATCH"

  [ "$status" -eq 1 ]
  [ -d "$SCRATCH" ]
  [ ! -e "$SCRATCH/verify-discriminating-wt" ]
}
