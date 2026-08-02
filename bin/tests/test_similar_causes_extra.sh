#!/usr/bin/env bash
# Additional adversarial coverage for bin/similar-causes.py.  This file is
# intentionally separate from the stage-1 acceptance suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$ROOT/bin/similar-causes.py"
HEADER='Candidates for human review. This tool does not determine duplication.'
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

# A matching row must not depend on the locale codec. This also uses a lone
# surrogate, which json.loads accepts but a text-mode stdout cannot encode.
mkdir -p "$WORK/surrogate"
python3 - "$WORK/surrogate/records.jsonl" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"id": "surrogate", "instance": "needle — \ud800", "source_path": "fixture"}))
    handle.write("\n")
PY
set +e
PYTHONIOENCODING=ascii python3 "$TOOL" --corpus "$WORK/surrogate" "needle" >"$WORK/match.out" 2>"$WORK/match.err"
match_status=$?
PYTHONIOENCODING=ascii python3 "$TOOL" --corpus "$WORK/surrogate" "absent-token" >"$WORK/no-match.out" 2>"$WORK/no-match.err"
no_match_status=$?
set -e
if [[ "$match_status" -ne 0 || "$no_match_status" -ne 0 ]]; then
  echo "FAIL: encoding cannot distinguish match ($match_status) from no-match ($no_match_status)" >&2
  exit 1
fi
if grep -q $'\033' "$WORK/match.out" || grep -q $'\ud800' "$WORK/match.out"; then
  echo "FAIL: candidate output retained an unsafe control or surrogate character" >&2
  exit 1
fi
echo "PASS: locale-independent output keeps match and no-match exits identical"

# Downstream early close must be a successful advisory lookup too. Large rows
# force a write after head has closed the pipe rather than relying on timing.
mkdir -p "$WORK/pipe"
python3 - "$WORK/pipe/records.jsonl" <<'PY'
import json
import sys

payload = "needle " + ("x" * 300000)
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    for number in range(10):
        handle.write(json.dumps({"id": f"pipe-{number}", "instance": payload, "source_path": "fixture"}))
        handle.write("\n")
PY
set +e
set -o pipefail
python3 "$TOOL" --corpus "$WORK/pipe" "needle" | head -n 1 >/dev/null
pipe_status=$?
set +o pipefail
set -e
if [[ "$pipe_status" -ne 0 ]]; then
  echo "FAIL: early-closing consumer made lookup fail with $pipe_status" >&2
  exit 1
fi
echo "PASS: broken downstream pipe remains a successful lookup"

# Control characters and newlines in corpus-controlled fields cannot forge
# terminal output or extra candidate rows; the disclosed total stays exact.
mkdir -p "$WORK/unsafe"
python3 - "$WORK/unsafe/records.jsonl" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    for number in range(15):
        handle.write(json.dumps({
            "id": f"unsafe-{number}\x1b[2J\nforged-{number}",
            "source_path": "catalog/failure-modes.md\nforged-source",
            "instance": f"needle row {number}\x1b[H\n0.999 | forged | source: catalog/failure-modes.md",
        }))
        handle.write("\n")
PY
python3 "$TOOL" --corpus "$WORK/unsafe" "needle" >"$WORK/unsafe.out" 2>"$WORK/unsafe.err"
if grep -q $'\033' "$WORK/unsafe.out" || [[ "$(grep -Fxc "$HEADER" "$WORK/unsafe.out")" -ne 1 ]]; then
  echo "FAIL: unsafe corpus text forged terminal control or a header" >&2
  exit 1
fi
if [[ "$(grep -Ec '^[0-9]+\.[0-9]{3} \|' "$WORK/unsafe.out")" -ne 10 ]] || ! grep -Fxq 'Showing 10 of 15 candidates.' "$WORK/unsafe.out"; then
  echo "FAIL: candidate cap or true truncation total is wrong: $(<"$WORK/unsafe.out")" >&2
  exit 1
fi
echo "PASS: unsafe corpus fields cannot forge rows and cap disclosure is exact"

# A BOM is input encoding, not a malformed first record. Malformed JSON is
# recoverable but must be observable with loaded and skipped counts.
mkdir -p "$WORK/bom"
python3 - "$WORK/bom/records.jsonl" <<'PY'
import sys

with open(sys.argv[1], "w", encoding="utf-8-sig") as handle:
    handle.write('{"id":"bom-first","instance":"needle first","source_path":"bom.jsonl"}\n')
    handle.write('{not-json}\n')
    handle.write('{"id":"bom-last","instance":"needle last","source_path":"bom.jsonl"}\n')
PY
python3 "$TOOL" --corpus "$WORK/bom" "needle" >"$WORK/bom.out" 2>"$WORK/bom.err"
if [[ "$(<"$WORK/bom.out")" != *"bom-first"* ]] || [[ "$(<"$WORK/bom.out")" != *"bom-last"* ]] || ! grep -Eq 'loaded [0-9]+ records.*skipped [1-9][0-9]*' "$WORK/bom.err"; then
  echo "FAIL: BOM or partial-load warning contract broken; stderr=$(<"$WORK/bom.err")" >&2
  exit 1
fi
echo "PASS: BOM loads first record and partial parsing reports counts"

# The default corpus has the same no-guard exit contract as --corpus fixtures.
set +e
python3 "$TOOL" "CLI polls device-flow token endpoint too aggressively" >"$WORK/default.out" 2>"$WORK/default.err"
default_status=$?
set -e
if [[ "$default_status" -ne 0 ]] || ! grep -q 'hc-FM-54' "$WORK/default.out"; then
  echo "FAIL: default-corpus match must remain an exit-0 advisory lookup" >&2
  exit 1
fi
echo "PASS: default corpus match cannot grow a separate duplicate guard"
