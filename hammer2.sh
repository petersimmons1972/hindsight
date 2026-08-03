#!/usr/bin/env bash
# Hammer the residual window in round 3: contained_target() re-check (line 255)
# -> mktemp (260) -> cp/mv (265).  A flipper spins swapping the leaf's parent
# directory for a symlink to an outside tree.  If the swap ever lands inside
# that window, mktemp+mv operate through the symlink and the catalog is written
# outside the consumer root.
set -u
WT="$1"; N="${2:-150}"
MARK='<!-- hindsight: vendored failure-mode catalog -->'
BASE="$(mktemp -d /tmp/hs-hammer.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor" "$BASE/outside"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
H="$BASE/consumer/docs/vendor/hindsight"
mkdir -p "$H"
echo "BASE=$BASE  HEAD=$(git -C "$WT" rev-parse --short HEAD)  iterations=$N"

STOP="$BASE/stop"
(
  while [ ! -e "$STOP" ]; do
    # $H is confined to this run's mktemp -d sandbox
    rm -rf -- "$H" 2>/dev/null
    ln -s "$BASE/outside" "$H" 2>/dev/null
    sleep 0.004
    rm -f -- "$H" 2>/dev/null
    mkdir -- "$H" 2>/dev/null
    sleep 0.004
  done
) &
FLIP=$!

esc=0; ok=0; fail=0
for i in $(seq 1 "$N"); do
  rm -f "$BASE/consumer/docs/vendor/hindsight/failure-modes.md" 2>/dev/null
  out="$(timeout 20 bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt" 2>&1)"
  rc=$?
  case "$rc" in 0) ok=$((ok+1)) ;; *) fail=$((fail+1)) ;; esac
  if [ -n "$(find "$BASE/outside" -mindepth 1 -print -quit 2>/dev/null)" ]; then
    esc=$((esc+1))
    echo "*** ESCAPE on iteration $i (rc=$rc) ***"
    echo "$out" | sed 's/^/    /'
    find "$BASE/outside" -printf '    %y %s %p\n'
  fi
done
touch "$STOP"; wait $FLIP 2>/dev/null
echo "iterations=$N exit0=$ok nonzero=$fail escapes=$esc"
echo "final outside tree:"; find "$BASE/outside" -mindepth 1 -printf '  %y %s %p\n' | sort
