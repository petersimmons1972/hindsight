#!/usr/bin/env bash
# Safely distribute the canonical failure-mode catalog to explicit consumers.
# See docs/SYNC.md.  It is dry-run by default; writes require --apply.

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly CATALOG="$REPO_ROOT/catalog/failure-modes.md"
readonly TARGET_REL="docs/vendor/hindsight/failure-modes.md"
readonly OWNERSHIP_MARKER='<!-- hindsight: vendored failure-mode catalog -->'

usage() {
  cat >&2 <<'EOF'
usage: bin/sync-failure-modes.sh [--dry-run | --apply --consumers FILE]
       bin/sync-failure-modes.sh --undo JOURNAL

Dry-run is the default.  --apply requires an explicit, non-empty consumer list.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

mode=dry-run
consumers=''
undo=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      [ "$mode" = dry-run ] || die '--dry-run and --apply cannot be combined'
      ;;
    --apply)
      [ "$mode" = dry-run ] || die '--dry-run and --apply cannot be combined'
      mode=apply
      ;;
    --consumers)
      [ "$#" -ge 2 ] || die '--consumers requires a path'
      consumers="$2"
      shift
      ;;
    --undo)
      [ "$#" -ge 2 ] || die '--undo requires a journal path'
      undo="$2"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*) die "unknown option: $1" ;;
    *) die "unexpected argument: $1" ;;
  esac
  shift
done

restore_journal() {
  local journal="$1" header target state backup extra
  [ -f "$journal" ] || die "undo journal not found: $journal"
  IFS= read -r header <"$journal" || die "undo journal is empty: $journal"
  [ "$header" = '# hindsight-sync-undo-v1' ] || die "unrecognised undo journal: $journal"

  while IFS=$'\t' read -r target state backup extra; do
    [ -n "$target" ] || continue
    [ -z "${extra:-}" ] || die "malformed undo journal row: $journal"
    case "$state" in
      absent)
        rm -f -- "$target"
        ;;
      untracked|tracked+hash:*)
        [ -f "$backup" ] || die "undo backup missing for: $target"
        mkdir -p -- "$(dirname "$target")"
        cp -- "$backup" "$target"
        ;;
      *) die "unknown undo state '$state' for: $target" ;;
    esac
  done < <(tail -n +2 -- "$journal")
  printf 'UNDO COMPLETE: %s\n' "$journal"
}

if [ -n "$undo" ]; then
  [ "$mode" = dry-run ] && [ -z "$consumers" ] || die '--undo cannot be combined with sync options'
  restore_journal "$undo"
  exit 0
fi

[ -n "$consumers" ] || die '--consumers is required; no default consumer file is used'
[ -f "$consumers" ] || die "consumer list not found: $consumers"
[ -s "$CATALOG" ] || die "canonical catalog not found or empty: $CATALOG"
[ "$mode" = dry-run ] || [ -n "$consumers" ] || die '--apply requires --consumers'
expected="$(mktemp "${TMPDIR:-/tmp}/hindsight-sync-expected.XXXXXX")"
trap 'rm -f -- "$expected"' EXIT
{ printf '%s\n' "$OWNERSHIP_MARKER"; cat "$CATALOG"; } >"$expected"

declare -a projects=()
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [ -n "$line" ] && projects+=("$line")
done <"$consumers"

if [ "${#projects[@]}" -eq 0 ]; then
  printf 'SUMMARY: attempted=0 succeeded=0 unchanged=0 failed=0\n' >&2
  printf 'ERROR: consumer list contains no consumers: %s\n' "$consumers" >&2
  exit 1
fi

journal_dir=''
journal=''
if [ "$mode" = apply ]; then
  journal_dir="$(mktemp -d "${TMPDIR:-/tmp}/hindsight-sync-undo.XXXXXX")"
  journal="$journal_dir/journal.tsv"
  printf '%s\n' '# hindsight-sync-undo-v1' >"$journal"
  index=0
  for project in "${projects[@]}"; do
    target="$project/$TARGET_REL"
    backup='-'
    if [ -e "$target" ]; then
      if git -C "$project" ls-files --error-unmatch -- "$TARGET_REL" >/dev/null 2>&1; then
        state="tracked+hash:$(sha256sum "$target" | awk '{print $1}')"
      else
        state=untracked
      fi
      backup="$journal_dir/$index.before"
      cp -- "$target" "$backup"
    else
      state=absent
    fi
    printf '%s\t%s\t%s\n' "$target" "$state" "$backup" >>"$journal"
    index=$((index + 1))
  done
  printf 'UNDO JOURNAL: %s\n' "$journal" >&2
  printf 'undo journal written before writes\n' >&2
else
  printf 'DRY RUN: no files will be written\n' >&2
  printf 'UNDO JOURNAL: none (dry-run)\n' >&2
  printf 'undo journal not created for dry-run\n' >&2
fi

attempted=0
succeeded=0
unchanged=0
failed=0
for project in "${projects[@]}"; do
  attempted=$((attempted + 1))
  target="$project/$TARGET_REL"
  if [ ! -d "$project" ]; then
    printf 'FAIL: %s (consumer directory missing)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  if [ -e "$target" ] && ! grep -Fqx "$OWNERSHIP_MARKER" "$target"; then
    printf 'FAIL: %s (refusing foreign target)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  if [ -f "$target" ] && cmp -s "$expected" "$target"; then
    printf 'UNCHANGED: %s\n' "$project" >&2
    unchanged=$((unchanged + 1))
    continue
  fi
  if [ "$mode" = dry-run ]; then
    printf 'WOULD UPDATE: %s -> %s\n' "$project" "$TARGET_REL" >&2
    succeeded=$((succeeded + 1))
    continue
  fi
  if ! mkdir -p -- "$(dirname "$target")"; then
    printf 'FAIL: %s (cannot create target directory)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  if ! cp -- "$expected" "$target"; then
    printf 'FAIL: %s (cannot write target)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  printf 'UPDATED: %s -> %s\n' "$project" "$TARGET_REL" >&2
  succeeded=$((succeeded + 1))
done

printf 'SUMMARY: attempted=%d succeeded=%d unchanged=%d failed=%d\n' \
  "$attempted" "$succeeded" "$unchanged" "$failed" >&2
[ "$failed" -eq 0 ]
