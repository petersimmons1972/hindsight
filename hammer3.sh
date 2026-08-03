#!/usr/bin/env bash
# Precise: detect the FIRST iteration in which anything appears outside the
# consumer root, and record that run's exit status and output verbatim.
set -u
WT="$1"; N="${2:-250}"
BASE="$(mktemp -d /tmp/hs-h3.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor" "$BASE/outside"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
H="$BASE/consumer/docs/vendor/hindsight"; mkdir -p "$H"
echo "BASE=$BASE  HEAD=$(git -C "$WT" rev-parse --short HEAD 2>/dev/null)  iterations=$N"
STOP="$BASE/stop"
( while [ ! -e "$STOP" ]; do
    rm -rf -- "$H" 2>/dev/null; ln -s "$BASE/outside" "$H" 2>/dev/null; sleep 0.004
    rm -f  -- "$H" 2>/dev/null; mkdir  -- "$H" 2>/dev/null;             sleep 0.004
  done ) &
FLIP=$!
for i in $(seq 1 "$N"); do
  out="$(timeout 20 bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt" 2>&1)"
  rc=$?
  n="$(find "$BASE/outside" -mindepth 1 | wc -l)"
  if [ "$n" -gt 0 ]; then
    echo "=== FIRST ESCAPE at iteration $i ==="
    echo "tool exit status: $rc"
    echo "tool output:"; printf '%s\n' "$out" | sed 's/^/  | /'
    touch "$STOP"
    echo "state of the path the tool PRINTED as updated:"
    ls -l "$BASE/consumer/docs/vendor/hindsight/failure-modes.md" 2>&1 | sed 's/^/  /'
    echo "    (size inside repo: $(stat -c %s "$BASE/consumer/docs/vendor/hindsight/failure-modes.md" 2>/dev/null || echo NONE))"
    echo "what appeared outside the consumer root:"
    find "$BASE/outside" -mindepth 1 -printf '  %y %s %p\n'
    break
  fi
done
touch "$STOP"; wait $FLIP 2>/dev/null
echo "--- verification ---"
for f in "$BASE"/outside/*; do
  [ -e "$f" ] || continue
  echo "  $f"; echo "    size=$(stat -c %s "$f")"
  echo "    sha256=$(sha256sum "$f" | awk '{print $1}')"
  echo "    first line: $(head -1 "$f")"
done
echo "  expected content = ownership marker + catalog:"
{ printf '%s\n' '<!-- hindsight: vendored failure-mode catalog -->'; cat "$WT/catalog/failure-modes.md"; } > "$BASE/expected"
echo "    size=$(stat -c %s "$BASE/expected") sha256=$(sha256sum "$BASE/expected" | awk '{print $1}')"
for f in "$BASE"/outside/*; do
  [ -f "$f" ] || continue
  cmp -s "$BASE/expected" "$f" && echo "    cmp: $f is BYTE-IDENTICAL to the synced catalog" \
                              || echo "    cmp: $f differs from the synced catalog"
done
