#!/usr/bin/env bash
# Deterministic TOCTOU harness, v2.
#
# Target is a FIFO.  The tool's ownership check `grep -Fqx MARKER <target>`
# blocks in read(2) with the FIFO open.  We detect that state precisely by
# polling /proc for a *grep* process holding the target, then swap the path
# out from under it, then release grep by feeding it the marker on a fd we
# grabbed while the FIFO was still the FIFO.
#
# $1 = worktree, $2 = swap mode
set -u
WT="$1"; SWAP="$2"
MARK='<!-- hindsight: vendored failure-mode catalog -->'
BASE="$(mktemp -d /tmp/hs-race2.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor/hindsight" "$BASE/outside"
( cd "$BASE/consumer" && git init -q . )
printf 'OUTSIDE-SECRET-DO-NOT-TOUCH\n' > "$BASE/outside/canary.md"
# outside decoys that DO carry the ownership marker, so the marker check cannot
# save the tool once the swap has happened
printf '%s\nOUTSIDE-MARKED-FILE\n' "$MARK" > "$BASE/outside/marked.md"
printf '%s\nOUTSIDE-HARDLINK-BODY\n' "$MARK" > "$BASE/outside/shared.md"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
T="$BASE/consumer/docs/vendor/hindsight/failure-modes.md"
mkfifo "$T"

pre_marked=$(sha256sum "$BASE/outside/marked.md" | awk '{print $1}')
pre_shared=$(sha256sum "$BASE/outside/shared.md" | awk '{print $1}')
pre_canary=$(sha256sum "$BASE/outside/canary.md" | awk '{print $1}')
echo "BASE=$BASE  SWAP=$SWAP  HEAD=$(git -C "$WT" rev-parse --short HEAD)"

grep_holds_target() {
  local p c fd
  for p in /proc/[0-9]*; do
    read -r c < "$p/comm" 2>/dev/null || continue
    [ "$c" = grep ] || continue
    for fd in "$p"/fd/*; do
      [ "$(readlink "$fd" 2>/dev/null)" = "$T" ] && return 0
    done
  done
  return 1
}

(
  # phase 1: let the undo-journal `cp` read the FIFO through to EOF
  exec 9>"$T"
  printf '%s\n' "$MARK" >&9
  exec 9>&-
  # phase 2: spin until the write loop's ownership grep is blocked on the FIFO
  for _ in $(seq 1 200000); do grep_holds_target && break; done
  if ! grep_holds_target; then echo "SWAPPER: never saw grep hold the target" >&2; exit 1; fi
  echo "SWAPPER: grep is blocked on the FIFO; swapping now ($SWAP)" >&2
  exec 9>"$T"          # returns immediately, grep is the reader; still the FIFO
  case "$SWAP" in
    symlink-outside)  rm -f "$T"; ln -s "$BASE/outside/marked.md" "$T" ;;
    ancestor-symlink) rm -f "$T"; rmdir "$BASE/consumer/docs/vendor/hindsight"
                      ln -s "$BASE/outside" "$BASE/consumer/docs/vendor/hindsight" ;;
    hardlink-outside) rm -f "$T"; ln "$BASE/outside/shared.md" "$T" ;;
    none)             : ;;
  esac
  echo "SWAPPER: swap done" >&2
  printf '%s\n' "$MARK" >&9
  exec 9>&-
) &
SWAPPER=$!

bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt"
echo "EXIT=$?"
wait $SWAPPER 2>/dev/null

echo "--- outside tree after ---"
find "$BASE/outside" -mindepth 1 -printf '%y %s %p\n' | sort
echo "--- consumer docs after ---"
find "$BASE/consumer/docs" -mindepth 1 -printf '%y %s %p -> %l\n' | sort
for f in canary marked shared; do
  now=$(sha256sum "$BASE/outside/$f.md" 2>/dev/null | awk '{print $1}')
  eval "pre=\$pre_$f"
  if [ "$now" = "$pre" ]; then echo "OUTSIDE $f.md: UNCHANGED"; else echo "OUTSIDE $f.md: *** CHANGED *** pre=$pre now=$now"; fi
done
stat -c 'shared.md links=%h ino=%i size=%s' "$BASE/outside/shared.md"
