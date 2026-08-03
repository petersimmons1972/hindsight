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

# Print the only filesystem path this tool is allowed to write for a consumer.
# realpath -m follows existing ancestors (including links) while allowing the
# leaf to be absent, so a link anywhere below the consumer root is detected.
contained_target() {
  local project="$1" root intended resolved
  intended="$project/$TARGET_REL"
  root="$(realpath -- "$project")" || {
    printf 'ERROR: cannot resolve consumer root: %s\n' "$project" >&2
    return 1
  }
  resolved="$(realpath -m -- "$intended")" || {
    printf 'ERROR: cannot resolve target: intended=%s\n' "$intended" >&2
    return 1
  }
  if [ "$resolved" != "$root/$TARGET_REL" ]; then
    printf 'ERROR: target escapes consumer root: intended=%s resolved=%s root=%s\n' \
      "$intended" "$resolved" "$root" >&2
    return 1
  fi
  printf '%s\n' "$resolved"
}

restore_backup_atomically() {
  local backup="$1" target="$2" parent temp
  parent="$(dirname "$target")"
  mkdir -p -- "$parent" || die "cannot create undo target directory: $parent"
  temp="$(mktemp "$parent/.hindsight-sync-undo.XXXXXX")" || die "cannot create undo temp file: $parent"
  if ! cp --no-dereference -- "$backup" "$temp"; then
    rm -f -- "$temp"
    die "cannot restore undo backup: $backup"
  fi
  if ! mv -T -- "$temp" "$target"; then
    rm -f -- "$temp"
    die "cannot install undo backup: $target"
  fi
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
      untracked|tracked+hash:*|tracked+link)
        { [ -e "$backup" ] || [ -L "$backup" ]; } || die "undo backup missing for: $target"
        restore_backup_atomically "$backup" "$target"
        ;;
      invalid|directory)
        # These entries were refused before any write, so undo must not alter
        # them; retaining rows keeps the pre-write journal complete.
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
    resolved_target=''
    if [ -L "$target" ]; then
      if git -C "$project" ls-files --error-unmatch -- "$TARGET_REL" >/dev/null 2>&1; then
        state=tracked+link
      else
        state=untracked
      fi
      backup="$journal_dir/$index.before"
      cp --no-dereference -- "$target" "$backup"
    elif ! resolved_target="$(contained_target "$project")"; then
      state=invalid
    elif [ -d "$resolved_target" ]; then
      state=directory
    elif [ -e "$resolved_target" ] || [ -L "$resolved_target" ]; then
      if git -C "$project" ls-files --error-unmatch -- "$TARGET_REL" >/dev/null 2>&1; then
        state="tracked+hash:$(sha256sum "$resolved_target" | awk '{print $1}')"
      else
        state=untracked
      fi
      backup="$journal_dir/$index.before"
      cp --no-dereference -- "$resolved_target" "$backup"
    else
      state=absent
    fi
    printf '%s\t%s\t%s\n' "${resolved_target:-$target}" "$state" "$backup" >>"$journal"
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
  if [ -L "$target" ]; then
    printf 'ERROR: symlinked target: %s -> %s\n' "$target" "$(readlink -- "$target")" >&2
    failed=$((failed + 1))
    continue
  fi
  if ! resolved_target="$(contained_target "$project")"; then
    failed=$((failed + 1))
    continue
  fi
  if [ -d "$resolved_target" ]; then
    printf 'FAIL: %s (directory target: %s)\n' "$project" "$resolved_target" >&2
    failed=$((failed + 1))
    continue
  fi
  if [ -e "$resolved_target" ]; then
    link_count="$(stat -c %h -- "$resolved_target")" || {
      printf 'FAIL: %s (cannot inspect target link count)\n' "$project" >&2
      failed=$((failed + 1))
      continue
    }
    if [ "$link_count" -gt 1 ]; then
      printf 'FAIL: %s (hardlinked target: %s, links=%s)\n' "$project" "$resolved_target" "$link_count" >&2
      failed=$((failed + 1))
      continue
    fi
  fi
  if [ -e "$resolved_target" ] && ! grep -Fqx "$OWNERSHIP_MARKER" "$resolved_target"; then
    printf 'FAIL: %s (refusing foreign target)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  if [ -f "$resolved_target" ] && cmp -s "$expected" "$resolved_target"; then
    printf 'UNCHANGED: %s\n' "$project" >&2
    unchanged=$((unchanged + 1))
    continue
  fi
  if [ "$mode" = dry-run ]; then
    printf 'WOULD UPDATE: %s -> %s\n' "$project" "$resolved_target" >&2
    succeeded=$((succeeded + 1))
    continue
  fi
  target_dir="$(dirname "$resolved_target")"
  if ! mkdir -p -- "$target_dir"; then
    printf 'FAIL: %s (cannot create target directory)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  if ! rechecked_target="$(contained_target "$project")" || [ "$rechecked_target" != "$resolved_target" ]; then
    printf 'FAIL: %s (target changed before write)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  if ! temp_target="$(mktemp "$target_dir/.hindsight-sync.XXXXXX")"; then
    printf 'FAIL: %s (cannot create temporary target)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  if ! cp -- "$expected" "$temp_target" || ! mv -T -- "$temp_target" "$resolved_target"; then
    rm -f -- "$temp_target"
    printf 'FAIL: %s (cannot atomically write target)\n' "$project" >&2
    failed=$((failed + 1))
    continue
  fi
  printf 'UPDATED: %s -> %s\n' "$project" "$resolved_target" >&2
  succeeded=$((succeeded + 1))
done

printf 'SUMMARY: attempted=%d succeeded=%d unchanged=%d failed=%d\n' \
  "$attempted" "$succeeded" "$unchanged" "$failed" >&2
[ "$failed" -eq 0 ]
