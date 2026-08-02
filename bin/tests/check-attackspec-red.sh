#!/usr/bin/env bash
# Acceptance check for a STAGE 1 (attack spec) dispatch.
#
# Stage 1's contract is inverted: the deliverable is a suite that FAILS, because
# the implementation it grades does not exist yet. A suite that passes here is a
# description of an implementation, not an attack on one.
#
# Three outcomes are distinguished on purpose, because collapsing them is the
# exact failure this repository catalogues:
#
#   suite absent        -> FAIL. Nothing was delivered. Not the same as "red".
#   suite exits 0       -> FAIL. It is green against a non-existent tool.
#   suite exits non-0   -> PASS. The red is proven.
#
# CI-17: exit status is never read through a pipe. Output is captured to a file
# and the status read directly from the command.
set -uo pipefail

SUITE="${1:?usage: check-attackspec-red.sh <path-to-suite>}"

if [[ ! -f "$SUITE" ]]; then
  echo "FAIL: attack spec not delivered — $SUITE does not exist." >&2
  echo "      An absent suite is not a red suite." >&2
  exit 1
fi

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

bash "$SUITE" >"$log" 2>&1
status=$?

echo "--- suite output (exit $status) ---"
tail -40 "$log"
echo "--- end suite output ---"

if [[ $status -eq 0 ]]; then
  echo "FAIL: the attack spec PASSES against a tree with no implementation." >&2
  echo "      Either the tests assert nothing, or an implementation was written." >&2
  exit 1
fi

# A suite that produced no output at all exited non-zero for some reason other
# than running tests (syntax error, missing interpreter). That is not a proven
# red either -- it is a broken file that happens to have the right exit code.
if [[ ! -s "$log" ]]; then
  echo "FAIL: suite exited $status but produced no output." >&2
  echo "      Cannot distinguish 'tests failed' from 'file is broken'." >&2
  exit 1
fi

echo "PASS: attack spec is red (exit $status) against a tree with no implementation."
exit 0
