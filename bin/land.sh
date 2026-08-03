#!/usr/bin/env bash
# land.sh — the only sanctioned way to merge a PR in this repo.
#
# bin/require-real-ci.sh has existed since Phase 0 and gated NOTHING: it was
# exercised only by its own bats suite. PLAN-TDD R7 says landing runs it, never
# a human reading of `gh pr view`. A rule that lives in a plan document is a
# sentence; this script is the mechanism (Law 1).
#
# Usage:
#   bin/land.sh <pr-number> [--repo owner/repo] [--json-file path] [--merge]
#
#   --merge       actually merge. WITHOUT it this is a DRY RUN that reports the
#                 gate verdict and merges nothing. Dry-run is the default
#                 because the destructive direction should need a word typed on
#                 purpose, not an omission.
#   --json-file   read the check rollup from a file instead of the network
#                 (testing; passed straight through to require-real-ci.sh).
#
# Exit: 0 gate passed (merged, or would merge under --merge)
#       non-zero gate refused, or the merge itself failed. Never merges on a
#       non-zero gate, whatever the argument order.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$HERE/require-real-ci.sh"
DISCRIMINATING_GATE="$HERE/verify-discriminating.sh"
PROG="$(basename "$0")"

# Save the invocation BEFORE the parse loop consumes it. The banner below used
# to print "$*" after the shifts had already emptied it, so the line claiming to
# record how the gate was invoked recorded nothing.
INVOCATION=("$@")

PR=""; REPO=""; JSON_FILE=""; DO_MERGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --merge)     DO_MERGE=1; shift ;;
    --repo)      REPO="${2:-}"; shift 2 ;;
    --json-file) JSON_FILE="${2:-}"; shift 2 ;;
    -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
    -*)          echo "$PROG: unknown option: $1" >&2; exit 2 ;;
    *)           [ -z "$PR" ] && PR="$1" || { echo "$PROG: unexpected argument: $1" >&2; exit 2; }
                 shift ;;
  esac
done

if [ -z "$PR" ]; then
  echo "$PROG: usage: $PROG <pr-number> [--repo owner/repo] [--json-file path] [--merge]" >&2
  exit 2
fi

# The dispatcher supplies the checked-out PR base when this landing gate is
# used for a branch.  No value means the historical CI-only gate remains
# usable on an already-landed checkout, where there are deliberately no new
# tests to evaluate.
if [ -n "${VERIFY_DISCRIMINATING_BASE:-}" ]; then
  bash "$DISCRIMINATING_GATE" --base "$VERIFY_DISCRIMINATING_BASE" || exit $?
fi

gate_args=("$PR")
[ -n "$REPO" ]      && gate_args+=(--repo "$REPO")
[ -n "$JSON_FILE" ] && gate_args+=(--json-file "$JSON_FILE")

echo "=== gate: require-real-ci.sh ${INVOCATION[*]} ==="
gate_log="$(mktemp)"
trap 'rm -f "$gate_log"' EXIT

# CI-17: status read directly from the command, never through a pipe.
bash "$GATE" "${gate_args[@]}" >"$gate_log" 2>&1
gate_status=$?
cat "$gate_log"
echo "=== gate exit: $gate_status ==="

if [ "$gate_status" -ne 0 ]; then
  echo ""
  echo "REFUSING to merge PR #$PR: required checks did not genuinely, completely succeed."
  echo "A check with no conclusion is RED, never green (FM-149/FM-150). Fix CI, do not"
  echo "override this — the eight-hour queued-CI incident is what this refusal is made of."
  exit "$gate_status"
fi

# Law 3: the undo is printed BEFORE the action, not after.
cat <<UNDO

=== UNDO (printed before the merge, per Law 3) ===
  A squash merge lands one commit on main. To reverse it:
    git revert -m 1 <merge-sha>      # if it landed as a merge commit
    git revert <squash-sha>          # if it landed as a squash (the default here)
  and to restore the PR for further work:
    gh pr reopen $PR ${REPO:+--repo $REPO}
  The branch is deleted on merge; recover it with:
    git push origin <squash-sha>:refs/heads/<branch-name>
=== END UNDO ===
UNDO

if [ "$DO_MERGE" -ne 1 ]; then
  echo "GATE PASSED for PR #$PR — DRY RUN, nothing was merged."
  echo "Re-run with --merge to land it."
  exit 0
fi

echo "GATE PASSED for PR #$PR — Merging."
gh pr merge "$PR" ${REPO:+--repo "$REPO"} --squash --delete-branch
merge_status=$?
[ "$merge_status" -eq 0 ] || { echo "$PROG: merge failed (exit $merge_status)" >&2; exit "$merge_status"; }
echo "merged PR #$PR"
exit 0
