#!/usr/bin/env bash
# verify-discriminating.sh — proves that every new/modified test in a branch
# actually discriminates: it must FAIL (or ERROR on an absent dependency) when
# run against the pre-change tree at merge-base. A test that PASSES on the
# unfixed baseline proves nothing (catalogued as CI-18) and is rejected.
#
# Usage: bin/verify-discriminating.sh [--base <ref>] [--scratch-dir <dir>]
set -uo pipefail

BASE_REF="origin/main"
SCRATCH_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      BASE_REF="$2"
      shift 2
      ;;
    --scratch-dir)
      SCRATCH_ROOT="$2"
      shift 2
      ;;
    *)
      echo "verify-discriminating: unknown option: $1" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "verify-discriminating: not inside a git worktree" >&2
  exit 2
}
cd "$REPO_ROOT" || exit 2

if [[ -z "$SCRATCH_ROOT" ]]; then
  SCRATCH_ROOT="$(mktemp -d)"
fi
mkdir -p "$SCRATCH_ROOT"
WORKTREE_DIR="$SCRATCH_ROOT/verify-discriminating-wt"

cleanup() {
  git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1
  rm -rf "$SCRATCH_ROOT"
}
trap cleanup EXIT

MERGE_BASE="$(git merge-base "$BASE_REF" HEAD)" || {
  echo "verify-discriminating: could not compute merge-base with $BASE_REF" >&2
  exit 2
}

# Find test files added or modified between merge-base and HEAD.
# Test files: *.bats, test_*.py, *_test.py, test_*.sh
mapfile -t CHANGED_FILES < <(git diff --name-only --diff-filter=AM "$MERGE_BASE" HEAD)

TEST_FILES=()
for f in "${CHANGED_FILES[@]}"; do
  base="$(basename "$f")"
  case "$base" in
    *.bats) TEST_FILES+=("$f") ;;
    test_*.py) TEST_FILES+=("$f") ;;
    *_test.py) TEST_FILES+=("$f") ;;
    test_*.sh) TEST_FILES+=("$f") ;;
  esac
done

if [[ "${#TEST_FILES[@]}" -eq 0 ]]; then
  echo "verify-discriminating: no new tests to verify (no *.bats, test_*.py, *_test.py, or test_*.sh added or modified since $MERGE_BASE)" >&2
  exit 1
fi

git worktree add --detach --quiet "$WORKTREE_DIR" "$MERGE_BASE" 2>&1 || {
  echo "verify-discriminating: failed to create scratch worktree at $MERGE_BASE" >&2
  exit 2
}

classify_python() {
  local status="$1" out="$2"
  if [[ "$status" -eq 2 ]] || grep -qE '(^|[[:space:]])ERROR(S)?[[:space:]]|error(s)? during collection' <<<"$out"; then
    echo "ERRORED"
  else
    echo "FAILED"
  fi
}

classify_generic() {
  local out="$1"
  if grep -qiE 'no such file or directory|command not found|cannot find' <<<"$out"; then
    echo "ERRORED"
  else
    echo "FAILED"
  fi
}

run_one_test() {
  # Echoes: "<status_word>\n<captured output>" — status_word is PASSED, FAILED, or ERRORED
  local relpath="$1"
  local base
  base="$(basename "$relpath")"
  local out status kind

  pushd "$WORKTREE_DIR" >/dev/null || {
    echo "ERRORED"
    echo "could not enter scratch worktree"
    return
  }

  case "$base" in
    *.bats)
      out="$(bats "$relpath" 2>&1)"
      status=$?
      kind=generic
      ;;
    test_*.sh)
      out="$(bash "$relpath" 2>&1)"
      status=$?
      kind=generic
      ;;
    *)
      out="$(pytest "$relpath" -q 2>&1)"
      status=$?
      kind=python
      ;;
  esac

  popd >/dev/null

  if [[ "$status" -eq 0 ]]; then
    echo "PASSED"
  elif [[ "$kind" == "python" ]]; then
    classify_python "$status" "$out"
  else
    classify_generic "$out"
  fi
  echo "$out"
}

TOTAL=${#TEST_FILES[@]}
DISCRIMINATING=0
NOT_DISCRIMINATING=()

for f in "${TEST_FILES[@]}"; do
  dest="$WORKTREE_DIR/$f"
  mkdir -p "$(dirname "$dest")"
  if ! git show "HEAD:$f" > "$dest" 2>/dev/null; then
    echo "verify-discriminating: could not read $f at HEAD" >&2
    exit 2
  fi

  result="$(run_one_test "$f")"
  verdict="$(head -n1 <<<"$result")"
  detail="$(tail -n +2 <<<"$result")"

  case "$verdict" in
    PASSED)
      echo "$f: PASSED (NOT discriminating — this test also passes on the pre-change tree)"
      NOT_DISCRIMINATING+=("$f")
      ;;
    FAILED)
      echo "$f: FAILED (discriminating — fails on the pre-change tree)"
      DISCRIMINATING=$((DISCRIMINATING + 1))
      ;;
    ERRORED)
      echo "$f: ERRORED (discriminating — absent dependency on the pre-change tree)"
      DISCRIMINATING=$((DISCRIMINATING + 1))
      ;;
  esac
  if [[ "$verdict" != "PASSED" ]]; then
    : # discriminating; detail available above if needed for debugging
  fi
done

echo "discriminating: ${DISCRIMINATING}/${TOTAL}"

if [[ "${#NOT_DISCRIMINATING[@]}" -gt 0 ]]; then
  echo "" >&2
  echo "verify-discriminating: the following test(s) do NOT discriminate (they pass even on the unfixed pre-change tree):" >&2
  for f in "${NOT_DISCRIMINATING[@]}"; do
    echo "  NOT DISCRIMINATING: $f" >&2
  done
  exit 1
fi

exit 0
