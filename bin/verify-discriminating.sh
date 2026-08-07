#!/usr/bin/env bash
# Supported-shape discriminating-test gate (hindsight#23 / plan 07).
#
# Founder ruling 2026-08-03: enumerate shapes the gate can genuinely separate;
# certify only those; refuse loudly on everything else. Never certify import-
# only / added-module failures as "discriminating" (PR #48 failure class).
#
# NEVER uses merge-base-copy of tests (disqualified by measurement).
#
# Usage: verify-discriminating.sh [--base <ref>]
# Exit: 0 all supported changed tests discriminate; 1 certification fail /
#       unsupported shape / no new tests; 2 usage; 3 runner missing.
set -uo pipefail

BASE=main
while [ $# -gt 0 ]; do
  case "$1" in
    --base)
      [ $# -ge 2 ] || { echo "verify-discriminating: --base needs a ref" >&2; exit 2; }
      BASE="$2"
      shift 2
      ;;
    *)
      echo "verify-discriminating: unknown option: $1" >&2
      exit 2
      ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "verify-discriminating: not in a git worktree" >&2
  exit 2
}
cd "$ROOT" || exit 2

MERGE_BASE="$(git merge-base "$BASE" HEAD)" || {
  echo "verify-discriminating: cannot merge-base $BASE" >&2
  exit 2
}

# --- shape detection (supported-shape gate) ---------------------------------

is_test_path() {
  case "$(basename "$1")" in
    *.bats|test_*.py|*_test.py) return 0 ;;
    *) return 1 ;;
  esac
}

# Unsupported: plain shell scripts claiming to be tests (no structured runner).
is_unsupported_shell_test() {
  case "$(basename "$1")" in
    test_*.sh|*_test.sh) return 0 ;;
  esac
  return 1
}

# Classify a python test: if it imports a module path that exists only as an
# ADDED file on this branch (not at merge-base), shape is unsupported.
# Returns 0 if supported, 1 if unsupported_added_module.
python_shape_supported() {
  local path="$1"
  local content imports mod
  content="$(git show "HEAD:$path" 2>/dev/null)" || return 1
  # Collect simple import targets: "import foo" / "from foo import"
  imports="$(printf '%s\n' "$content" | sed -nE \
    -e 's/^[[:space:]]*import[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)/\1/p' \
    -e 's/^[[:space:]]*from[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)(\.[A-Za-z0-9_]+)*.*/\1/p')"
  while IFS= read -r mod; do
    [ -n "$mod" ] || continue
    # stdlib / builtins short-circuit: if no corresponding .py on either tree, ignore
    if git cat-file -e "HEAD:${mod}.py" 2>/dev/null; then
      if ! git cat-file -e "${MERGE_BASE}:${mod}.py" 2>/dev/null; then
        return 1
      fi
    fi
    # package form package/__init__.py
    if git cat-file -e "HEAD:${mod}/__init__.py" 2>/dev/null; then
      if ! git cat-file -e "${MERGE_BASE}:${mod}/__init__.py" 2>/dev/null; then
        return 1
      fi
    fi
  done <<<"$imports"
  return 0
}

# --- collect changed paths --------------------------------------------------

declare -a TESTS=() IMPLEMENTATION=() UNSUPPORTED=()

while IFS= read -r path; do
  [ -n "$path" ] || continue
  if is_unsupported_shell_test "$path"; then
    UNSUPPORTED+=("$path:unstructured-shell")
  elif is_test_path "$path"; then
    TESTS+=("$path")
  else
    IMPLEMENTATION+=("$path")
  fi
done < <(git diff --name-only -M "$MERGE_BASE" HEAD)

if [ "${#UNSUPPORTED[@]}" -gt 0 ]; then
  for u in "${UNSUPPORTED[@]}"; do
    echo "UNSUPPORTED_SHAPE: $u (supported-shape gate refuses unstructured shell tests)"
  done
  echo "verify-discriminating: refuse — unsupported shapes present" >&2
  exit 1
