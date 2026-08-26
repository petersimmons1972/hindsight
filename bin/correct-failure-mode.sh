#!/usr/bin/env bash
# correct-failure-mode.sh — append a superseding record for a refuted catalog row.
#
# Usage:
#   correct-failure-mode.sh -t TIER --disposition KIND \
#     --ladder-rung RUNG|--ladder-rung-infeasible REASON \
#     --recurrence-of c-NNN|none \
#     FM-NNN "REFUTATION" "CORRECTED LESSON"
#
# A correction preserves every substantive cell on the original row, prepends
# an explicit tombstone marker naming the replacement, and appends the complete
# superseding row. add-failure-mode.sh stages and guards that catalog+ledger
# state before one atomic directory exchange, then derives L1/L2 consumers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ADD_TOOL="$REPO_ROOT/bin/add-failure-mode.sh"

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \?//'
    exit "${1:-1}"
}

TIER=""
DISPOSITION=""
LADDER_ARGS=()
LADDER_SEEN=0
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
        --ladder-rung)
            [[ $# -ge 2 && $LADDER_SEEN -eq 0 ]] || {
                echo "ERROR: provide exactly one of --ladder-rung or --ladder-rung-infeasible" >&2
                exit 1
            }
            LADDER_ARGS=(--ladder-rung "$2")
            LADDER_SEEN=1
            shift 2
            ;;
        --ladder-rung-infeasible)
            [[ $# -ge 2 && $LADDER_SEEN -eq 0 ]] || {
                echo "ERROR: provide exactly one of --ladder-rung or --ladder-rung-infeasible" >&2
                exit 1
            }
            LADDER_ARGS=(--ladder-rung-infeasible "$2")
            LADDER_SEEN=1
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
[[ -n "$TIER" && -n "$DISPOSITION" && -n "$RECURRENCE" && $LADDER_SEEN -eq 1 ]] || {
    echo "ERROR: --tier, --disposition, --ladder-rung (or --ladder-rung-infeasible), and --recurrence-of are required" >&2
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
CLASS="$(python3 - "$REPO_ROOT" "$CATALOG" "$TARGET_ID" <<'PYEOF'
import sys
from pathlib import Path

repo, catalog, target = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(repo))
from pipeline.reconcile_l1 import parse_catalog_rows

rows = [
    row for row in parse_catalog_rows(catalog.read_text(encoding="utf-8"))
    if row.fm_id == target
]
if len(rows) != 1:
    raise SystemExit(f"ERROR: target {target} must name exactly one canonical catalog row")
print(rows[0].class_hint)
PYEOF
)"
[[ $(printf '%s\n' "$CLASS" | sed '/^$/d' | wc -l) -eq 1 ]] || {
    echo "ERROR: target $TARGET_ID must name exactly one canonical catalog row" >&2
    exit 1
}

DESCRIPTION="CORRECTION: $TARGET_ID is superseded, not erased. Refuted stated cause: $REFUTATION Supersedes $TARGET_ID."
"$ADD_TOOL" \
    -c "$CLASS" \
    -t "$TIER" \
    --disposition "$DISPOSITION" \
    "${LADDER_ARGS[@]}" \
    --recurrence-of "$RECURRENCE" \
    --supersedes "$TARGET_ID" \
    "$LESSON" "$DESCRIPTION"
