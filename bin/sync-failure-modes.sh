#!/usr/bin/env bash
# sync-failure-modes.sh — vendor the canonical failure-mode catalog to consumers.
#
# Dry-run is the default. Writes require an explicit --apply. Founder ruling
# 2026-08-03: Hindsight is not authorized to write into repositories it does
# not own without separate per-run sign-off (standing R9). Use --apply only
# against temporary test consumers unless that sign-off is in hand.
#
# Usage:
#   bin/sync-failure-modes.sh [--dry-run|--apply]
#   bin/sync-failure-modes.sh --undo <journal-dir>
#
# Environment:
#   HINDSIGHT_CONSUMERS_CONF   Override consumers list (default: conf/consumers.conf)
#   HINDSIGHT_CATALOG_SOURCE   Override catalog source (default: catalog/failure-modes.md)
#   HINDSIGHT_SYNC_JOURNAL_DIR Parent directory for undo journals (default: ${TMPDIR:-/tmp})
#
# Exit:
#   0  dry-run completed, or --apply with zero failures, or --undo restored
#   1  one or more consumers failed / zero consumers configured / config missing
#   2  unrecognised argument or bad usage
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONF="${HINDSIGHT_CONSUMERS_CONF:-$ROOT_DIR/conf/consumers.conf}"
CATALOG="${HINDSIGHT_CATALOG_SOURCE:-$ROOT_DIR/catalog/failure-modes.md}"
JOURNAL_PARENT="${HINDSIGHT_SYNC_JOURNAL_DIR:-${TMPDIR:-/tmp}}"
MODE="dry-run"
UNDO_DIR=""
PROG="$(basename "$0")"

usage() {
  printf 'Usage: %s [--dry-run|--apply]\n' "$PROG"
  printf '       %s --undo <journal-dir>\n' "$PROG"
}

# ── argument parse: unknown tokens abort with no fallback target (FM-146) ────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) MODE="dry-run"; shift ;;
    --apply)   MODE="apply"; shift ;;
    --undo)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      UNDO_DIR="$2"
      MODE="undo"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    -*)
      printf 'ERROR: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
    *)
      printf 'ERROR: unexpected argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

