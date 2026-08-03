#!/usr/bin/env bash
# Exploit harness for hindsight sync-failure-modes.sh containment.
# Builds a throwaway consumer repo + an "outside" tree under a fresh mktemp -d.
# NEVER points at a real repository.
set -u

mk_case() {
  # $1 = layout function name
  BASE="$(mktemp -d /tmp/hs-attack.XXXXXX)"
  export BASE
  mkdir -p "$BASE/consumer" "$BASE/outside"
  ( cd "$BASE/consumer" && git init -q . && git config user.email a@b && git config user.name a )
  printf 'OUTSIDE-SECRET-DO-NOT-TOUCH\n' > "$BASE/outside/canary.md"
  printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
  "$1"
}

run_tool() {
  # $1 = worktree root, rest = args
  local wt="$1"; shift
  bash "$wt/bin/sync-failure-modes.sh" "$@"
  echo "EXIT=$?"
}

report() {
  echo "--- outside tree ---"
  find "$BASE/outside" -mindepth 1 \( -type f -o -type l \) -printf '%y %s %p\n' | sort
  echo "--- inside consumer docs ---"
  find "$BASE/consumer/docs" -mindepth 1 -printf '%y %s %p\n' 2>/dev/null | sort
  echo "--- canary sha ---"
  sha256sum "$BASE/outside/canary.md" 2>/dev/null || echo "canary gone"
}
