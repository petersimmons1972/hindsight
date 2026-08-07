#!/usr/bin/env bash
# Contract tests for the plan-06 amendment re-cut (issue #71).
#
# Founder rulings 2026-08-04:
#   - ceiling 5 → 6 is the agreed target; stated consistently
#   - §7 may contain directory entries (advisory count)
#   - §11 undo is a static, explicitly listed sequence — never parses the plan
#   - git branch -d (not -D)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# ── 1. The four ceiling statements agree on 6 (not a mix of 5 and 6) ──────────
for f in \
  "$ROOT/bin/check-plan-preamble.sh" \
  "$ROOT/plans/00-INDEX.md" \
  "$ROOT/PLAN.md" \
  "$ROOT/plans/AUTOMATION-QUEUE.md"
do
  [[ -f "$f" ]] || fail "missing $f"
done

rg -q 'MAX_FILES="\$\{MAX_FILES:-6\}"' "$ROOT/bin/check-plan-preamble.sh" \
  || fail "check-plan-preamble MAX_FILES default is not 6"
rg -q '≤6' "$ROOT/plans/00-INDEX.md" || fail "00-INDEX ceiling is not ≤6"
rg -q '≤6' "$ROOT/PLAN.md" || fail "PLAN.md ceiling is not ≤6"
rg -q '≤6' "$ROOT/plans/AUTOMATION-QUEUE.md" || fail "AUTOMATION-QUEUE ceiling is not ≤6"
# No leftover hard "≤5 files" ceiling claims in those four files.
if rg -n '≤5 files' "$ROOT/plans/00-INDEX.md" "$ROOT/PLAN.md" "$ROOT/plans/AUTOMATION-QUEUE.md"; then
  fail "stale ≤5 files ceiling claim remains"
fi

# ── 2. Plan 06 §7 includes the work directory entry ──────────────────────────
sec7=$(awk '/^## 7\./{f=1;next} /^## 8\./{f=0} f' "$ROOT/plans/06-l3-invariant-ledger.md")
printf '%s\n' "$sec7" | rg -q 'pipeline/L3/work/' \
  || fail "plan 06 §7 must name pipeline/L3/work/"
n_paths=$(printf '%s\n' "$sec7" | rg -c '^/home/psimmons/' || true)
[[ "$n_paths" -eq 6 ]] || fail "plan 06 §7 should name 6 paths, got $n_paths"

# ── 3. §11 undo is static: no awk/grep of the plan, no branch -D, no rm -rf ──
sec11=$(awk '/^## 11\./{f=1;next} /^## 12\./{f=0} f' "$ROOT/plans/06-l3-invariant-ledger.md")
# Only the fenced bash block is executable undo; prose may mention forbidden forms.
undo_code=$(printf '%s\n' "$sec11" | awk '/^```bash/{f=1;next} /^```/{f=0} f')
[[ -n "$undo_code" ]] || fail "§11 missing bash undo block"
printf '%s\n' "$undo_code" | rg -q 'git branch -d' || fail "§11 must use git branch -d"
if printf '%s\n' "$undo_code" | rg -q 'git branch -D'; then
  fail "§11 must not use git branch -D"
fi
if printf '%s\n' "$undo_code" | rg -q 'rm -rf'; then
  fail "§11 must not rm -rf (static narrow deletes only)"
fi
# Reject the document-parsing undo that PR #70 introduced.
if printf '%s\n' "$undo_code" | rg -q 'awk |mapfile |SEC7'; then
  fail "§11 must not parse §7 at runtime"
fi
# Explicit path list present in the code block.
printf '%s\n' "$undo_code" | rg -q 'pipeline/validate_l3.py' || fail "§11 missing validate_l3.py"
printf '%s\n' "$undo_code" | rg -q 'docs/L3.md' || fail "§11 missing docs/L3.md"

# ── 4. Preamble lint still runs; plan 06 is not a new structural fail ────────
out=$(bash "$ROOT/bin/check-plan-preamble.sh" 2>&1 || true)
printf '%s\n' "$out" | rg -q '06-l3-invariant-ledger.md §7 names 6 path' \
  || fail "preamble should accept plan 06's 6 §7 paths; out=$(printf '%s' "$out" | rg '06-l3' || true)"

printf 'PASS: plan-06 amendment re-cut (issue #71)\n'
