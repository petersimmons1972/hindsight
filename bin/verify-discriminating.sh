#!/usr/bin/env bash
# verify-discriminating.sh — refuses, it does not adjudicate.
#
# Contract: prove that every test file added or modified since merge-base
# FAILS (nonzero exit) when run against the merge-base tree. That is the
# whole job. This script deliberately does NOT try to explain *why* a test
# failed at merge-base, does not distinguish an assertion failure from an
# import error from a missing binary, and does not treat "added" and
# "modified" test files differently. Two build->adversarial-verify rounds
# tried to classify that taxonomy (FAILED vs ERRORED vs EMPTY vs
# RUNNER_ABSENT vs modified-vs-added) and each round produced a fresh crop
# of HIGH-severity inversions, including a silent 0/0 clean pass and a
# RUNNER_ABSENT sentinel that misread a legitimate shell-TDD red proof as an
# environment failure. The diagnosis: the design was too ambitious, not
# that the code was bad. So: every ambiguous case below REFUSES rather than
# guesses. A false rejection costs a human a minute of reading the raw
# exit code and stderr line printed below. A false acceptance is the exact
# failure family this repository exists to catalogue. DO NOT "helpfully"
# soften any refusal below into a pass, an exemption, or a classification
# — that is exactly how round 2 happened. When in doubt, exit non-zero.
#
# Usage: bin/verify-discriminating.sh [--base <ref>] [--scratch-dir <dir>]
#
# Exit codes:
#   0  every added/modified test file discriminates (fails at merge-base)
#   1  gate rejection: no test files were added/modified at all, a test
#      file passed (or reported zero collected/executed tests) at the
#      merge-base — this is a REJECTION of the change under test, never a
#      usage problem
#   2  usage error: bad flags, not inside a git worktree, unresolvable
#      merge-base, an unreadable file at HEAD, or an unsafe --scratch-dir
#   3  a required test runner (bats / python3+pytest / bash) is missing —
#      checked up front, before running anything, because a missing runner
#      must never be silently treated as a passing or discriminating result
#   4  the merge-base tree itself fails a trivially-passing probe test of
#      its own — refuses to trust any per-file verdict produced against a
#      base that can't even pass a test known to pass
#
# Only the final "discriminating: N/M" line goes to stdout. Everything
# else — including every git error — goes to stderr, so the dispatch
# ledger can parse stdout as a clean machine-readable stream.
set -uo pipefail

BASE_REF="origin/main"
SCRATCH_ROOT_ARG=""

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
      SCRATCH_ROOT_ARG="$2"
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
# --scratch-dir is user-supplied. This tool must never delete anything it
# did not create itself. Rule: if we create the root, we own the whole
# root and remove all of it. If the caller hands us an existing (empty)
# directory, we did NOT create that root — we create one uniquely-named
# subdirectory inside it and remove ONLY that subdirectory, leaving
# everything else the caller had there untouched. A non-empty caller-
# supplied directory is refused outright: we will not guess what's safe to
# touch inside someone else's directory.
CREATED_SCRATCH_ROOT=false

if [[ -z "$SCRATCH_ROOT_ARG" ]]; then
  SCRATCH_ROOT="$(mktemp -d)" || {
    echo "verify-discriminating: mktemp -d failed" >&2
    exit 2
  }
  CREATED_SCRATCH_ROOT=true
else
  SCRATCH_ROOT="$SCRATCH_ROOT_ARG"
  if [[ -e "$SCRATCH_ROOT" && ! -d "$SCRATCH_ROOT" ]]; then
    echo "verify-discriminating: --scratch-dir $SCRATCH_ROOT exists and is not a directory; refusing to proceed" >&2
    exit 2
  fi
  if [[ -d "$SCRATCH_ROOT" ]]; then
    if [[ -n "$(ls -A "$SCRATCH_ROOT" 2>/dev/null)" ]]; then
      echo "verify-discriminating: --scratch-dir $SCRATCH_ROOT already exists and is not empty; refusing to use it (this tool only ever removes what it creates itself — point it at an empty or nonexistent directory instead)" >&2
      exit 2
    fi
    CREATED_SCRATCH_ROOT=false
  else
    mkdir -p "$SCRATCH_ROOT" || {
      echo "verify-discriminating: could not create --scratch-dir $SCRATCH_ROOT" >&2
      exit 2
    }
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

