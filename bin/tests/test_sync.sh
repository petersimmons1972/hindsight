#!/usr/bin/env bash
# Contract tests for bin/sync-failure-modes.sh (issue #22).
#
# Red-first against main's unguarded writer: bare invocation must not write,
# unknown args must abort, one consumer failure must not kill the batch, and
# --apply must emit an undo journal before the first write.
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

assert_not_contains() {
  local needle="$1" file="$2"
  if rg -F --quiet -- "$needle" "$file"; then
    fail "expected $file NOT to contain: $needle"
  fi
}

assert_not_exists() {
  [[ ! -e "$1" ]] || fail "expected $1 not to exist"
}

assert_exists() {
  [[ -e "$1" ]] || fail "expected $1 to exist"
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
unmakeable="$TMP/unmakeable"
mkdir -p "$not_repo"
make_repo "$good" 'git@github.com:example/good.git'
make_repo "$wrong" 'https://github.com/example/other.git'
git init -q "$no_origin"
make_repo "$worktree_source" 'git@github.com:example/worktree.git'
git -C "$worktree_source" worktree add -q -b sync-test-worktree "$linked_worktree"
make_repo "$symlink_repo" 'git@github.com:example/symlink.git'
mkdir "$escape_target"
ln -s "$escape_target" "$symlink_repo/docs"
# Consumer whose docs/ cannot be created as a directory (file occupies the name).
make_repo "$unmakeable" 'git@github.com:example/unmakeable.git'
printf 'blocker\n' > "$unmakeable/docs"

source="$TMP/catalog.md"
printf '# Canonical catalog\n\nFM-1\n' > "$source"
conf="$TMP/consumers.conf"
{
  printf '%s:%s\n' "$good" 'example/good'
  printf '%s:%s\n' "$wrong" 'example/expected'
  printf '%s:%s\n' "$no_origin" 'example/no-origin'
  printf '%s:%s\n' "$linked_worktree" 'example/worktree'
  printf '%s:%s\n' "$symlink_repo" 'example/symlink'
  printf '%s:%s\n' "$not_repo" 'example/not-repo'
  printf '%s:%s\n' "$unmakeable" 'example/unmakeable'
} > "$conf"

run_sync() {
  # shellcheck disable=SC2034
  HINDSIGHT_CONSUMERS_CONF="$conf" \
  HINDSIGHT_CATALOG_SOURCE="$source" \
  HINDSIGHT_SYNC_JOURNAL_DIR="${HINDSIGHT_SYNC_JOURNAL_DIR:-}" \
    "$SYNC" "$@"
}

# ── 1. Default is dry-run: bare invocation never writes ──────────────────────
output="$TMP/dry-run.out"
set +e
run_sync >"$output" 2>&1
ec=$?
set -e
[[ $ec -eq 0 ]] || fail "dry-run default should exit 0, got $ec; out=$(cat "$output")"
assert_not_exists "$good/docs/failure-modes.md"
assert_not_exists "$linked_worktree/docs/failure-modes.md"
assert_contains 'would-write' "$output"
assert_contains 'refused-mismatch' "$output"
assert_contains 'skipped-not-a-repo' "$output"
assert_contains 'refused-unsafe-path' "$output"
# Summary must show every configured consumer was attempted.
assert_contains 'attempted=7' "$output"

# ── 2. Unrecognised argument aborts without writing (FM-146) ─────────────────
set +e
run_sync --please-write >"$output" 2>&1
ec=$?
set -e
[[ $ec -eq 2 ]] || fail "unknown arg should exit 2, got $ec"
assert_not_exists "$good/docs/failure-modes.md"
assert_contains 'Usage:' "$output"

# ── 3. --apply writes only safe consumers; batch continues past failures ─────
head_before="$(git -C "$good" rev-parse HEAD)"
index_before="$(git -C "$good" diff --cached --quiet; printf '%s' "$?")"
journal_parent="$TMP/journals"
mkdir -p "$journal_parent"
export HINDSIGHT_SYNC_JOURNAL_DIR="$journal_parent"

set +e
run_sync --apply >"$output" 2>&1
ec=$?
set -e
# Apply may exit non-zero when some consumers fail, but good must still land.
assert_contains 'GENERATED — DO NOT EDIT, canonical source is hindsight' "$good/docs/failure-modes.md"
assert_contains 'FM-1' "$good/docs/failure-modes.md"
assert_not_exists "$wrong/docs/failure-modes.md"
assert_not_exists "$no_origin/docs/failure-modes.md"
assert_exists "$linked_worktree/docs/failure-modes.md"
assert_not_exists "$escape_target/failure-modes.md"
# Unmakeable docs/ must not abort the rest of the batch (T1 / #22).
assert_contains 'failed' "$output"
assert_contains 'attempted=7' "$output"
assert_contains 'wrote' "$output"
# Undo journal printed BEFORE action and persisted.
assert_contains 'UNDO' "$output"
assert_contains 'journal' "$output"
journal_dir="$(rg -o '/[^[:space:]]*hindsight-sync-journal[^[:space:]]*' "$output" | head -1 || true)"
if [[ -z "${journal_dir:-}" ]]; then
  # Fall back: any directory created under journal_parent
  journal_dir="$(find "$journal_parent" -mindepth 1 -maxdepth 1 -type d | head -1 || true)"
fi
[[ -n "${journal_dir:-}" && -d "$journal_dir" ]] || fail "expected an undo journal directory; out=$(cat "$output")"
assert_exists "$journal_dir/manifest.tsv"

[[ "$(git -C "$good" rev-parse HEAD)" == "$head_before" ]] || fail 'apply changed consumer HEAD'
[[ "$(git -C "$good" diff --cached --quiet; printf '%s' "$?")" == "$index_before" ]] || fail 'apply changed consumer index'
status_after_apply="$(git -C "$good" status --porcelain)"
assert_contains '?? docs/' <(printf '%s\n' "$status_after_apply")

# ── 4. Repeat apply is up-to-date; no git mutation ───────────────────────────
set +e
run_sync --apply >"$output" 2>&1
set -e
assert_contains 'up-to-date' "$output"
[[ "$(git -C "$good" rev-parse HEAD)" == "$head_before" ]] || fail 'repeat apply changed consumer HEAD'
[[ "$(git -C "$good" status --porcelain)" == "$status_after_apply" ]] || fail 'repeat apply changed consumer status'

# ── 5. --undo restores prior state from the journal ──────────────────────────
printf 'PRIOR\n' > "$good/docs/failure-modes.md"
# Fresh apply should snapshot PRIOR then overwrite with catalog.
set +e
run_sync --apply >"$output" 2>&1
set -e
assert_contains 'FM-1' "$good/docs/failure-modes.md"
journal_dir="$(find "$journal_parent" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
[[ -n "$journal_dir" ]] || fail 'no journal after second apply'
set +e
HINDSIGHT_CONSUMERS_CONF="$conf" HINDSIGHT_CATALOG_SOURCE="$source" \
  "$SYNC" --undo "$journal_dir" >"$output" 2>&1
ec=$?
set -e
[[ $ec -eq 0 ]] || fail "undo should exit 0, got $ec; out=$(cat "$output")"
assert_contains 'PRIOR' "$good/docs/failure-modes.md"

# ── 6. Zero consumers must fail loud (R4) ────────────────────────────────────
empty_conf="$TMP/empty.conf"
: > "$empty_conf"
set +e
HINDSIGHT_CONSUMERS_CONF="$empty_conf" HINDSIGHT_CATALOG_SOURCE="$source" \
  "$SYNC" >"$output" 2>&1
ec=$?
set -e
[[ $ec -ne 0 ]] || fail "empty consumers conf should fail, got 0"
assert_contains 'attempted=0' "$output"

# ── 7. Issue #72: journal cannot authorise an out-of-tree undo target ────────
# A containment check whose both sides come from the journal certifies nothing.
# --undo must re-derive the boundary from operator conf + git toplevel.
victim="$TMP/outside-victim"
printf 'SAFE\n' > "$victim"
evil_journal="$TMP/evil-journal"
mkdir -p "$evil_journal"
printf 'EVIL\n' > "$evil_journal/file-0"
printf 'file\t%s\tfile-0\n' "$victim" > "$evil_journal/manifest.tsv"
set +e
HINDSIGHT_CONSUMERS_CONF="$conf" HINDSIGHT_CATALOG_SOURCE="$source" \
  "$SYNC" --undo "$evil_journal" >"$output" 2>&1
ec=$?
set -e
[[ $ec -ne 0 ]] || fail "poisoned journal undo must refuse, got 0; out=$(cat "$output")"
assert_contains 'not authorised' "$output"
[[ "$(cat "$victim")" == "SAFE" ]] || fail "poisoned journal overwrote path outside consumer roots"
# Legitimate undo of an authorised destination still works (section 5 above).

printf 'PASS: sync-failure-modes contract (issues #22 + #72)\n'
