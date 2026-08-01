#!/usr/bin/env bash
# Contract tests for the consumer catalog vendor script.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SYNC="$ROOT/bin/sync-failure-modes.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local needle="$1" file="$2"
  rg -F --quiet -- "$needle" "$file" || fail "expected $file to contain: $needle"
}

assert_not_exists() {
  [[ ! -e "$1" ]] || fail "expected $1 not to exist"
}

make_repo() {
  local path="$1" remote="$2"
  git init -q "$path"
  git -C "$path" config user.email test@example.invalid
  git -C "$path" config user.name 'Sync Test'
  printf 'seed\n' > "$path/README"
  git -C "$path" add README
  git -C "$path" commit -qm seed
  git -C "$path" remote add origin "$remote"
}

good="$TMP/good"
wrong="$TMP/wrong"
no_origin="$TMP/no-origin"
worktree_source="$TMP/worktree-source"
linked_worktree="$TMP/linked-worktree"
symlink_repo="$TMP/symlink-repo"
escape_target="$TMP/escape-target"
not_repo="$TMP/not-a-repo"
mkdir -p "$not_repo"
make_repo "$good" 'git@github.com:example/good.git'
make_repo "$wrong" 'https://github.com/example/other.git'
git init -q "$no_origin"
make_repo "$worktree_source" 'git@github.com:example/worktree.git'
git -C "$worktree_source" worktree add -q -b sync-test-worktree "$linked_worktree"
make_repo "$symlink_repo" 'git@github.com:example/symlink.git'
mkdir "$escape_target"
ln -s "$escape_target" "$symlink_repo/docs"

source="$TMP/catalog.md"
printf '# Canonical catalog\n\nFM-1\n' > "$source"
conf="$TMP/consumers.conf"
printf '%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n' \
  "$good" 'example/good' "$wrong" 'example/expected' "$no_origin" 'example/no-origin' \
  "$linked_worktree" 'example/worktree' "$symlink_repo" 'example/symlink' "$not_repo" 'example/not-repo' > "$conf"

head_before="$(git -C "$good" rev-parse HEAD)"
index_before="$(git -C "$good" diff --cached --quiet; printf '%s' "$?")"
output="$TMP/dry-run.out"
HINDSIGHT_CONSUMERS_CONF="$conf" HINDSIGHT_CATALOG_SOURCE="$source" "$SYNC" >"$output" 2>&1
assert_not_exists "$good/docs/failure-modes.md"
assert_contains 'would-write' "$output"
assert_contains 'refused-mismatch' "$output"
assert_contains 'skipped-not-a-repo' "$output"
assert_contains 'origin missing' "$output"
assert_contains 'refused-unsafe-path' "$output"

HINDSIGHT_CONSUMERS_CONF="$conf" HINDSIGHT_CATALOG_SOURCE="$source" "$SYNC" --apply >"$output" 2>&1
assert_contains 'GENERATED — DO NOT EDIT, canonical source is hindsight' "$good/docs/failure-modes.md"
assert_contains 'FM-1' "$good/docs/failure-modes.md"
assert_not_exists "$wrong/docs/failure-modes.md"
assert_not_exists "$no_origin/docs/failure-modes.md"
[[ -f "$linked_worktree/docs/failure-modes.md" ]] || fail 'linked git worktree was not synced'
assert_not_exists "$escape_target/failure-modes.md"
[[ "$(git -C "$good" rev-parse HEAD)" == "$head_before" ]] || fail 'apply changed consumer HEAD'
[[ "$(git -C "$good" diff --cached --quiet; printf '%s' "$?")" == "$index_before" ]] || fail 'apply changed consumer index'
status_after_apply="$(git -C "$good" status --porcelain)"
assert_contains '?? docs/' <(printf '%s\n' "$status_after_apply")

HINDSIGHT_CONSUMERS_CONF="$conf" HINDSIGHT_CATALOG_SOURCE="$source" "$SYNC" --apply >"$output" 2>&1
assert_contains 'up-to-date' "$output"
[[ "$(git -C "$good" rev-parse HEAD)" == "$head_before" ]] || fail 'repeat apply changed consumer HEAD'
[[ "$(git -C "$good" diff --cached --quiet; printf '%s' "$?")" == "$index_before" ]] || fail 'repeat apply changed consumer index'
[[ "$(git -C "$good" status --porcelain)" == "$status_after_apply" ]] || fail 'repeat apply changed consumer status'

printf 'PASS: sync-failure-modes contract\n'