MERGE_BASE="$(git merge-base "$BASE_REF" HEAD 2>/dev/null)" || {
  echo "verify-discriminating: could not compute merge-base with $BASE_REF" >&2
  exit 2
}

# --- find test files added or modified since merge-base -----------------
# Detection set: *.bats, test_*.py, *_test.py, test_*.sh. This set is
# pinned by tests — deleting any one pattern here must turn the test suite
# red, because a pattern silently dropped here is a class of test the gate
# stops checking at all.
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
  echo "verify-discriminating: no test files (*.bats, test_*.py, *_test.py, test_*.sh) were added or modified between $MERGE_BASE and HEAD — refusing (this is never treated as a vacuous clean pass)" >&2
  exit 1
fi

HAS_PYTHON=false
HAS_BATS=false
HAS_SH=false
for k in "${TEST_KINDS[@]}"; do
  [[ "$k" == "python" ]] && HAS_PYTHON=true
  [[ "$k" == "bats" ]] && HAS_BATS=true
  [[ "$k" == "sh" ]] && HAS_SH=true
done

# --- runner preflight: checked up front, before running anything --------
# A gate that cannot run its own runner must abort, not silently pass. This
# check must happen before a single test is executed, so a missing runner
# never has the chance to surface as a per-file exit 127 that later code
# might mistake for a real (discriminating) test result.
if [[ "$HAS_BATS" == "true" ]] && ! command -v bats >/dev/null 2>&1; then
  echo "verify-discriminating: required test runner 'bats' is not installed or not on PATH — refusing to certify" >&2
  exit 3
fi

if [[ "$HAS_SH" == "true" ]] && ! command -v bash >/dev/null 2>&1; then
  echo "verify-discriminating: required interpreter 'bash' is not installed or not on PATH — refusing to certify" >&2
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

git worktree add --detach --quiet "$WORKTREE_DIR" "$MERGE_BASE" >/dev/null || {
  echo "verify-discriminating: failed to create scratch worktree at $MERGE_BASE" >&2
  exit 2
}

# --- merge-base sanity probe ---------------------------------------------
# Before trusting any per-file verdict, confirm the merge-base tree can run
# a trivially-passing test of each kind we actually need. This is not a
# diagnosis of any real test's failure cause — it's a precondition check.
# If the base can't pass a test that is written to always pass, the base
# is broken for reasons unrelated to the change under test, and every real
# file would spuriously look "discriminating" — rubber-stamping the whole
# PR. Refuse instead of trusting a broken base.
PROBE_DIR="$WORKTREE_DIR/.verify-discriminating-probe"
mkdir -p "$PROBE_DIR"

probe_kind() {
  local kind="$1" out status relpath
  case "$kind" in
    bats)
      relpath=".verify-discriminating-probe/probe.bats"
      cat > "$WORKTREE_DIR/$relpath" <<'EOF'
#!/usr/bin/env bats
@test "verify-discriminating merge-base probe" { true; }
EOF
      out="$(cd "$WORKTREE_DIR" && bats "$relpath" 2>&1 1>/dev/null)"
      status=$?
      ;;
    python)
      relpath=".verify-discriminating-probe/test_verify_discriminating_probe.py"
      cat > "$WORKTREE_DIR/$relpath" <<'EOF'
def test_verify_discriminating_probe():
    assert True
EOF
      out="$(cd "$WORKTREE_DIR" && python3 -m pytest "$relpath" -q 2>&1 1>/dev/null)"
      status=$?
      ;;
    sh)
      relpath=".verify-discriminating-probe/test_verify_discriminating_probe.sh"
      cat > "$WORKTREE_DIR/$relpath" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
      out="$(cd "$WORKTREE_DIR" && bash "$relpath" 2>&1 1>/dev/null)"
      status=$?
      ;;
  esac
  if [[ "$status" -ne 0 ]]; then
    echo "verify-discriminating: the merge-base tree ($MERGE_BASE) fails a trivially-passing $kind probe test (observed exit $status; stderr: ${out:-<empty>}) — refusing to trust any result produced against this base" >&2
    rm -rf "$PROBE_DIR"
    exit 4
  fi
}

