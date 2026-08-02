#!/usr/bin/env bash
# require-real-ci.sh — refuse to call a PR green unless required checks
# genuinely, completely, successfully ran.
#
# Background (FM-149 / FM-150): this repo had CI runs sitting in `queued` for
# eight hours because the runner scaleset didn't exist. The `guard` check
# reported an EMPTY conclusion, which GitHub renders BLANK, not red — so
# nothing flagged the problem and PRs merged on a gate that never executed.
#
# Contract: exit 0 ONLY if every required check name is present in the
# rollup AND every single entry bearing that name (there is often more than
# one — duplicate names are the NORMAL case in this repo, not an edge case)
# has status == COMPLETED AND a non-empty conclusion AND that conclusion is
# SUCCESS. Never deduplicate by name: one bad entry fails the whole check,
# regardless of how many good entries share its name or what order they
# appear in. A check with no conclusion is RED, never green. Zero checks
# reported is an ERROR, not a clean pass. A required check absent from the
# rollup entirely is an ERROR.
#
# Legacy commit statuses (the StatusContext shape used by some third-party
# bots) carry `context`/`state` instead of `name`/`status`/`conclusion`; those
# are evaluated on their own terms (state == SUCCESS), not permanently
# reported RED just because they lack a `conclusion` field.
#
# Usage:
#   require-real-ci.sh <pr-number> [--repo <owner/repo>] [--required <name[,name...]>]
#                       [--json-file <path>] [--max-wait-minutes <n>]
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
MAX_WAIT_MINUTES="15"

usage() {
  cat >&2 <<EOF
Usage: $PROG <pr-number> [--repo <owner/repo>] [--required <name[,name...]>] [--json-file <path>] [--max-wait-minutes <n>]
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
    --max-wait-minutes)
      [ $# -ge 2 ] || die_usage "--max-wait-minutes requires an argument"
      case "$2" in
        ''|*[!0-9]*) die_usage "--max-wait-minutes must be a non-negative integer, got: $2" ;;
      esac
      MAX_WAIT_MINUTES="$2"
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
# We pass the max-wait window and required-name list as argv (small, bounded),
# and the raw rollup JSON via stdin -- NOT argv. A rollup can exceed
# MAX_ARG_STRLEN (131072 bytes on Linux, independent of ARG_MAX and unrelated
# to any per-process argv/env budget): once RAW_JSON crossed that as a single
# argv string, execve() itself failed before python3 ever started, so the
# shell printed "Argument list too long" and python3 exited 126 -- a code
# this script's own contract does not document (0/1/2 only). Zero checks got
# evaluated and no PASS:/FAIL: line reached stdout at all: the gate silently
# did not run. stdin has no such size cap, so the payload goes there instead.
#
# This means the python *program text* can no longer come from stdin (the
# usual `python3 - <<'PYEOF' ... PYEOF` trick): stdin is now RAW_JSON's
# channel, and `python3 -` reading its own source from stdin would consume
# that payload as "source code" before the script ever calls
# sys.stdin.read(), leaving it empty. So the program text is captured into
# PY_SCRIPT (a plain heredoc-to-variable, no execution involved) and handed
# to python3 via -c instead; only RAW_JSON travels over the pipe.
#
# CI-17: never read a command's exit status through a pipe when the command
# whose status you want is NOT the last stage (`cmd | head; echo $?` reports
# head's status, not cmd's). Here python3 -- the command whose exit code we
# actually need -- IS the last stage of `printf ... | python3 ...`, so plain
# $?/pipefail already resolves to python3's own status; PIPESTATUS would in
# fact be wrong here, since PIPESTATUS from a pipeline run inside a `$(...)`
# subshell does not propagate to the parent shell that reads PY_RC.
PY_SCRIPT="$(cat <<'PYEOF'
import json
import sys
from datetime import datetime, timezone

raw_json = sys.stdin.read()
max_wait_minutes = int(sys.argv[1])
required = sys.argv[2:]

# No try/except here: bash already validated raw_json as parseable JSON
# (see the `json.load(sys.stdin)` pre-check above, run against this exact
# string before this invocation happens at all), so json.loads() can never
# raise here in practice. A try/except around it would be unreachable dead
# code that reads as coverage but is never exercised -- deleted rather than
# kept for a false sense of safety (M33). If json.loads ever DOES raise here
# despite that guarantee, the uncaught exception's nonzero, no-stdout exit
# is caught by the undocumented-exit-code check below, same as any other
# unexpected python3 failure.
doc = json.loads(raw_json)

# Accept either the full `gh pr view --json statusCheckRollup` envelope
# ({"statusCheckRollup": [...]}) or a bare list, for fixture convenience.
if isinstance(doc, dict):
    rollup = doc.get("statusCheckRollup")
