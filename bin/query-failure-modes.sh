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
# Every run states its own scope (hindsight#184, FM-606). The two pointer files
# are a curated SUBSET of the canonical population — `catalog/criticality.jsonl`,
# the file `bin/synthesize-pointer.py` renders them from. Without the
# denominator, a miss here reads as "no such failure mode exists", which is the
# dangerous direction: that false NONE is the premise used to demote a standing
# rule. So the scope line is printed on every path, hit or miss, and the miss
# path says in words that a NONE in the subset is not a NONE in the catalog.
#
# Environment:
#   POINTER      Override the CRITICAL pointer path (default: <repo>/docs/POINTER.md).
#   HIGH         Override the HIGH pointer path (default: <repo>/docs/HIGH.md).
#   CRITICALITY  Override the canonical population file
#                (default: <repo>/catalog/criticality.jsonl).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
POINTER="${POINTER:-$REPO_ROOT/docs/POINTER.md}"
HIGH="${HIGH:-$REPO_ROOT/docs/HIGH.md}"
CRITICALITY="${CRITICALITY:-$REPO_ROOT/catalog/criticality.jsonl}"
MAX_LINES=10

# Rows actually greppable in the two pointer files: the lines synthesize-pointer.py
# emits, one per FM.
subset_size() {
    local file total=0 n
    for file in "$POINTER" "$HIGH"; do
        [[ -f "$file" ]] || continue
        n="$(grep -c '^- \*\*FM-' "$file" || true)"
        total=$(( total + n ))
    done
    printf '%s\n' "$total"
}

# The population those rows were drawn from: distinct fm_id in criticality.jsonl
# (a later line for the same id is a re-triage of the same FM, not a second one).
corpus_size() {
    [[ -f "$CRITICALITY" ]] || { printf 'unknown\n'; return 0; }
    grep -oE '"fm_id"[[:space:]]*:[[:space:]]*"[^"]+"' "$CRITICALITY" \
        | sort -u | grep -c '^' || true
}

# A scope line is only worth printing if it is TRUE. The fraction is claimed
# ONLY when the two numbers can both be read and are consistent with each other:
# the subset cannot be larger than the population it was rendered from, so
# `258 of 0` (an empty or stale criticality.jsonl beside populated pointer files)
# is not a small inaccuracy, it is a mathematically impossible sentence. In that
# case, and when the population file cannot be read at all, the run says the
# coverage is UNKNOWN rather than printing a number it cannot stand behind — the
# same reason this script prints a scope line at all.
SUBSET_ROWS="$(subset_size)"
CORPUS_ROWS="$(corpus_size)"
if [[ "$CORPUS_ROWS" == "unknown" ]]; then
    SCOPE_NOTE="scope: searched ${SUBSET_ROWS} rows in docs/POINTER.md + docs/HIGH.md. \
The canonical population (${CRITICALITY}) could not be read, so this run claims NO coverage \
fraction: treat its coverage of the catalog as UNKNOWN."
elif (( CORPUS_ROWS < SUBSET_ROWS )); then
    SCOPE_NOTE="scope: searched ${SUBSET_ROWS} rows in docs/POINTER.md + docs/HIGH.md, but \
${CRITICALITY} reports only ${CORPUS_ROWS} canonical failure modes — fewer than the pointer files \
contain. The pointer files and the population they are rendered from DISAGREE, so this run claims \
NO coverage fraction: treat its coverage as UNKNOWN and re-run bin/synthesize-pointer.py."
else
    SCOPE_NOTE="scope: searched ${SUBSET_ROWS} of ${CORPUS_ROWS} canonical failure modes \
(docs/POINTER.md + docs/HIGH.md, the CRITICAL+HIGH subset of catalog/criticality.jsonl)."
fi

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
        echo "$SCOPE_NOTE" >&2
        exit 0
    fi
done

echo "not-in-subset: no match in docs/POINTER.md or docs/HIGH.md." >&2
echo "$SCOPE_NOTE" >&2
echo "This is NOT an all-clear: a miss here does not mean the catalog holds no such failure mode, only that no row in the CRITICAL+HIGH subset matched these keywords. Broaden the query (fewer/single keywords -- terms are ANDed) or search catalog/failure-modes.md directly before concluding NONE." >&2
echo "Falling back to the full L1 corpus below (advisory, not authoritative)." >&2
exec python3 "$REPO_ROOT/bin/similar-causes.py" "$*"