[[ "$HAS_BATS" == "true" ]] && probe_kind bats
[[ "$HAS_PYTHON" == "true" ]] && probe_kind python
[[ "$HAS_SH" == "true" ]] && probe_kind sh
rm -rf "$PROBE_DIR"

# --- per-file evaluation --------------------------------------------------
# Copy each changed test file into the merge-base worktree at its real
# repo-relative path, run it with the runner for its kind, and record only
# the exit code and stderr — no interpretation. Exit 0 (it passed at base)
# is a refusal. Everything else is discriminating, with two named,
# protocol-level exceptions (not a diagnosis of cause): pytest's own
# "zero collected" exit code 5, and bats' own "found no tests" report —
# both mean nothing actually ran, so neither may satisfy the gate.
run_one_test() {
  local relpath="$1" kind="$2"
  case "$kind" in
    bats)
      RESULT_STDERR="$(cd "$WORKTREE_DIR" && bats "$relpath" 2>&1 1>/dev/null)"
      RESULT_STATUS=$?
      ;;
    sh)
      RESULT_STDERR="$(cd "$WORKTREE_DIR" && bash "$relpath" 2>&1 1>/dev/null)"
      RESULT_STATUS=$?
      ;;
    python)
      RESULT_STDERR="$(cd "$WORKTREE_DIR" && python3 -m pytest "$relpath" -q 2>&1 1>/dev/null)"
      RESULT_STATUS=$?
      ;;
  esac
}

TOTAL=0
DISCRIMINATING=0
NOT_DISCRIMINATING=()

for i in "${!TEST_FILES[@]}"; do
  f="${TEST_FILES[$i]}"
  kind="${TEST_KINDS[$i]}"
  dest="$WORKTREE_DIR/$f"
  mkdir -p "$(dirname "$dest")"
  if ! git show "HEAD:$f" > "$dest" 2>/dev/null; then
    echo "verify-discriminating: could not read $f at HEAD" >&2
    exit 2
  fi

  RESULT_STATUS=""
  RESULT_STDERR=""
  run_one_test "$f" "$kind"
  status="$RESULT_STATUS"
  stderr_first="$(head -n1 <<<"$RESULT_STDERR")"

  TOTAL=$((TOTAL + 1))

  if [[ "$status" -eq 0 ]]; then
    echo "verify-discriminating: $f — NOT discriminating (exit 0 at merge-base $MERGE_BASE; this test already passes there)" >&2
    NOT_DISCRIMINATING+=("$f")
    continue
  fi

  if [[ "$kind" == "python" && "$status" -eq 5 ]]; then
    echo "verify-discriminating: $f — NOT discriminating (pytest reported zero tests collected at merge-base, exit 5; a placeholder cannot satisfy this gate)" >&2
    NOT_DISCRIMINATING+=("$f")
    continue
  fi

  if [[ "$kind" == "bats" ]] && grep -qF "Found no tests" <<<"$RESULT_STDERR"; then
    echo "verify-discriminating: $f — NOT discriminating (bats reported zero tests found at merge-base; a placeholder cannot satisfy this gate)" >&2
    NOT_DISCRIMINATING+=("$f")
    continue
  fi

  echo "verify-discriminating: $f — discriminating (observed exit $status at merge-base; stderr: ${stderr_first:-<empty>})" >&2
  DISCRIMINATING=$((DISCRIMINATING + 1))
done

echo "discriminating: ${DISCRIMINATING}/${TOTAL}"

if [[ "${#NOT_DISCRIMINATING[@]}" -gt 0 ]]; then
  echo "" >&2
  echo "verify-discriminating: the following file(s) do NOT discriminate and block this gate:" >&2
  for f in "${NOT_DISCRIMINATING[@]}"; do
    echo "  $f" >&2
  done
  exit 1
fi

exit 0
