#!/usr/bin/env bash
# query-failure-modes.sh — on-demand failure-mode lookup by keyword.
#
# Usage:
#   query-failure-modes.sh <keyword...>
#
# Search order, each stage tried only if the previous found nothing:
#   1. docs/POINTER.md  — CRITICAL tier, tiny, safe to load whole (not needed
#      here since we only grep it, but it's small enough that it wouldn't hurt).
#   2. docs/HIGH.md      — HIGH tier, too large to preload. NEVER cat/Read this
#      file directly; only grep it through this script.
#   3. similar-causes.py — advisory token-overlap fallback over the full L1
#      corpus, only reached if neither pointer file matched.
#
# Output is always capped at MAX_LINES matching lines, regardless of stage, so
# a broad keyword can never dump an entire pointer file into a session.
#
# This never loads catalog/failure-modes.md (57K tokens) into a session — see
# hindsight's own CLAUDE.md: "Spool to disk, never to context."
#
# Environment:
#   POINTER   Override the CRITICAL pointer path (default: <repo>/docs/POINTER.md).
#   HIGH      Override the HIGH pointer path (default: <repo>/docs/HIGH.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
POINTER="${POINTER:-$REPO_ROOT/docs/POINTER.md}"
HIGH="${HIGH:-$REPO_ROOT/docs/HIGH.md}"
MAX_LINES=10

if [[ $# -eq 0 ]]; then
    echo "usage: query-failure-modes.sh <keyword...>" >&2
    exit 1
fi

search_file() {
    local file="$1"
    shift
    [[ -f "$file" ]] || return 1
    local matches
    matches="$(cat "$file")"
    local word
    for word in "$@"; do
        matches="$(printf '%s\n' "$matches" | grep -i -F -- "$word" || true)"
        [[ -n "$matches" ]] || return 1
    done
    printf '%s\n' "$matches"
}

for source in "$POINTER" "$HIGH"; do
    if results="$(search_file "$source" "$@")"; then
        total="$(printf '%s\n' "$results" | grep -c '^' || true)"
        printf '%s\n' "$results" | head -n "$MAX_LINES"
        if [[ "$total" -gt "$MAX_LINES" ]]; then
            echo "... showing $MAX_LINES of $total matches in ${source#"$REPO_ROOT"/}." >&2
        fi
        exit 0
    fi
done

echo "No match in POINTER.md or HIGH.md; falling back to full corpus (advisory, not authoritative)." >&2
exec python3 "$REPO_ROOT/bin/similar-causes.py" "$*"