fi

if [ "${#TESTS[@]}" -eq 0 ]; then
  echo "verify-discriminating: no new tests since $MERGE_BASE" >&2
  exit 1
fi

# Classify each test shape before any certification attempt.
declare -a SUPPORTED=()
for path in "${TESTS[@]}"; do
  mode="$(git ls-tree HEAD -- "$path" | awk '{print $1}')"
  if [ "$mode" = "120000" ]; then
    echo "UNSUPPORTED_SHAPE: $path:symlink (never materialised / never certified)"
    UNSUPPORTED+=("$path:symlink")
    continue
  fi
  case "$(basename "$path")" in
    *.py)
      if python_shape_supported "$path"; then
        SUPPORTED+=("$path")
      else
        echo "UNSUPPORTED_SHAPE: $path:added-module (imports a module not present at merge-base)"
        UNSUPPORTED+=("$path:added-module")
      fi
      ;;
    *.bats)
      # Bats: supported when the .bats file itself is not a symlink (already checked).
      # Discrimination still verified by reversion below.
      SUPPORTED+=("$path")
      ;;
  esac
done

if [ "${#UNSUPPORTED[@]}" -gt 0 ]; then
  echo "verify-discriminating: refuse — ${#UNSUPPORTED[@]} unsupported shape(s); not certified" >&2
  exit 1
fi

if [ "${#SUPPORTED[@]}" -eq 0 ]; then
  echo "verify-discriminating: no supported-shape tests to certify" >&2
  exit 1
fi

for path in "${IMPLEMENTATION[@]}"; do
  echo "implementation hunk scheduled for reversion: $path"
done

# --- reverse implementation at HEAD, run supported tests --------------------

SCRATCH="$(mktemp -d)"
WT="$SCRATCH/head-without-implementation"
cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$SCRATCH"
}
trap cleanup EXIT

git worktree add --detach --quiet "$WT" HEAD || {
  echo "verify-discriminating: cannot create HEAD worktree" >&2
  exit 2
}

PATCH="$SCRATCH/implementation.patch"
: >"$PATCH"
for path in "${IMPLEMENTATION[@]}"; do
  git diff --binary "$MERGE_BASE" HEAD -- "$path" >>"$PATCH" || true
done
if [ -s "$PATCH" ]; then
  if ! git -C "$WT" apply --reverse "$PATCH"; then
    echo "verify-discriminating: cannot cleanly revert implementation hunks" >&2
    exit 2
  fi
fi

total=0
good=0
bad=0
for path in "${SUPPORTED[@]}"; do
  total=$((total + 1))
  log="$SCRATCH/test-$total.log"
  case "$(basename "$path")" in
    *.py)
      (cd "$WT" && python3 -m pytest "$path" -q) >"$log" 2>&1
      rc=$?
      ;;
    *.bats)
      command -v bats >/dev/null 2>&1 || {
        echo "verify-discriminating: bats unavailable" >&2
        exit 3
      }
      (cd "$WT" && bats "$path") >"$log" 2>&1
      rc=$?
      ;;
    *)
      echo "$path: UNSUPPORTED_SHAPE (internal)"
      bad=$((bad + 1))
      continue
      ;;
  esac

  if [ "$rc" -eq 0 ]; then
    echo "$path: PASSED (not discriminating after implementation reversion)"
    bad=$((bad + 1))
  elif grep -Eqi 'ModuleNotFoundError|ImportError|No module named|cannot import name|SyntaxError' "$log"; then
    # Defence in depth: even if shape classifier missed, never certify these.
    echo "$path: NON_BEHAVIORAL_FAIL (not certified: import/syntax after reversion)"
    bad=$((bad + 1))
  else
    echo "$path: FAILED (discriminating after implementation reversion)"
    good=$((good + 1))
  fi
done

echo "discriminating: $good/$total (supported-shape)"
if [ "$bad" -ne 0 ]; then
  exit 1
fi
exit 0