origin_fragment() {
  local origin="$1"
  local fragment
  if [[ "$origin" =~ ^git@github\.com:([^[:space:]]+/[^[:space:]]+)(\.git)?$ ]]; then
    fragment="${BASH_REMATCH[1]}"
  elif [[ "$origin" =~ ^https?://github\.com/([^[:space:]]+/[^[:space:]]+)(\.git)?$ ]]; then
    fragment="${BASH_REMATCH[1]}"
  elif [[ "$origin" =~ ^ssh://git@github\.com/([^[:space:]]+/[^[:space:]]+)(\.git)?$ ]]; then
    fragment="${BASH_REMATCH[1]}"
  else
    return 1
  fi
  printf '%s\n' "${fragment%.git}"
}

# ── --undo: restore every path listed in the journal ─────────────────────────
if [[ "$MODE" == "undo" ]]; then
  [[ -n "$UNDO_DIR" && -d "$UNDO_DIR" && -f "$UNDO_DIR/manifest.tsv" && ! -L "$UNDO_DIR/manifest.tsv" ]] || {
    printf 'ERROR: undo journal not found: %s\n' "${UNDO_DIR:-}" >&2
    exit 1
  }
  line_number=0
  while IFS=$'\t' read -r state target backup extra || [[ -n "${state:-}" ]]; do
    line_number=$((line_number + 1))
    [[ -z "${extra:-}" && -n "$state" && -n "$target" ]] || {
      printf 'ERROR: malformed undo journal at line %s\n' "$line_number" >&2
      exit 1
    }
    case "$state" in
      file)
        [[ -n "$backup" && -f "$UNDO_DIR/$backup" && ! -L "$UNDO_DIR/$backup" ]] || {
          printf 'ERROR: undo snapshot missing: %s\n' "$UNDO_DIR/$backup" >&2
          exit 1
        }
        mkdir -p "$(dirname "$target")"
        cp "$UNDO_DIR/$backup" "$target"
        ;;
      absent)
        if [[ -e "$target" || -L "$target" ]]; then
          rm -f "$target"
        fi
        ;;
      *)
        printf 'ERROR: unknown journal state %s at line %s\n' "$state" "$line_number" >&2
        exit 1
        ;;
    esac
  done < "$UNDO_DIR/manifest.tsv"
  printf 'sync-failure-modes: restored files from %s\n' "$UNDO_DIR"
  exit 0
fi

[[ -f "$CONF" ]] || { printf 'ERROR: consumers config not found: %s\n' "$CONF" >&2; exit 1; }
[[ -f "$CATALOG" ]] || { printf 'ERROR: canonical catalog not found: %s\n' "$CATALOG" >&2; exit 1; }

expected="$(mktemp "${TMPDIR:-/tmp}/hindsight-catalog.XXXXXX")"
cleanup() {
  rm -f "$expected"
}
trap cleanup EXIT
printf '<!-- GENERATED — DO NOT EDIT, canonical source is hindsight -->\n\n' > "$expected"
cat "$CATALOG" >> "$expected"

# First pass: resolve every consumer and decide the action. Writes happen only
# after the undo journal is printed (Law 3 / R6).
declare -a PLAN_STATUS=()
declare -a PLAN_REPO=()
declare -a PLAN_ROOT=()
declare -a PLAN_DEST=()
declare -a PLAN_NOTE=()

attempted=0
would_write=0
up_to_date=0
wrote=0
failed=0
skipped=0
refused=0

while IFS= read -r raw || [[ -n "$raw" ]]; do
  [[ "$raw" =~ ^[[:space:]]*($|#) ]] && continue
  attempted=$((attempted + 1))

  if [[ "$raw" != *:* ]]; then
    PLAN_STATUS+=("failed")
    PLAN_REPO+=("$raw")
    PLAN_ROOT+=("")
    PLAN_DEST+=("")
    PLAN_NOTE+=("invalid consumer entry")
    failed=$((failed + 1))
    continue
  fi

  repo="${raw%%:*}"
  required_fragment="${raw#*:}"
  if [[ -z "$repo" || -z "$required_fragment" || "$required_fragment" == *:* ]]; then
    PLAN_STATUS+=("failed")
    PLAN_REPO+=("$raw")
    PLAN_ROOT+=("")
    PLAN_DEST+=("")
    PLAN_NOTE+=("invalid consumer entry")
    failed=$((failed + 1))
    continue
  fi

  if [[ ! -d "$repo" ]] || ! repo_root="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)"; then
    PLAN_STATUS+=("skipped-not-a-repo")
    PLAN_REPO+=("$repo")
    PLAN_ROOT+=("")
    PLAN_DEST+=("")
    PLAN_NOTE+=("not a git repo")
    skipped=$((skipped + 1))
    continue
  fi

  # Containment boundary: process config + git toplevel of that path — never a
  # value the consumer journal row could invent (issue #72).
  if ! origin="$(git -C "$repo" remote get-url origin 2>/dev/null)"; then
    PLAN_STATUS+=("skipped-not-a-repo")
    PLAN_REPO+=("$repo")
    PLAN_ROOT+=("$repo_root")
    PLAN_DEST+=("")
    PLAN_NOTE+=("origin missing")
    skipped=$((skipped + 1))
    continue
  fi
  if ! actual_fragment="$(origin_fragment "$origin")" || [[ "$actual_fragment" != "$required_fragment" ]]; then
    PLAN_STATUS+=("refused-mismatch")
    PLAN_REPO+=("$repo")
    PLAN_ROOT+=("$repo_root")
    PLAN_DEST+=("")
    PLAN_NOTE+=("expected ${required_fragment}, got ${origin}")
    refused=$((refused + 1))
    continue
  fi

  destination="$repo_root/docs/failure-modes.md"
  if [[ -L "$repo_root/docs" || -L "$destination" ]]; then
    PLAN_STATUS+=("refused-unsafe-path")
    PLAN_REPO+=("$repo")
    PLAN_ROOT+=("$repo_root")
    PLAN_DEST+=("$destination")
    PLAN_NOTE+=("vendored path is a symlink")
    refused=$((refused + 1))
    continue
  fi
  if [[ -e "$repo_root/docs" && ! -d "$repo_root/docs" ]]; then
    PLAN_STATUS+=("failed")
    PLAN_REPO+=("$repo")
    PLAN_ROOT+=("$repo_root")
    PLAN_DEST+=("$destination")
    PLAN_NOTE+=("docs path exists and is not a directory")
    failed=$((failed + 1))
    continue
  fi

  if [[ -f "$destination" ]] && cmp -s "$expected" "$destination"; then
    PLAN_STATUS+=("up-to-date")
    PLAN_REPO+=("$repo")
    PLAN_ROOT+=("$repo_root")
    PLAN_DEST+=("$destination")
    PLAN_NOTE+=("")
    up_to_date=$((up_to_date + 1))
  else
    PLAN_STATUS+=("would-write")
    PLAN_REPO+=("$repo")
    PLAN_ROOT+=("$repo_root")
    PLAN_DEST+=("$destination")
    PLAN_NOTE+=("")
    would_write=$((would_write + 1))
  fi
done < "$CONF"

if [[ $attempted -eq 0 ]]; then
  printf 'ERROR: attempted=0 — consumers config listed no entries\n' >&2
  printf 'summary: attempted=0 wrote=0 failed=0 skipped=0 refused=0 up-to-date=0 would-write=0\n' >&2
  exit 1
fi

printf '%-20s %s\n' STATUS REPOSITORY
i=0
while [[ $i -lt ${#PLAN_STATUS[@]} ]]; do
  status="${PLAN_STATUS[$i]}"
  repo="${PLAN_REPO[$i]}"
  note="${PLAN_NOTE[$i]}"
  if [[ -n "$note" ]]; then
    printf '%-20s %s (%s)\n' "$status" "$repo" "$note"
  else
    printf '%-20s %s\n' "$status" "$repo"
  fi
  i=$((i + 1))
done

if [[ "$MODE" != "apply" ]]; then
  printf 'summary: attempted=%s would-write=%s up-to-date=%s failed=%s skipped=%s refused=%s\n' \
    "$attempted" "$would_write" "$up_to_date" "$failed" "$skipped" "$refused"
  printf 'DRY-RUN: nothing was written. Re-run with --apply to write (requires founder sign-off for real consumers).\n'
  # Dry-run is informational even when some consumers would be refused; exit 0
  # unless the config itself was empty (handled above).
  exit 0
fi

# ── --apply: emit undo journal BEFORE any write (Law 3 / R6) ─────────────────
journal="$(mktemp -d "$JOURNAL_PARENT/hindsight-sync-journal.XXXXXX")"
manifest="$journal/manifest.tsv"
: > "$manifest"
snap_i=0
i=0
while [[ $i -lt ${#PLAN_STATUS[@]} ]]; do
  if [[ "${PLAN_STATUS[$i]}" == "would-write" ]]; then
    dest="${PLAN_DEST[$i]}"
    if [[ -f "$dest" && ! -L "$dest" ]]; then
      snap="file-$snap_i"
      cp "$dest" "$journal/$snap"
      printf 'file\t%s\t%s\n' "$dest" "$snap" >> "$manifest"
    else
      printf 'absent\t%s\t-\n' "$dest" >> "$manifest"
    fi
    snap_i=$((snap_i + 1))
  fi
  i=$((i + 1))
done

cat <<UNDO

=== UNDO (printed before any write, per Law 3) ===
  journal: $journal
  restore with:
    $PROG --undo $journal
=== END UNDO ===

UNDO

# Second pass: perform writes. A single consumer failure must not abort the
# batch — capture errors and continue (issue #22 / plan-04 T1).
i=0
while [[ $i -lt ${#PLAN_STATUS[@]} ]]; do
  if [[ "${PLAN_STATUS[$i]}" != "would-write" ]]; then
    i=$((i + 1))
    continue
  fi
  repo="${PLAN_REPO[$i]}"
  repo_root="${PLAN_ROOT[$i]}"
  dest="${PLAN_DEST[$i]}"

  write_ok=0
  if (
    set -e
    mkdir -p "$repo_root/docs"
    # Bind the directory fd so a later pathname swap cannot redirect the write
    # outside the resolved consumer root.
    exec {docs_fd}<"$repo_root/docs"
    opened_docs="$(cd "/proc/self/fd/$docs_fd" && pwd -P)"
    expected_docs="$(cd "$repo_root/docs" && pwd -P)"
    if [[ "$opened_docs" != "$expected_docs" ]]; then
      exec {docs_fd}<&-
      exit 10
    fi
    staged_file="$(mktemp "/proc/self/fd/$docs_fd/.hindsight-catalog.XXXXXX")"
    cat "$expected" > "$staged_file"
    chmod 0644 "$staged_file"
    mv -f "$staged_file" "/proc/self/fd/$docs_fd/failure-modes.md"
    exec {docs_fd}<&-
  ); then
    write_ok=1
  else
    write_ok=0
  fi

  if [[ $write_ok -eq 1 ]]; then
    printf '%-20s %s\n' wrote "$repo"
    wrote=$((wrote + 1))
    would_write=$((would_write - 1))
  else
    printf '%-20s %s (write failed)\n' failed "$repo" >&2
    failed=$((failed + 1))
    would_write=$((would_write - 1))
  fi
  i=$((i + 1))
done

printf 'summary: attempted=%s wrote=%s up-to-date=%s failed=%s skipped=%s refused=%s would-write=%s\n' \
  "$attempted" "$wrote" "$up_to_date" "$failed" "$skipped" "$refused" "$would_write"
printf 'undo journal retained at: %s\n' "$journal"

if [[ $failed -gt 0 ]]; then
  exit 1
fi
exit 0