elif isinstance(doc, list):
    rollup = doc
else:
    rollup = None

if not isinstance(rollup, list) or len(rollup) == 0:
    print("FAIL: no checks reported (statusCheckRollup missing, null, non-list, or empty)")
    sys.exit(2)


def entry_key(entry):
    """CheckRun entries use 'name'; legacy StatusContext entries use 'context'."""
    return entry.get("name") or entry.get("context")


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def elapsed_minutes(entry):
    started = parse_time(entry.get("startedAt") or entry.get("createdAt"))
    if started is None:
        return None
    try:
        # A timestamp with no timezone offset (e.g. "2026-08-01", or
        # "2026-08-01T22:12:07" with no trailing Z/+00:00) parses fine via
        # fromisoformat() but yields a tz-naive datetime. Subtracting that
        # from an aware datetime.now(timezone.utc) raises TypeError -- and
        # since this helper is only ever used to enrich a diagnostic
        # message, that must never escape and crash the whole evaluation
        # (which would relay bash exit 1, the code documented as a USAGE
        # error, silently downgrading a real gate failure). GitHub's own
        # timestamps are always UTC, so treat a naive value as UTC.
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - started).total_seconds() / 60.0
    except Exception:
        return None


def evaluate_entry(req, entry):
    """Return None if this single entry satisfies the contract, else a reason string."""
    if "status" in entry or "conclusion" in entry:
        # CheckRun shape.
        status = entry.get("status")
        conclusion = entry.get("conclusion")

        if status != "COMPLETED":
            mins = elapsed_minutes(entry)
            if mins is None:
                window_note = ""
            elif mins < max_wait_minutes:
                window_note = f" ({mins:.1f}m elapsed, within --max-wait-minutes={max_wait_minutes}: still starting up)"
            else:
                window_note = (
                    f" ({mins:.1f}m elapsed, exceeded --max-wait-minutes={max_wait_minutes}: "
                    f"likely stuck, matches the FM-149 pattern)"
                )
            return f"required check '{req}' is not complete (status={status!r}){window_note}"

        if conclusion is None or conclusion == "":
            return f"required check '{req}' is COMPLETED but has an empty/missing conclusion"

        if conclusion != "SUCCESS":
            return f"required check '{req}' concluded '{conclusion}', not SUCCESS"

        return None

    if "state" in entry:
        # Legacy StatusContext shape: context/state/targetUrl/createdAt, no
        # status/conclusion fields at all.
        state = entry.get("state")
        if state != "SUCCESS":
            return f"required check '{req}' (legacy status context) is not SUCCESS (state={state!r})"
        return None

    return f"required check '{req}' has an unrecognized entry shape: {entry!r}"


reasons = []
for req in required:
    matches = [e for e in rollup if isinstance(e, dict) and entry_key(e) == req]

    if not matches:
        reasons.append(f"required check '{req}' is absent from the rollup entirely")
        continue

    # Every entry bearing this name must independently satisfy the contract.
    # Never deduplicate by name / let one SUCCESS entry mask a bad sibling.
    bad = []
    for entry in matches:
        reason = evaluate_entry(req, entry)
        if reason is not None:
            bad.append(reason)

    if bad:
        if len(matches) > 1:
            reasons.append(
                f"{len(bad)} of {len(matches)} entries named '{req}' failed the contract: "
                + " | ".join(bad)
            )
        else:
            reasons.extend(bad)

if reasons:
    print("FAIL: " + "; ".join(reasons))
    sys.exit(2)

names = ", ".join(required)
print(f"PASS: all required checks ({names}) are COMPLETED/SUCCESS")
sys.exit(0)
PYEOF
)"

PY_OUT="$(printf '%s' "$RAW_JSON" | python3 -c "$PY_SCRIPT" "$MAX_WAIT_MINUTES" "${TRIMMED_REQUIRED[@]}")"
PY_RC=$?

# Documented contract is 0 (pass) / 2 (fail); anything else (e.g. a python3
# crash unrelated to the try/except above, an interpreter-level failure, or
# a future regression reopening the argv-limit failure this section exists
# to close) must not pass through as a silent, undocumented exit code -- it
# must become a loud, clearly-labeled failure instead.
if [ "$PY_RC" -ne 0 ] && [ "$PY_RC" -ne 2 ]; then
  echo "$PROG: python3 evaluator exited with undocumented code $PY_RC (expected 0 or 2)" >&2
  if [ -n "$PY_OUT" ]; then
    echo "$PY_OUT" >&2
  fi
  exit 2
fi

echo "$PY_OUT"
exit "$PY_RC"
