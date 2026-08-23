#!/usr/bin/env bash
# Configure this clone's tracked hooks so every currently registered worktree
# uses its own checked-out hook version.

set -euo pipefail

die() {
  echo "install-hooks: $*" >&2
  exit 1
}

reject_ambiguous_git_environment() {
  local name
  for name in GIT_DIR GIT_COMMON_DIR GIT_WORK_TREE; do
    if [[ -v "$name" ]]; then
      die "refusing repository-routing Git environment variable $name"
    fi
  done
  for name in GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS; do
    if [[ -v "$name" ]]; then
      die "refusing command-scope Git configuration from $name"
    fi
  done
}

assert_regular_executable() {
  local path="$1"
  if [ ! -f "$path" ] || [ -L "$path" ] || [ ! -x "$path" ]; then
    die "registered worktree is not armed: $path is not a regular non-symlink executable"
  fi
}

assert_no_higher_priority_hookspath() {
  local entry origin
  local -a worktree_values=()
  local -a local_entries=()

  mapfile -t worktree_values < <(
    git -C "$REPO_ROOT" config --worktree --get-all core.hooksPath 2>/dev/null || true
  )
  if [ "${#worktree_values[@]}" -ne 0 ]; then
    die "a higher-priority worktree core.hooksPath override is active"
  fi

  mapfile -t local_entries < <(
    git -C "$REPO_ROOT" config --local --includes --show-origin --get-all core.hooksPath \
      2>/dev/null || true
  )
  if [ "${#local_entries[@]}" -gt 1 ]; then
    die "expected exactly one direct local core.hooksPath or none, found ${#local_entries[@]}"
  fi

  HAS_LOCAL_HOOKSPATH=0
  CURRENT_LOCAL_HOOKSPATH=
  if [ "${#local_entries[@]}" -eq 1 ]; then
    entry="${local_entries[0]}"
    origin="${entry%%$'\t'*}"
    if [ "$origin" != "file:$COMMON_CONFIG" ]; then
      die "expected a direct local core.hooksPath in $COMMON_CONFIG, not $origin"
    fi
    HAS_LOCAL_HOOKSPATH=1
    CURRENT_LOCAL_HOOKSPATH="${entry#*$'\t'}"
  fi
}

assert_relative_hook_resolution() {
  local field worktree physical hook resolved expected
  local count=0

  while IFS= read -r -d '' field; do
    case "$field" in
      'worktree '*)
        worktree="${field#worktree }"
        if [ ! -d "$worktree" ]; then
          die "registered worktree is unavailable: $worktree; prune or repair it first"
        fi
        physical="$(cd "$worktree" && pwd -P)"
        assert_regular_executable "$physical/bin/verify-hook-worktree.sh"
        for hook in pre-commit pre-push; do
          assert_regular_executable "$physical/.githooks/$hook"
          resolved="$(
            git -C "$physical" -c core.hooksPath=.githooks \
              rev-parse --path-format=absolute --git-path "hooks/$hook"
          )"
          expected="$physical/.githooks/$hook"
          if [ "$resolved" != "$expected" ]; then
            die "candidate .githooks resolves $hook to '$resolved', expected '$expected'"
          fi
        done
        count=$((count + 1))
        ;;
    esac
  done < <(git -C "$REPO_ROOT" worktree list --porcelain -z)

  if [ "$count" -eq 0 ]; then
    die "Git reported no registered worktrees"
  fi
}

reject_ambiguous_git_environment

if ! REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  die "not inside a Git worktree"
fi
REPO_ROOT="$(cd "$REPO_ROOT" && pwd -P)"
if ! COMMON_DIR="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir)"; then
  die "cannot resolve the shared Git directory"
fi
COMMON_DIR="$(cd "$COMMON_DIR" && pwd -P)"
COMMON_CONFIG="$COMMON_DIR/config"

# These assertions are intentionally named and independently mutation-tested.
# Both run before even an idempotent early exit, so a stale relative setting
# cannot hide a newly introduced override or missing worktree hook.
assert_no_higher_priority_hookspath
assert_relative_hook_resolution

if [ "$HAS_LOCAL_HOOKSPATH" -eq 1 ] \
  && [ "$CURRENT_LOCAL_HOOKSPATH" = .githooks ]; then
  echo "install-hooks: core.hooksPath=.githooks (already configured and verified)"
  exit 0
fi

if [ "$HAS_LOCAL_HOOKSPATH" -eq 1 ]; then
  printf 'install-hooks: replacing local core.hooksPath %q with .githooks\n' \
    "$CURRENT_LOCAL_HOOKSPATH"
  printf 'install-hooks: UNDO: git config --local --replace-all core.hooksPath %q\n' \
    "$CURRENT_LOCAL_HOOKSPATH"
else
  echo "install-hooks: setting local core.hooksPath to .githooks"
  echo "install-hooks: UNDO: git config --local --unset-all core.hooksPath"
fi
echo "install-hooks: verified every registered worktree; activating shared config"

# Terminal handoff is mandatory: Git's lock-and-rename is the only mutation.
# There is no shell instruction or verification window after a successful
# shared-config write. Callers verify the persisted effective/resolved paths.
exec git -C "$REPO_ROOT" config --local --replace-all core.hooksPath .githooks
