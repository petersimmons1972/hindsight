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

# ---------------------------------------------------------------------------
# CONTENT CHECK -- the defect cli-dispatch's stub probe found in this script.
#
# The four conditions above are all satisfied by a ONE-BYTE GARBAGE FILE: bash
# runs it, the shell prints "x: command not found" to stderr (non-empty output)
# and exits 127 (non-zero). So the check passed against a file containing no
# tests at all, and cli-dispatch correctly refused to mint a verified PASS,
# reporting content_blind=true.
#
# This script had been verified in four directions before use -- absent, green,
# red-with-output, red-and-silent -- and every one of those inputs was authored
# by the same hand that wrote the check. That is FM-153 exactly: an instrument
# validated only against inputs its author imagined. The stub is the input class
# the author does not think of, which is why the probe belongs in the tool and
# not in the author's imagination.
#
# So require STRUCTURE: the suite must report a countable set of test outcomes.
# Accepted shapes (an adversary may use either):
#   TAP-ish : lines beginning "not ok" / "ok"
#   summary : a line matching "<n> passed, <m> failed"
# and there must be at least MIN_TESTS of them, of which at least one failed.
# A stub cannot fake this; a real suite gets it for free.
MIN_TESTS=5

tap_fail=$(grep -cE '^\s*not ok' "$log" || true)
tap_ok=$(grep -cE '^\s*ok ' "$log" || true)
line_fail=$(grep -cE '^\s*(FAIL|✗|not ok)\b' "$log" || true)

# "N passed, M failed" in any casing/spacing
read -r sum_pass sum_fail < <(
  grep -oiE '[0-9]+ +passed, *[0-9]+ +failed' "$log" \
    | tail -1 | grep -oE '[0-9]+' | tr '\n' ' '
)
sum_pass=${sum_pass:-0}; sum_fail=${sum_fail:-0}

total=$(( tap_fail + tap_ok ))
(( total == 0 )) && total=$(( sum_pass + sum_fail ))
(( total == 0 )) && total=$line_fail

failed=$(( tap_fail > 0 ? tap_fail : 0 ))
(( failed == 0 )) && failed=$sum_fail
(( failed == 0 )) && failed=$line_fail

if (( total < MIN_TESTS )); then
  echo "FAIL: suite exited $status but reported only $total test outcome(s)." >&2
  echo "      A red exit with no countable tests is a stub, not an attack spec." >&2
  echo "      Emit TAP ('not ok N - name') or a '<n> passed, <m> failed' summary," >&2
  echo "      with at least $MIN_TESTS tests." >&2
  exit 1
fi

if (( failed == 0 )); then
  echo "FAIL: suite exited $status, reported $total tests, but none of them FAILED." >&2
  echo "      The non-zero exit came from something other than a failing test." >&2
  exit 1
fi

echo "PASS: attack spec is red (exit $status) against a tree with no implementation."
echo "      $failed of $total reported tests failed."
exit 0
