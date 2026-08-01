#!/usr/bin/env bash
# require-real-ci.sh — refuse to call a PR green unless required checks
# genuinely, completely, successfully ran.
#
# Background (FM-149 / FM-150): this repo had CI runs sitting in `queued` for
# eight hours because the runner scaleset didn't exist. The `guard` check
# reported an EMPTY conclusion, which GitHub renders BLANK, not red — so
# nothing flagged the problem and PRs merged on a gate that never executed.
#
# Contract: exit 0 ONLY if every required check has status == COMPLETED AND a
# non-empty conclusion AND that conclusion is SUCCESS. A check with no
# conclusion is RED, never green. Zero checks reported is an ERROR, not a
# clean pass. A required check absent from the rollup entirely is an ERROR.
#
# Usage:
#   require-real-ci.sh <pr-number> [--repo <owner/repo>] [--required <name[,name...]>] [--json-file <path>]
#
# Exit codes:
#   0  all required checks are COMPLETED with conclusion SUCCESS
#   1  usage error
#   2  one or more required checks failed the contract (see stderr for which)

set -u
set -o pipefail

PROG="$(basename "$0")"

REPO="petersimmons1972/hindsight"
REQUIRED_CSV="guard"
JSON_FILE=""
PR=""

usage() {
  cat >&2 <<EOF
Usage: $PROG <pr-number> [--repo <owner/repo>] [--required <name[,name...]>] [--json-file <path>]
EOF
}

die_usage() {
  echo "$PROG: $*" >&2
  usage
  exit 1
}

# ---- argument parsing --------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --repo)
      [ $# -ge 2 ] || die_usage "--repo requires an argument"
      REPO="$2"
      shift 2
      ;;
    --required)
      [ $# -ge 2 ] || die_usage "--required requires an argument"
      REQUIRED_CSV="$2"
      shift 2
      ;;
    --json-file)
      [ $# -ge 2 ] || die_usage "--json-file requires an argument"
      JSON_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      die_usage "unknown option: $1"
      ;;
    *)
      if [ -n "$PR" ]; then
        die_usage "unexpected extra argument: $1"
      fi
      PR="$1"
      shift
      ;;
  esac
done

[ -n "$PR" ] || die_usage "missing required <pr-number> argument"

# ---- fetch the rollup ---------------------------------------------------
RAW_JSON=""
if [ -n "$JSON_FILE" ]; then
  [ -f "$JSON_FILE" ] || die_usage "--json-file not found: $JSON_FILE"
  RAW_JSON="$(cat "$JSON_FILE")"
else
  if ! command -v gh >/dev/null 2>&1; then
    echo "$PROG: gh CLI not found and no --json-file supplied" >&2
    exit 1
  fi
  RAW_JSON="$(gh pr view "$PR" --repo "$REPO" --json statusCheckRollup 2>&1)"
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "$PROG: gh pr view failed (exit $RC):" >&2
    echo "$RAW_JSON" >&2
    exit 1
  fi
fi

[ -n "$RAW_JSON" ] || die_usage "no JSON produced (empty --json-file or empty gh response)"

# Validate it's actually JSON at all before handing to python3.
if ! printf '%s' "$RAW_JSON" | python3 -c 'import sys,json; json.load(sys.stdin)' >/dev/null 2>&1; then
  echo "$PROG: input is not valid JSON" >&2
  exit 1
fi

# ---- build the required-check allowlist ---------------------------------
IFS=',' read -r -a REQUIRED_ARR <<< "$REQUIRED_CSV"
if [ "${#REQUIRED_ARR[@]}" -eq 0 ]; then
  die_usage "--required produced an empty allowlist"
fi

# Trim whitespace around each required name.
TRIMMED_REQUIRED=()
for name in "${REQUIRED_ARR[@]}"; do
  trimmed="$(printf '%s' "$name" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [ -n "$trimmed" ] || die_usage "--required contains an empty check name"
  TRIMMED_REQUIRED+=("$trimmed")
done

# ---- evaluate via python3 (robust JSON handling, no jq quoting gymnastics) ----
# We pass the raw rollup JSON and the required-name list to python3, which
# does the actual contract check and prints PASS/FAIL plus reasons. Bash just
# relays python3's verdict and exit code.
PY_OUT="$(python3 - "$RAW_JSON" "${TRIMMED_REQUIRED[@]}" <<'PYEOF'
import json
import sys

raw_json = sys.argv[1]
required = sys.argv[2:]

try:
    doc = json.loads(raw_json)
except Exception as exc:
    print(f"FAIL: could not parse rollup JSON: {exc}")
    sys.exit(2)

# Accept either the full `gh pr view --json statusCheckRollup` envelope
# ({"statusCheckRollup": [...]}) or a bare list, for fixture convenience.
if isinstance(doc, dict):
    rollup = doc.get("statusCheckRollup")
elif isinstance(doc, list):
    rollup = doc
else:
    rollup = None

if rollup is None:
    print("FAIL: no checks reported (statusCheckRollup missing from response)")
    sys.exit(2)

if not isinstance(rollup, list) or len(rollup) == 0:
    print("FAIL: no checks reported (empty statusCheckRollup)")
    sys.exit(2)

# Index rollup entries by name (checks use "name", legacy status contexts use "context").
by_name = {}
for entry in rollup:
    if not isinstance(entry, dict):
        continue
    key = entry.get("name") or entry.get("context")
    if key:
        by_name[key] = entry

reasons = []
for req in required:
    entry = by_name.get(req)
    if entry is None:
        reasons.append(f"required check '{req}' is absent from the rollup entirely")
        continue

    status = entry.get("status")
    conclusion = entry.get("conclusion")

    if status != "COMPLETED":
        reasons.append(f"required check '{req}' is not complete (status={status!r})")
        continue

    if conclusion is None or conclusion == "":
        reasons.append(f"required check '{req}' is COMPLETED but has an empty/missing conclusion")
        continue

    if conclusion != "SUCCESS":
        reasons.append(f"required check '{req}' concluded '{conclusion}', not SUCCESS")
        continue

if reasons:
    print("FAIL: " + "; ".join(reasons))
    sys.exit(2)

names = ", ".join(required)
print(f"PASS: all required checks ({names}) are COMPLETED/SUCCESS")
sys.exit(0)
PYEOF
)"
PY_RC=$?

echo "$PY_OUT"
exit $PY_RC
