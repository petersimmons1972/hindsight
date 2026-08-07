#!/usr/bin/env bash
# Contract: check-plan-index-truth is load-bearing in pre-commit and land.sh (#92).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

pre="$ROOT/.githooks/pre-commit"
land="$ROOT/bin/land.sh"
checker="$ROOT/bin/check-plan-index-truth.sh"

[[ -x "$checker" ]] || fail "checker missing or not executable"
[[ -f "$pre" ]] || fail "pre-commit missing"
[[ -f "$land" ]] || fail "land.sh missing"

# Ship path must name the real binary path (not a fixture path).
rg -q 'check-plan-index-truth\.sh' "$pre" || fail "pre-commit does not invoke the checker"
rg -q 'check-plan-index-truth\.sh' "$land" || fail "land.sh does not invoke the checker"
rg -q '\$REPO_ROOT/bin/check-plan-index-truth\.sh|\$HERE/check-plan-index-truth\.sh' "$pre" "$land" \
  || fail "hooks must call the shipped binary by REPO_ROOT/HERE path"

# Digest of the path string in land matches basename of shipped checker.
rg -q 'bash "\$HERE/check-plan-index-truth.sh"' "$land" \
  || fail "land.sh must bash \$HERE/check-plan-index-truth.sh"

# Pre-commit path-gates on index inputs (catalog-only stays cheap).
rg -q 'plans/00-INDEX.md' "$pre" || fail "pre-commit must path-gate on 00-INDEX.md"
rg -q 'plan-index-expected-ids.conf' "$pre" || fail "pre-commit must path-gate on expected-ids conf"

# Structural: land refuses merge when plan-index fails — the refuse message exists.
rg -q 'plan-index truth check failed' "$land" || fail "land.sh missing refuse message for plan-index"

printf 'PASS: plan-index is load-bearing in pre-commit and land.sh (#92)\n'
