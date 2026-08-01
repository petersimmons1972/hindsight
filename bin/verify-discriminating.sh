#!/usr/bin/env bash
# verify-discriminating.sh — proves that every new/modified test in a branch
# actually discriminates: it must FAIL (or ERROR on an absent dependency) when
# run against the pre-change tree at merge-base. A test that PASSES on the
# unfixed baseline proves nothing (catalogued as CI-18) and is rejected.
#
# Usage: bin/verify-discriminating.sh [--base <ref>] [--scratch-dir <dir>]
#
# Exit codes:
#   0  every relevant test discriminates — gate passes
#   1  a legitimate gate rejection (a test does not discriminate, zero tests
#      were collected, or no new/modified test files were found)
#   2  usage error: bad invocation, not a git worktree, unresolvable
#      merge-base, an unreadable file at HEAD, or an unsafe --scratch-dir
#   3  the environment cannot run its own test runner (pytest/bats missing,
#      or a runner exits 127) — this gate refuses to silently pass when it
#      cannot actually execute a test
#   4  the merge-base tree itself is broken for a reason unrelated to the
#      change under test (e.g. a conftest.py ImportError) — refuses to
#      certify against a tree it cannot trust
set -uo pipefail

BASE_REF="origin/main"
SCRATCH_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      if [[ $# -lt 2 ]]; then
        echo "verify-discriminating: --base requires an argument" >&2
        exit 2
      fi
      BASE_REF="$2"
      shift 2
      ;;
    --scratch-dir)
      if [[ $# -lt 2 ]]; then
        echo "verify-discriminating: --scratch-dir requires an argument" >&2
        exit 2
      fi
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

# --- scratch-dir handling -----------------------------------------------
# --scratch-dir is user-supplied. We must never delete anything we did not
# create ourselves. If the caller points us at an existing non-empty
# directory we refuse outright rather than risk destroying its contents.
CREATED_SCRATCH_ROOT=false

if [[ -z "$SCRATCH_ROOT" ]]; then
  SCRATCH_ROOT="$(mktemp -d)"
  CREATED_SCRATCH_ROOT=true
else
  if [[ -e "$SCRATCH_ROOT" && ! -d "$SCRATCH_ROOT" ]]; then
    echo "verify-discriminating: --scratch-dir $SCRATCH_ROOT exists and is not a directory; refusing to proceed" >&2
    exit 2
  fi
  if [[ -d "$SCRATCH_ROOT" ]]; then
    if [[ -n "$(ls -A "$SCRATCH_ROOT" 2>/dev/null)" ]]; then
      echo "verify-discriminating: --scratch-dir $SCRATCH_ROOT already exists and is not empty; refusing to use it (this tool only ever removes what it creates itself, so it will not touch pre-existing content — point it at an empty or nonexistent directory instead)" >&2
      exit 2
    fi
    CREATED_SCRATCH_ROOT=false
  else
    mkdir -p "$SCRATCH_ROOT"
    CREATED_SCRATCH_ROOT=true
  fi
fi

WORKTREE_DIR="$SCRATCH_ROOT/verify-discriminating-wt"

cleanup() {
  if [[ -d "$WORKTREE_DIR" ]] || git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | grep -qF "worktree $WORKTREE_DIR"; then
    echo "verify-discriminating: removing scratch worktree $WORKTREE_DIR" >&2
    git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1
  fi
  if [[ "$CREATED_SCRATCH_ROOT" == "true" ]]; then
    echo "verify-discriminating: removing scratch root $SCRATCH_ROOT (created by this run)" >&2
    rm -rf "$SCRATCH_ROOT"
  else
    echo "verify-discriminating: removing only $WORKTREE_DIR (leaving the rest of $SCRATCH_ROOT untouched — this run did not create it)" >&2
    rm -rf "$WORKTREE_DIR"
  fi
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
TEST_KINDS=()
for f in "${CHANGED_FILES[@]}"; do
  base="$(basename "$f")"
  case "$base" in
    *.bats) TEST_FILES+=("$f"); TEST_KINDS+=("bats") ;;
    test_*.py) TEST_FILES+=("$f"); TEST_KINDS+=("python") ;;
    *_test.py) TEST_FILES+=("$f"); TEST_KINDS+=("python") ;;
    test_*.sh) TEST_FILES+=("$f"); TEST_KINDS+=("sh") ;;
  esac
