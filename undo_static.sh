#!/usr/bin/env bash
# Static --undo escape: ancestor symlink + leaf symlink.
#   apply  -> journal records the UNRESOLVED target (symlink branch leaves
#             resolved_target empty), then the write loop refuses (exit 1)
#   undo   -> restore_backup_atomically() mkdir -p's and renames onto that
#             UNRESOLVED path, with no containment check, so it walks the
#             ancestor symlink and lands outside the consumer root.
# Nothing is changed on disk between the two invocations.
set -u
WT="$1"
BASE="$(mktemp -d /tmp/hs-us.XXXXXX)"
mkdir -p "$BASE/consumer/docs" "$BASE/outside/hindsight"
printf 'OUTSIDE-SECRET-DO-NOT-TOUCH\n' > "$BASE/outside/canary.md"
ln -s "$BASE/outside" "$BASE/consumer/docs/vendor"          # ancestor symlink
ln -s "$BASE/outside/canary.md" "$BASE/outside/hindsight/failure-modes.md"   # leaf symlink
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
echo "HEAD=$(git -C "$WT" rev-parse --short HEAD)  BASE=$BASE"
echo "--- layout before ---"; find "$BASE" -mindepth 1 -printf '%y %p -> %l\n' | sort
echo
echo "--- STEP 1: --apply (expected to refuse) ---"
bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt"
echo "APPLY EXIT=$?"
J=$(ls -d /tmp/hindsight-sync-undo.*/journal.tsv -t 2>/dev/null | head -1)
echo "--- journal ---"; cat "$J"
echo
echo "--- outside tree between the two calls (nothing touched by me) ---"
find "$BASE/outside" -mindepth 1 -printf '%y %s %p -> %l\n' | sort
echo
echo "--- STEP 2: --undo (same filesystem state) ---"
bash "$WT/bin/sync-failure-modes.sh" --undo "$J"
echo "UNDO EXIT=$?"
echo "--- outside tree after undo ---"
find "$BASE/outside" -mindepth 1 -printf '%y %s %p -> %l\n' | sort
echo "--- consumer tree after undo (real files only, not through the symlink) ---"
find "$BASE/consumer" -mindepth 1 -printf '%y %s %p -> %l\n' | sort
