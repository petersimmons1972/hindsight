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
OUT="$REPO/.dispatch-briefs"
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
packet_effort() { case "$1" in C1|C3) echo high ;; *) echo medium ;; esac; }

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
    --check "$chk" --check-timeout 900 --retries 1
  echo "  exit=$?"
done