done

if [[ "${#TEST_FILES[@]}" -eq 0 ]]; then
  echo "verify-discriminating: no new tests to verify (no *.bats, test_*.py, *_test.py, or test_*.sh added or modified since $MERGE_BASE)" >&2
  exit 1
fi

HAS_PYTHON=false
HAS_BATS=false
for k in "${TEST_KINDS[@]}"; do
  [[ "$k" == "python" ]] && HAS_PYTHON=true
  [[ "$k" == "bats" ]] && HAS_BATS=true
done

# --- runner preflight: fail loud, never fail open -----------------------
# A gate that cannot run its own runner must abort, not silently pass.
if [[ "$HAS_BATS" == "true" ]] && ! command -v bats >/dev/null 2>&1; then
  echo "verify-discriminating: required test runner 'bats' is not installed or not on PATH — refusing to certify (this would otherwise fail-open: a missing runner must never be treated as a passing/discriminating result)" >&2
  exit 3
fi

if [[ "$HAS_PYTHON" == "true" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "verify-discriminating: required interpreter 'python3' is not installed or not on PATH — refusing to certify" >&2
    exit 3
  fi
  if ! python3 -m pytest --version >/dev/null 2>&1; then
    echo "verify-discriminating: 'python3 -m pytest' is not available (pytest not installed for this interpreter) — refusing to certify" >&2
    exit 3
  fi
fi

git worktree add --detach --quiet "$WORKTREE_DIR" "$MERGE_BASE" || {
  echo "verify-discriminating: failed to create scratch worktree at $MERGE_BASE" >&2
  exit 2
}

# --- merge-base sanity check --------------------------------------------
# If the pre-change tree itself is broken for a reason unrelated to the
# change under test (e.g. a conftest.py ImportError), every test file would
# spuriously appear to "fail on base" and the whole PR would be rubber-
# stamped. Refuse to certify against a base we can't trust.
if [[ "$HAS_PYTHON" == "true" ]]; then
  base_check_out="$(cd "$WORKTREE_DIR" && python3 -m pytest --collect-only -q 2>&1)"
  base_check_status=$?
  if [[ "$base_check_status" -eq 4 ]] || grep -qE 'ImportError while loading conftest' <<<"$base_check_out"; then
    reason="$(grep -m1 -E 'Error|ImportError' <<<"$base_check_out")"
    echo "verify-discriminating: the merge-base tree ($MERGE_BASE) is broken independent of this change and cannot be trusted to verify anything against — refusing to certify. Observed: ${reason:-$base_check_out}" >&2
    exit 4
  fi
fi

classify_python() {
  local status="$1" out="$2"
  if [[ "$status" -eq 127 ]]; then
    echo "RUNNER_ABSENT"
  elif [[ "$status" -eq 5 ]]; then
    echo "EMPTY"
  elif [[ "$status" -eq 2 ]] || grep -qE '(^|[[:space:]])ERROR(S)?[[:space:]]|error(s)? during collection' <<<"$out"; then
    echo "ERRORED"
  else
    echo "FAILED"
  fi
}

classify_generic() {
  local status="$1" out="$2"
  if [[ "$status" -eq 127 ]]; then
    echo "RUNNER_ABSENT"
  elif grep -qiE 'no such file or directory|command not found|cannot find' <<<"$out"; then
    echo "ERRORED"
  else
    echo "FAILED"
  fi
}

# Extract a short, real reason from a test's captured output rather than a
# fixed guess. Best-effort: prefer a concrete error line, fall back to the
# last non-blank line.
extract_reason() {
  local out="$1"
  local line
  line="$(grep -m1 -E 'Error:|Error while|SyntaxError|ModuleNotFoundError|ImportError|command not found|No such file or directory' <<<"$out")"
  if [[ -z "$line" ]]; then
    line="$(grep -vE '^[[:space:]]*$' <<<"$out" | tail -n1)"
  fi
  # trim leading/trailing whitespace and cap length
  line="$(sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' <<<"$line")"
  echo "${line:0:200}"
}

run_one_test() {
  # Echoes: "<status_word>\n<captured output>" — status_word is PASSED,
  # FAILED, ERRORED, EMPTY, or RUNNER_ABSENT.
  local relpath="$1" kind="$2"
  local out status verdict

  pushd "$WORKTREE_DIR" >/dev/null || {
    echo "ERRORED"
    echo "could not enter scratch worktree"
    return
  }

  case "$kind" in
    bats)
      out="$(bats "$relpath" 2>&1)"
      status=$?
      ;;
    sh)
      out="$(bash "$relpath" 2>&1)"
      status=$?
      ;;
    python)
      out="$(python3 -m pytest "$relpath" -q 2>&1)"
      status=$?
      ;;
  esac

  popd >/dev/null || {
    echo "ERRORED"
    echo "failed to return from scratch worktree"
    return
  }

  if [[ "$status" -eq 0 ]]; then
    verdict="PASSED"
  elif [[ "$kind" == "python" ]]; then
    verdict="$(classify_python "$status" "$out")"
  else
    verdict="$(classify_generic "$status" "$out")"
  fi
  echo "$verdict"
  echo "$out"
}

