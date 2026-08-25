#!/usr/bin/env bash
# Regression test for hindsight#153: the guard.yml "Run bats tests" step must
# preserve captured diagnostic output when a bats case fails, not just report
# a nonzero exit code.
#
# This wrapper ties the result to the ACTUAL CI step's content (so a future
# revert of the flag is caught), then runs the behavioral pytest suite that
# drives a deliberately failing bats fixture and asserts the captured
# output/stderr survives.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

WORKFLOW=".github/workflows/guard.yml"
if [ ! -f "$WORKFLOW" ]; then
  echo "REGRESSION: $WORKFLOW is missing" >&2
  exit 1
fi

RUN_LINE=$(awk '
  /- name: Run bats tests/ { infound=1 }
  infound && /run:/ { print; exit }
' "$WORKFLOW")

if [[ "$RUN_LINE" != *"--print-output-on-failure"* ]]; then
  echo "REGRESSION: guard.yml '"'"'Run bats tests'"'"' step lost --print-output-on-failure; a bats failure's captured output would again be discarded and undiagnosable (hindsight#153)." >&2
  echo "  found run line: ${RUN_LINE}" >&2
  exit 1
fi

echo "guard.yml still carries --print-output-on-failure on the guard/tests bats step; running the behavioral output-capture regression suite..."
python3 -m pytest guard/tests/test_bats_output_capture.py -q
