#!/usr/bin/env bats
# Attack + acceptance suite for the supported-shape discriminating gate (#23).
# Fresh mini-repos only — never mutates the hindsight checkout.

if [[ -z ${BATS_VERSION:-} ]]; then
  exec bats "$0"
fi

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="${VERIFY_SCRIPT:-$ROOT/bin/verify-discriminating.sh}"
  REPO="$BATS_TEST_TMPDIR/repo"
  git init -q -b main "$REPO"
  git -C "$REPO" config user.email test@example.com
  git -C "$REPO" config user.name Test
  printf 'old\n' >"$REPO/value.txt"
  git -C "$REPO" add value.txt
  git -C "$REPO" commit -qm base
  git -C "$REPO" switch -qc feature
  # Gate script is invoked by absolute path; mini-repo is the subject.
  cp "$SCRIPT" "$REPO/verify-discriminating.sh"
  chmod +x "$REPO/verify-discriminating.sh"
}

commit_fixture() {
  git -C "$REPO" add -A
  git -C "$REPO" commit -qm fixture
}

run_verify() {
  run env -C "$REPO" bash ./verify-discriminating.sh --base main
}

@test "D1: behavioral pytest after impl reversion is certified discriminating" {
  printf 'new\n' >"$REPO/value.txt"
  cat >"$REPO/test_value.py" <<'EOF'
def test_value():
    assert open("value.txt").read().strip() == "new"
EOF
  commit_fixture
  run_verify
  [ "$status" -eq 0 ]
  [[ "$output" == *"test_value.py: FAILED (discriminating"* ]]
  [[ "$output" == *"discriminating: 1/1"* ]]
}

@test "D2: trivial always-green test is rejected by name" {
  printf 'new\n' >"$REPO/value.txt"
  cat >"$REPO/test_trivial.py" <<'EOF'
def test_trivial():
    assert True
EOF
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"test_trivial.py: PASSED"* ]]
}

@test "D3: added-module import shape is refused up front (not certified)" {
  cat >"$REPO/new_module.py" <<'EOF'
VALUE = 42
EOF
  cat >"$REPO/test_import_only.py" <<'EOF'
import new_module

def test_import_only():
    assert new_module.VALUE == 42
EOF
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"UNSUPPORTED_SHAPE"* ]]
  [[ "$output" == *"added-module"* ]]
  [[ "$output" != *"discriminating: 1/"* ]]
}

@test "D4: no changed tests fails loudly (never 0/0 pass)" {
  printf 'docs only\n' >>"$REPO/value.txt"
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"no new tests"* ]]
  [[ "$output" != *"discriminating: 0/0"* ]]
}

@test "D5: rename-plus-edit of a test is still detected" {
  git -C "$REPO" switch -q main
  # Long body so git records rename after one-line edit.
  {
    echo 'def test_body():'
    echo '    x = open("value.txt").read().strip()'
    for i in $(seq 1 40); do
      echo "    # pad $i"
    done
    echo '    assert x == "old"'
  } >"$REPO/test_old.py"
  git -C "$REPO" add test_old.py
  git -C "$REPO" commit -qm add-test
  # Bring the test onto feature before renaming (feature branched before add-test).
  git -C "$REPO" switch -q feature
  git -C "$REPO" merge -q main -m 'sync main'
  git -C "$REPO" mv test_old.py test_renamed.py
  printf 'new\n' >"$REPO/value.txt"
  python3 -c "
from pathlib import Path
p = Path(r'''$REPO''') / 'test_renamed.py'
p.write_text(p.read_text().replace('assert x == \"old\"', 'assert x == \"new\"'))
"
  commit_fixture
  run_verify
  [ "$status" -eq 0 ]
  [[ "$output" == *"test_renamed.py: FAILED (discriminating"* ]]
}

@test "unsupported unstructured shell test is refused" {
  cat >"$REPO/test_loose.sh" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
  chmod +x "$REPO/test_loose.sh"
  printf 'new\n' >"$REPO/value.txt"
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"UNSUPPORTED_SHAPE"* ]]
  [[ "$output" == *"unstructured-shell"* ]]
}

@test "symlink test is refused" {
  printf 'new\n' >"$REPO/value.txt"
  cat >"$REPO/real_test.py" <<'EOF'
def test_real():
    assert open("value.txt").read().strip() == "new"
EOF
  ln -s real_test.py "$REPO/test_link.py"
  commit_fixture
  run_verify
  [ "$status" -eq 1 ]
  [[ "$output" == *"UNSUPPORTED_SHAPE"* ]]
  [[ "$output" == *"symlink"* ]]
}
