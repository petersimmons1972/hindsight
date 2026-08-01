#!/usr/bin/env bash
# Vendor the canonical failure-mode catalog without mutating consumer git state.
#
# A consumer's origin is checked before any write: this is deliberately a
# distribution gate, not a convenient bulk copy command. Each valid consumer
# receives a status row; write failures are reported after the full batch.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONF="${HINDSIGHT_CONSUMERS_CONF:-$ROOT_DIR/conf/consumers.conf}"
CATALOG="${HINDSIGHT_CATALOG_SOURCE:-$ROOT_DIR/catalog/failure-modes.md}"
MODE="dry-run"

usage() {
  printf 'Usage: %s [--dry-run|--apply]\n' "$0"
}

case "${1:-}" in
  '') ;;
  --dry-run) MODE="dry-run" ;;
  --apply) MODE="apply" ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

[[ -f "$CONF" ]] || { printf 'ERROR: consumers config not found: %s\n' "$CONF" >&2; exit 1; }
[[ -f "$CATALOG" ]] || { printf 'ERROR: canonical catalog not found: %s\n' "$CATALOG" >&2; exit 1; }

expected="$(mktemp "${TMPDIR:-/tmp}/hindsight-catalog.XXXXXX")"
trap 'rm -f "$expected"' EXIT
printf '<!-- GENERATED — DO NOT EDIT, canonical source is hindsight -->\n\n' > "$expected"
cat "$CATALOG" >> "$expected"

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

write_catalog() {
  local repo_root="$1"
  local destination="$2"
  local docs_dir="$repo_root/docs"
  local docs_fd=""
  local opened_docs
  local staged_file=""

  if ! mkdir -p "$docs_dir"; then
    return 1
  fi
  if [[ -L "$docs_dir" || -L "$destination" || -d "$destination" ]]; then
    return 1
  fi
  # Keep the directory open while writing. A later pathname swap cannot
  # redirect /proc/self/fd/$docs_fd to a different directory.
  if ! exec {docs_fd}<"$docs_dir"; then
    return 1
  fi
  if ! opened_docs="$(cd "/proc/self/fd/$docs_fd" && pwd -P)" || [[ "$opened_docs" != "$docs_dir" ]]; then
    exec {docs_fd}<&- || true
    return 1
  fi
  if [[ -L "$destination" || -d "$destination" ]]; then
    exec {docs_fd}<&- || true
    return 1
  fi
  if ! staged_file="$(mktemp "/proc/self/fd/$docs_fd/.hindsight-catalog.XXXXXX")"; then
    exec {docs_fd}<&- || true
    return 1
  fi
  if ! cat "$expected" > "$staged_file" || ! chmod 0644 "$staged_file"; then
    rm -f "$staged_file" || true
    exec {docs_fd}<&- || true
    return 1
  fi
  # -T prevents a destination directory from becoming a staging-file sink.
  if ! mv -fT "$staged_file" "/proc/self/fd/$docs_fd/failure-modes.md"; then
    rm -f "$staged_file" || true
    exec {docs_fd}<&- || true
    return 1
  fi
  if ! exec {docs_fd}<&-; then
    return 1
  fi
}

printf '%-20s %s\n' STATUS REPOSITORY
had_write_failure=0
while IFS= read -r raw || [[ -n "$raw" ]]; do
  [[ "$raw" =~ ^[[:space:]]*($|#) ]] && continue
  if [[ "$raw" != *:* ]]; then
    printf 'ERROR: invalid consumer entry: %s\n' "$raw" >&2
    exit 1
  fi
  repo="${raw%%:*}"
  required_fragment="${raw#*:}"
  if [[ -z "$repo" || -z "$required_fragment" || "$required_fragment" == *:* ]]; then
    printf 'ERROR: invalid consumer entry: %s\n' "$raw" >&2
    exit 1
  fi

  if [[ ! -d "$repo" ]] || ! repo_root="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)"; then
    printf '%-20s %s (not a git repo)\n' skipped-not-a-repo "$repo" >&2
    continue
  fi
  if ! origin="$(git -C "$repo" remote get-url origin 2>/dev/null)"; then
    printf '%-20s %s (origin missing)\n' skipped-not-a-repo "$repo" >&2
    continue
  fi
  if ! actual_fragment="$(origin_fragment "$origin")"; then
    printf '%-20s %s (origin %s)\n' unrecognized-origin "$repo" "$origin" >&2
    continue
  fi
  if [[ "$actual_fragment" != "$required_fragment" ]]; then
    printf '%-20s %s (expected %s, got %s)\n' refused-mismatch "$repo" "$required_fragment" "$origin" >&2
    continue
  fi

  destination="$repo_root/docs/failure-modes.md"
  if [[ -L "$repo_root/docs" || -L "$destination" ]]; then
    printf '%-20s %s (vendored path is a symlink)\n' refused-unsafe-path "$repo" >&2
    continue
  fi
  if [[ -f "$destination" ]]; then
    if cmp -s "$expected" "$destination"; then
      printf '%-20s %s\n' up-to-date "$repo"
      continue
    fi
    compare_status=$?
    if (( compare_status > 1 )); then
      printf '%-20s %s (could not compare existing catalog)\n' failed-write "$repo" >&2
      had_write_failure=1
      continue
    fi
  fi

  if [[ "$MODE" == dry-run ]]; then
    printf '%-20s %s\n' would-write "$repo"
  elif write_catalog "$repo_root" "$destination"; then
    printf '%-20s %s\n' wrote "$repo"
  else
    printf '%-20s %s (could not update vendored catalog)\n' failed-write "$repo" >&2
    had_write_failure=1
  fi
done < "$CONF"

if (( had_write_failure )); then
  exit 1
fi
