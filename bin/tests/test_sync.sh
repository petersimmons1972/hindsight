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

assert_status() {
  local status="$1" repo="$2" file="$3"
  assert_contains "$(printf '%-20s %s' "$status" "$repo")" "$file"
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
docs_file_repo="$TMP/docs-file"
destination_dir_repo="$TMP/destination-dir"
after_failure="$TMP/after-failure"
unrecognized_origin="$TMP/unrecognized-origin"
not_repo="$TMP/not-a-repo"
mkdir -p "$not_repo"
make_repo "$good" 'git@github.com:example/good.git'
make_repo "$wrong" 'https://github.com/example/other.git'
git init -q "$no_origin"
make_repo "$worktree_source" 'git@github.com:example/worktree.git'
git -C "$worktree_source" worktree add -q -b sync-test-worktree "$linked_worktree"
make_repo "$symlink_repo" 'git@github.com:example/symlink.git'
make_repo "$docs_file_repo" 'git@github.com:example/docs-file.git'
make_repo "$destination_dir_repo" 'git@github.com:example/destination-dir.git'
make_repo "$after_failure" 'git@github.com:example/after-failure.git'
make_repo "$unrecognized_origin" 'git@gitlab.com:example/unrecognized.git'
mkdir "$escape_target"
ln -s "$escape_target" "$symlink_repo/docs"
printf 'not a directory\n' > "$docs_file_repo/docs"
mkdir -p "$destination_dir_repo/docs/failure-modes.md"

source="$TMP/catalog.md"
printf '# Canonical catalog\n\nFM-1\n' > "$source"
conf="$TMP/consumers.conf"
printf '%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n%s:%s\n' \
  "$good" 'example/good' "$wrong" 'example/expected' "$no_origin" 'example/no-origin' \
  "$linked_worktree" 'example/worktree' "$symlink_repo" 'example/symlink' \
  "$docs_file_repo" 'example/docs-file' "$destination_dir_repo" 'example/destination-dir' \
  "$after_failure" 'example/after-failure' "$unrecognized_origin" 'example/unrecognized' \
  "$not_repo" 'example/not-repo' > "$conf"

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
assert_contains 'unrecognized-origin' "$output"

set +e
HINDSIGHT_CONSUMERS_CONF="$conf" HINDSIGHT_CATALOG_SOURCE="$source" "$SYNC" --apply >"$output" 2>&1
apply_status=$?
set -e
[[ "$apply_status" -ne 0 ]] || fail 'apply exited zero despite write failures'
assert_contains 'GENERATED — DO NOT EDIT, canonical source is hindsight' "$good/docs/failure-modes.md"
assert_contains 'FM-1' "$good/docs/failure-modes.md"
assert_not_exists "$wrong/docs/failure-modes.md"
assert_not_exists "$no_origin/docs/failure-modes.md"
[[ -f "$linked_worktree/docs/failure-modes.md" ]] || fail 'linked git worktree was not synced'
assert_not_exists "$escape_target/failure-modes.md"
assert_contains 'failed-write' "$output"
assert_contains "$docs_file_repo" "$output"
assert_contains "$destination_dir_repo" "$output"
[[ -f "$after_failure/docs/failure-modes.md" ]] || fail 'consumer after write failure was not synced'
assert_contains 'unrecognized-origin' "$output"
assert_status wrote "$good" "$output"
assert_status refused-mismatch "$wrong" "$output"
assert_status skipped-not-a-repo "$no_origin" "$output"
assert_status wrote "$linked_worktree" "$output"
assert_status refused-unsafe-path "$symlink_repo" "$output"
assert_status failed-write "$docs_file_repo" "$output"
assert_status failed-write "$destination_dir_repo" "$output"
assert_status wrote "$after_failure" "$output"
assert_status unrecognized-origin "$unrecognized_origin" "$output"
assert_status skipped-not-a-repo "$not_repo" "$output"
[[ "$(git -C "$good" rev-parse HEAD)" == "$head_before" ]] || fail 'apply changed consumer HEAD'
[[ "$(git -C "$good" diff --cached --quiet; printf '%s' "$?")" == "$index_before" ]] || fail 'apply changed consumer index'
status_after_apply="$(git -C "$good" status --porcelain)"
assert_contains '?? docs/' <(printf '%s\n' "$status_after_apply")

set +e
HINDSIGHT_CONSUMERS_CONF="$conf" HINDSIGHT_CATALOG_SOURCE="$source" "$SYNC" --apply >"$output" 2>&1
repeat_apply_status=$?
set -e
[[ "$repeat_apply_status" -ne 0 ]] || fail 'repeat apply exited zero despite persistent write failures'
assert_contains 'up-to-date' "$output"
[[ "$(git -C "$good" rev-parse HEAD)" == "$head_before" ]] || fail 'repeat apply changed consumer HEAD'
[[ "$(git -C "$good" diff --cached --quiet; printf '%s' "$?")" == "$index_before" ]] || fail 'repeat apply changed consumer index'
[[ "$(git -C "$good" status --porcelain)" == "$status_after_apply" ]] || fail 'repeat apply changed consumer status'

printf 'PASS: sync-failure-modes contract\n'
