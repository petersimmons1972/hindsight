#!/usr/bin/env bash
# correct-failure-mode.sh — append a superseding record for a refuted catalog row.
#
# Usage:
#   correct-failure-mode.sh -t TIER --disposition KIND --recurrence-of c-NNN|none \
#     FM-NNN "REFUTATION" "CORRECTED LESSON"
#
# The catalog is append-only.  A correction is therefore an ordinary canonical
# add whose concrete-instance text names the old row and says it is superseded;
# add-failure-mode.sh performs the one sanctioned write transaction and derives
# L1/L2/pointer consumers.  FM-332 established this CORRECTION record precedent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ADD_TOOL="$REPO_ROOT/bin/add-failure-mode.sh"

usage() {
    sed -n '2,10p' "$0" | sed 's/^# \?//'
    exit "${1:-1}"
}

TIER=""
DISPOSITION=""
RECURRENCE=""
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -t|--tier)
            [[ $# -ge 2 && -z "$TIER" ]] || { echo "ERROR: --tier requires one value" >&2; exit 1; }
            TIER="$2"
            shift 2
            ;;
        --disposition)
            [[ $# -ge 2 && -z "$DISPOSITION" ]] || { echo "ERROR: --disposition requires one value" >&2; exit 1; }
            DISPOSITION="$2"
            shift 2
            ;;
        --recurrence-of)
            [[ $# -ge 2 && -z "$RECURRENCE" ]] || { echo "ERROR: --recurrence-of requires one value" >&2; exit 1; }
            RECURRENCE="$2"
            shift 2
            ;;
        -h|--help) usage 0 ;;
        --) shift; POSITIONAL+=("$@"); break ;;
        -*) echo "ERROR: unknown flag: $1" >&2; usage ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done

[[ ${#POSITIONAL[@]} -eq 3 ]] || {
    echo "ERROR: expected TARGET_ID, REFUTATION, and CORRECTED_LESSON" >&2
    usage
}
[[ -n "$TIER" && -n "$DISPOSITION" && -n "$RECURRENCE" ]] || {
    echo "ERROR: --tier, --disposition, and --recurrence-of are required" >&2
    exit 1
}

TARGET_ID="${POSITIONAL[0]}"
REFUTATION="${POSITIONAL[1]}"
LESSON="${POSITIONAL[2]}"
[[ "$TARGET_ID" =~ ^FM-[0-9]{2,3}$ ]] || {
    echo "ERROR: TARGET_ID must be a canonical FM-NNN ID" >&2
    exit 1
}

CATALOG="${CATALOG:-$REPO_ROOT/catalog/failure-modes.md}"
[[ -f "$CATALOG" ]] || { echo "ERROR: catalog not found: $CATALOG" >&2; exit 1; }
CLASS="$({ awk -F '|' -v id="$TARGET_ID" '
    $0 ~ "^\\| " id " \\|" {
        value = $3
        sub(/^[[:space:]]+/, "", value)
        sub(/[[:space:]]+$/, "", value)
        print value
    }
' "$CATALOG"; })"
[[ $(printf '%s\n' "$CLASS" | sed '/^$/d' | wc -l) -eq 1 ]] || {
    echo "ERROR: target $TARGET_ID must name exactly one canonical catalog row" >&2
    exit 1
}

DESCRIPTION="CORRECTION: $TARGET_ID is superseded, not erased. Refuted stated cause: $REFUTATION Supersedes $TARGET_ID."
"$ADD_TOOL" \
    -c "$CLASS" \
    -t "$TIER" \
    --disposition "$DISPOSITION" \
    --recurrence-of "$RECURRENCE" \
    "$LESSON" "$DESCRIPTION"
