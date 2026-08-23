#!/usr/bin/env bash
# Fail before hook logic runs if Git selected a hook from a sibling worktree.

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "verify-hook-worktree: usage: verify-hook-worktree.sh <invoked-hook-path>" >&2
  exit 1
fi
if ! REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "verify-hook-worktree: hook must run inside the worktree being operated on" >&2
  exit 1
fi

invoked="$1"
hook_name="${invoked##*/}"
if ! invoked_dir="$(cd "$(dirname "$invoked")" 2>/dev/null && pwd -P)"; then
  echo "verify-hook-worktree: cannot resolve invoked hook path '$invoked'" >&2
  exit 1
fi
if ! expected_dir="$(cd "$REPO_ROOT/.githooks" 2>/dev/null && pwd -P)"; then
  echo "verify-hook-worktree: active worktree has no .githooks directory: $REPO_ROOT" >&2
  exit 1
fi

invoked_path="$invoked_dir/$hook_name"
expected_path="$expected_dir/$hook_name"
if [ "$invoked_path" != "$expected_path" ]; then
  configured="$(git config --get core.hooksPath 2>/dev/null || printf '<unset>')"
  echo "ERROR: Git selected a hook from another worktree." >&2
  echo "  invoked: $invoked_path" >&2
  echo "  expected: $expected_path" >&2
  echo "  core.hooksPath: $configured" >&2
  echo "Run '$REPO_ROOT/bin/install-hooks.sh' to select this worktree's hook version." >&2
  exit 1
fi
