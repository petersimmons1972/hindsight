#!/usr/bin/env bash
# Additional adversarial coverage for bin/similar-causes.py.  This file is
# intentionally separate from the stage-1 acceptance suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$ROOT/bin/similar-causes.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# A record without the required string instance must not be stringified and
# presented as a candidate merely because its other fields share query tokens.
printf '%s\n' \
  '{"id":"bad-1","instance":null,"source_path":"bad.jsonl","note":"queue race"}' \
  '{"id":"good-1","instance":"A queue race is caused by two workers claiming one job.","source_path":"good.jsonl"}' \
  >"$WORK/records.jsonl"

set +e
out="$(python3 "$TOOL" --corpus "$WORK" "queue race" 2>"$WORK/stderr")"
status=$?
set -e
if [[ "$status" -ne 0 ]]; then
  echo "FAIL: valid record alongside malformed record must remain a successful lookup: $(<"$WORK/stderr")" >&2
  exit 1
fi
if [[ "$out" == *"bad-1"* ]] || [[ "$out" != *"good-1"* ]]; then
  echo "FAIL: invalid instance record was emitted or valid record was lost: $out" >&2
  exit 1
fi
if [[ -s "$WORK/stderr" ]]; then
  echo "FAIL: malformed record must not leak a warning on a successful lookup" >&2
  exit 1
fi

echo "PASS: malformed instance records are ignored without contaminating candidates"
