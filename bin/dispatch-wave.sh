#!/usr/bin/env bash
# Build a packet brief (shared context + packet) and dispatch it to Codex.
# Usage: bin/dispatch-wave.sh C1 [C4 C5 ...]      # starts each concurrently
set -uo pipefail

REPO="$HOME/projects/hindsight"
B="$REPO/briefs"

# The ambient GH_TOKEN goes stale in long-lived sessions (App installation tokens
# expire hourly) and returns "Bad credentials". Refresh here rather than trusting
# the exported value -- verify auth by exercising it, not by reading it.
if command -v gh-app-token >/dev/null; then
  GH_TOKEN="$(gh-app-token claude | tr -d '[:space:]')" && export GH_TOKEN
fi
# Brief staging lives OUTSIDE the repo. Writing it into the shared checkout made
# concurrent dispatches mutate the tree their siblings were being judged against.
# Building a dispatch harness that violates the shared-mutable-checkout invariant
# is the failure this corpus records seven times (OPS-8/13/36/38/41/45/48).
OUT="${XDG_CACHE_HOME:-$HOME/.cache}/hindsight-dispatch-briefs"
mkdir -p "$OUT"

packet_check() {
  case "$1" in
    C1) echo 'python3 -m pytest pipeline/tests/test_cluster.py -q' ;;
    C2) echo 'python3 -m pytest pipeline/tests/test_recurrence_report.py -q' ;;
    C3) echo 'python3 -m pytest guard/tests/ -q && bats guard/tests/*.bats' ;;
    C4) echo 'python3 -m pytest guard/tests/test_verify_enforcement.py -q' ;;
    C5) echo 'python3 pipeline/validate_l1.py && python3 -m pytest pipeline/tests/test_validate_l1.py -q' ;;
    C6) echo 'bash bin/tests/test_sync.sh' ;;
    C7) echo 'actionlint .github/workflows/*.yml && python3 guard/failure_mode_catalog_guard.py' ;;
    *)  return 1 ;;
  esac
}
# Audition slot: exempted for this batch, deliberately and on the record.
# Filling the slot properly means enrolling a thin-history harness, and an
# unresolved audition blocks EVERY dispatch in the repo (commands.md). The
# obvious candidate, grok, carries a documented indefinite-hang failure mode
# when it races on a shared auth.json (catalog FM-125) -- so auditioning here
# would put all 7 packets behind a pairing that can wedge the repo. A real
# audition should be scheduled once this batch has landed and a baseline exists.
EXEMPT="first dispatch batch in a new repo; auditioning an unproven harness would block all 7 packets, and the thin-history candidate has a documented indefinite-hang mode (FM-125). Audition scheduled separately post-baseline."

packet_effort() { case "$1" in C1|C3) echo high ;; *) echo medium ;; esac; }

# SERIALIZE. cli-dispatch's checkout_state_snapshot prunes .dispatch/worktrees but
# NOT .dispatch/covariates or .dispatch/probes, so concurrent dispatches in one repo
# cross-trip each other's leak detectors nondeterministically (observed 2026-08-01:
# C4 and C5 flagged leak=true with their work intact and uncommitted, while C6 and
# C7 passed). Until that is fixed upstream, run one dispatch at a time.
for p in "$@"; do
  src=$(ls "$B/$p"-*.md 2>/dev/null | head -1)
  if [ -z "$src" ]; then echo "no brief for $p" >&2; continue; fi
  slug=$(basename "$src" .md)
  cat "$B/_shared-context.md" "$src" > "$OUT/$slug.md"
  chk=$(packet_check "$p") || { echo "no check for $p" >&2; continue; }
  echo "=== dispatching $slug (effort $(packet_effort "$p")) ==="
  cli-dispatch start --repo "$REPO" --task "$slug" \
    --harness codex --effort "$(packet_effort "$p")" \
    --brief-file "$OUT/$slug.md" \
    --check "$chk" --check-strength behavioral --negative-cases yes \
    --audition-exempt "$EXEMPT" \
    --check-timeout 900 --retries 1
  echo "  exit=$?"
done
