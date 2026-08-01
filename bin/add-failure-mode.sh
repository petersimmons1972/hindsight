#!/usr/bin/env bash
# add-failure-mode.sh — append a new failure-mode entry to the canonical catalog.
#
# Usage:
#   add-failure-mode.sh [OPTIONS] TITLE [DESCRIPTION]
#   add-failure-mode.sh [OPTIONS]   # prompts for TITLE if stdin is a tty
#
# Options:
#   -c CLASS    Bug class letter (A-L) or explicit bug-class label.
#   -i ISSUE    GitHub issue number (appended to the concrete-instance column).
#   -a          Mark the row as automatable (`Auto?` = 🤖).
#   -h          Show this help.
#
# TITLE is the check statement / rule (one sentence).
# DESCRIPTION is optional concrete-instance context for the catalog row.
#
# A backup is made before every write.
# The script appends only a canonical table row and relies on the catalog guard
# to keep IDs unique and numerically ordered.
#
# Environment:
#   CATALOG     Override catalog path (default:
#               <repo>/docs/failure-modes-standard.md).
#               Useful for testing: CATALOG=/tmp/fms-test.md add-failure-mode.sh ...
#
# Install: ln -sf ~/projects/claude-codex/scripts/add-failure-mode.sh ~/bin/add-failure-mode.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CATALOG="${CATALOG:-$REPO_ROOT/docs/failure-modes-standard.md}"

usage() {
    grep '^#' "$0" | sed 's/^# \?//'
    exit 1
}

CLASS=""
ISSUE=""
AUTO=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--class) CLASS="${2^^}"; shift 2 ;;
        -i|--issue) ISSUE="$2"; shift 2 ;;
        -a|--auto)  AUTO=1; shift ;;
        -h|--help)  usage ;;
        --)         shift; break ;;
        -*)         echo "unknown flag: $1" >&2; usage ;;
        *)          break ;;
    esac
done

TITLE="${1:-}"
DESC="${2:-}"

# If no title given, prompt when interactive, read line when piped
if [[ -z "$TITLE" ]]; then
    if [[ -t 0 ]]; then
        read -r -p "Check/title (one sentence): " TITLE
    else
        read -r TITLE
    fi
fi

[[ -z "$TITLE" ]] && { echo "ERROR: title is required" >&2; exit 1; }
[[ -f "$CATALOG" ]] || { echo "ERROR: catalog not found: $CATALOG" >&2; exit 1; }

FM_ID="$(python3 "$REPO_ROOT/scripts/failure_mode_catalog_guard.py" --next-id "$CATALOG")"

class_label() {
    case "${1^^}" in
        A) echo "Identity vs. Routing" ;;
        B) echo "Install / Config Layout Integrity" ;;
        C) echo "Portability" ;;
        D) echo "Fail-Loud" ;;
        E) echo "Thermal / Resource-Role Safety" ;;
        F) echo "Repo Hygiene / Canonical Home" ;;
        G) echo "Deploy / Verify Discipline" ;;
        H) echo "Ephemeral Resource Leakage / Host Exhaustion" ;;
        I) echo "Container Runtime — Design" ;;
        J) echo "Container Runtime — Operational" ;;
        K) echo "Agent Runtime / Coordination" ;;
        L) echo "GitOps Declarative Drift" ;;
        "") echo "Unclassified" ;;
        *) echo "$1" ;;
    esac
}

BUG_CLASS="$(class_label "$CLASS")"

# ── Build entry components ────────────────────────────────────────────────────

AUTO_MARKER="Judgment"
[[ $AUTO -eq 1 ]] && AUTO_MARKER="🤖"

# Table row: | FM-NNN | Bug class | Concrete instance | Check that catches it | Auto? |
TABLE_DESC="${DESC:-${TITLE}}"
[[ -n "$ISSUE" ]] && TABLE_DESC="${TABLE_DESC} (GitHub #${ISSUE})"
TABLE_ROW="| ${FM_ID} | ${BUG_CLASS} | ${TABLE_DESC} | ${TITLE} | ${AUTO_MARKER} |"

# ── Backup before write ───────────────────────────────────────────────────────

cp "$CATALOG" "${CATALOG}.bak"

# ── Insert the canonical catalog row ───────────────────────────────────────────

python3 - "$CATALOG" "$TABLE_ROW" <<'PYEOF'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
table_row = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
table_row_pat = re.compile(r'^\| FM-\d+')

last_table_row = None
for i, line in enumerate(lines):
    if table_row_pat.match(line):
        last_table_row = i

if last_table_row is None:
    lines.append(table_row + '\n')
else:
    lines.insert(last_table_row + 1, table_row + '\n')

path.write_text(''.join(lines), encoding="utf-8")
PYEOF

python3 "$REPO_ROOT/scripts/failure_mode_catalog_guard.py" "$CATALOG" >/dev/null

# ── Report ────────────────────────────────────────────────────────────────────

echo "add-failure-mode: ${FM_ID} appended to ${CATALOG}"
echo "  class: ${BUG_CLASS}"
[[ -n "$ISSUE" ]]  && echo "  issue: #${ISSUE}"
echo "  table:  ${TABLE_ROW}"