TOTAL=0
DISCRIMINATING=0
BLOCKING=()      # verdicts that must reject the whole run
INFO_ONLY=()     # informational, non-blocking (cosmetic modified-passing)

for i in "${!TEST_FILES[@]}"; do
  f="${TEST_FILES[$i]}"
  kind="${TEST_KINDS[$i]}"
  dest="$WORKTREE_DIR/$f"
  mkdir -p "$(dirname "$dest")"
  if ! git show "HEAD:$f" > "$dest" 2>/dev/null; then
    echo "verify-discriminating: could not read $f at HEAD" >&2
    exit 2
  fi

  # is this file new relative to merge-base, or an edit to an existing file?
  is_modified=false
  if git cat-file -e "$MERGE_BASE:$f" 2>/dev/null; then
    is_modified=true
  fi

  result="$(run_one_test "$f" "$kind")"
  verdict="$(head -n1 <<<"$result")"
  detail="$(tail -n +2 <<<"$result")"

  case "$verdict" in
    RUNNER_ABSENT)
      echo "verify-discriminating: test runner became unavailable (exit 127) while running $f — refusing to certify" >&2
      exit 3
      ;;
    PASSED)
      if [[ "$is_modified" == "true" ]]; then
        echo "$f: PASSED (modified, not discriminating — this test already passed on the pre-change tree; likely a cosmetic edit, not blocking)"
        INFO_ONLY+=("$f")
      else
        echo "$f: PASSED (NOT discriminating — this test also passes on the pre-change tree)"
        BLOCKING+=("$f: added, not discriminating")
        TOTAL=$((TOTAL + 1))
      fi
      ;;
    EMPTY)
      echo "$f: EMPTY (zero tests collected on the pre-change tree — a placeholder proves nothing and cannot be discriminating)"
      BLOCKING+=("$f: zero tests collected")
      TOTAL=$((TOTAL + 1))
      ;;
    FAILED)
      echo "$f: FAILED (discriminating — fails on the pre-change tree)"
      DISCRIMINATING=$((DISCRIMINATING + 1))
      TOTAL=$((TOTAL + 1))
      ;;
    ERRORED)
      reason="$(extract_reason "$detail")"
      echo "$f: ERRORED (discriminating — ${reason:-error on the pre-change tree})"
      DISCRIMINATING=$((DISCRIMINATING + 1))
      TOTAL=$((TOTAL + 1))
      ;;
  esac
done

echo "discriminating: ${DISCRIMINATING}/${TOTAL}"

if [[ "${#INFO_ONLY[@]}" -gt 0 ]]; then
  echo "" >&2
  echo "verify-discriminating: the following modified test(s) already passed on the pre-change tree (not discriminating, but not blocking — likely cosmetic):" >&2
  for f in "${INFO_ONLY[@]}"; do
    echo "  INFO (non-blocking): $f" >&2
  done
fi

if [[ "${#BLOCKING[@]}" -gt 0 ]]; then
  echo "" >&2
  echo "verify-discriminating: the following test(s) do NOT discriminate and block this PR:" >&2
  for f in "${BLOCKING[@]}"; do
    echo "  BLOCKING: $f" >&2
  done
  exit 1
fi

exit 0
