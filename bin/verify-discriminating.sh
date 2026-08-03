#!/usr/bin/env bash
# Verify tests by removing implementation changes from a HEAD worktree, then
# requiring each changed test to fail.  It intentionally never copies a test
# into a merge-base tree: that design confuses absent imports with behaviour.
# Usage: verify-discriminating.sh [--base <ref>]
set -uo pipefail

BASE=main
while [ $# -gt 0 ]; do
  case "$1" in
    --base) [ $# -ge 2 ] || { echo "verify-discriminating: --base needs a ref" >&2; exit 2; }; BASE="$2"; shift 2 ;;
    *) echo "verify-discriminating: unknown option: $1" >&2; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "verify-discriminating: not in a git worktree" >&2; exit 2; }
cd "$ROOT" || exit 2
MERGE_BASE="$(git merge-base "$BASE" HEAD)" || { echo "verify-discriminating: cannot merge-base $BASE" >&2; exit 2; }

is_test() {
  case "$(basename "$1")" in *.bats|test_*.py|*_test.py|test_*.sh) return 0;; esac
  return 1
}
kind() {
  case "$(basename "$1")" in *.bats) echo bats;; *.py) echo python;; *) echo shell;; esac
}

declare -a TESTS=() IMPLEMENTATION=()
# --name-only with -M reports the destination of a rename.  We need that path:
# it is the file that exists at HEAD and is therefore the one we can run.
while IFS= read -r path; do
  [ -n "$path" ] || continue
  if is_test "$path"; then TESTS+=("$path"); else IMPLEMENTATION+=("$path"); fi
done < <(git diff --name-only -M "$MERGE_BASE" HEAD)

for path in "${IMPLEMENTATION[@]}"; do
  if [[ "$path" == *.py || "$path" == *.sh || "$path" == *.bats ]]; then
    echo "unrecognized changed file: $path"
  fi
done

if [ "${#TESTS[@]}" -eq 0 ]; then
  echo "verify-discriminating: no new tests since $MERGE_BASE" >&2
  exit 1
fi
for path in "${IMPLEMENTATION[@]}"; do
  echo "implementation hunk scheduled for reversion: $path"
done

for path in "${TESTS[@]}"; do
  mode="$(git ls-tree HEAD -- "$path" | awk '{print $1}')"
  if [ "$mode" = 120000 ]; then
    echo "$path: SYMLINK (not run; symlinked tests are never materialised)"
    echo "discriminating: 0/${#TESTS[@]}"
    exit 1
  fi
done

SCRATCH="$(mktemp -d)"
WT="$SCRATCH/head-without-implementation"
cleanup() { git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$SCRATCH"; }
trap cleanup EXIT
git worktree add --detach --quiet "$WT" HEAD || { echo "verify-discriminating: cannot create HEAD worktree" >&2; exit 2; }

PATCH="$SCRATCH/implementation.patch"
for path in "${IMPLEMENTATION[@]}"; do git diff --binary "$MERGE_BASE" HEAD -- "$path" >> "$PATCH"; done
if [ -s "$PATCH" ]; then
  git -C "$WT" apply --reverse "$PATCH" || { echo "verify-discriminating: cannot cleanly revert implementation hunks" >&2; exit 2; }
fi

total=0; good=0; bad=0
for path in "${TESTS[@]}"; do
  total=$((total + 1))
  runner="$(kind "$path")"
  log="$SCRATCH/test-$total.log"
  case "$runner" in
    python) (cd "$WT" && python3 -m pytest "$path" -q) >"$log" 2>&1; rc=$? ;;
    bats) command -v bats >/dev/null 2>&1 || { echo "verify-discriminating: bats unavailable" >&2; exit 3; }; (cd "$WT" && bats "$path") >"$log" 2>&1; rc=$? ;;
    shell) (cd "$WT" && bash "$path") >"$log" 2>&1; rc=$? ;;
  esac
  if [ "$rc" -eq 0 ]; then
    echo "$path: PASSED (not discriminating after implementation reversion)"
    bad=$((bad + 1))
  elif grep -Eqi 'ModuleNotFoundError|ImportError|No module named|cannot import name' "$log"; then
    echo "$path: IMPORT_CONFOUND (not certified: reverted code removed an import dependency)"
    bad=$((bad + 1))
  else
    echo "$path: FAILED (discriminating after implementation reversion)"
    good=$((good + 1))
  fi
done
echo "discriminating: $good/$total"
[ "$bad" -eq 0 ] || exit 1
