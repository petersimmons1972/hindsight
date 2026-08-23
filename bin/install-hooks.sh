#!/usr/bin/env bash
# Configure this clone's tracked hooks so every linked worktree uses its own
# checked-out hook version.

set -euo pipefail

if ! REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "install-hooks: not inside a Git worktree" >&2
  exit 1
fi

for hook in pre-commit pre-push; do
  if [ ! -x "$REPO_ROOT/.githooks/$hook" ]; then
    echo "install-hooks: required hook is not executable: $REPO_ROOT/.githooks/$hook" >&2
    exit 1
  fi
done

current="$(git config --local --get core.hooksPath 2>/dev/null || true)"
if [ "$current" != .githooks ]; then
  if [ -n "$current" ]; then
    printf 'install-hooks: replacing local core.hooksPath %q with .githooks\n' "$current"
    printf 'install-hooks: UNDO: git config --local core.hooksPath %q\n' "$current"
  else
    echo "install-hooks: setting local core.hooksPath to .githooks"
    echo "install-hooks: UNDO: git config --local --unset-all core.hooksPath"
  fi
  git config --local core.hooksPath .githooks
fi

effective="$(git config --get core.hooksPath 2>/dev/null || true)"
if [ "$effective" != .githooks ]; then
  echo "install-hooks: core.hooksPath is still '$effective'; a higher-priority override is active" >&2
  exit 1
fi

resolved="$(git rev-parse --path-format=absolute --git-path hooks/pre-commit)"
expected="$REPO_ROOT/.githooks/pre-commit"
if [ "$resolved" != "$expected" ]; then
  echo "install-hooks: Git resolves pre-commit to '$resolved', expected '$expected'" >&2
  exit 1
fi

echo "install-hooks: core.hooksPath=.githooks"
