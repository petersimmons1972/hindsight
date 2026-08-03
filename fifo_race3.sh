#!/usr/bin/env bash
# Deterministic TOCTOU harness, v3.
# Target is a FIFO, so the tool's ownership check `grep -Fqx MARKER <target>`
# blocks in read(2) forever.  We poll /proc (slowly -- grep will wait) until a
# grep process is holding the target open, swap the path, then release grep by
# feeding it the marker on a fd taken while it was still the FIFO.
# $1 = worktree, $2 = swap mode
set -u
WT="$1"; SWAP="$2"
MARK='<!-- hindsight: vendored failure-mode catalog -->'
BASE="$(mktemp -d /tmp/hs-race3.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor/hindsight" "$BASE/outside"
( cd "$BASE/consumer" && git init -q . )
printf 'OUTSIDE-SECRET-DO-NOT-TOUCH\n' > "$BASE/outside/canary.md"
printf '%s\nOUTSIDE-MARKED-FILE\n'  "$MARK" > "$BASE/outside/marked.md"
printf '%s\nOUTSIDE-HARDLINK-BODY\n' "$MARK" > "$BASE/outside/shared.md"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
T="$BASE/consumer/docs/vendor/hindsight/failure-modes.md"
mkfifo "$T"
for f in canary marked shared; do eval "pre_$f=\$(sha256sum \"\$BASE/outside/\$f.md\" | awk '{print \$1}')"; done
echo "BASE=$BASE  SWAP=$SWAP  HEAD=$(git -C "$WT" rev-parse --short HEAD)"

find_blocked_grep() {   # echoes pid, or nothing
  local p fd
  for p in $(pgrep -x grep 2>/dev/null); do
    for fd in /proc/"$p"/fd/*; do
      if [ "$(readlink -- "$fd" 2>/dev/null)" = "$T" ]; then printf '%s' "$p"; return 0; fi
    done
  done
  return 1
}

(
  exec 2>>"$BASE/swapper.log"
  # phase 1: release the undo-journal `cp` (target still the FIFO, unmodified)
  exec 9>"$T"; printf '%s\n' "$MARK" >&9; exec 9>&-
  # phase 2: wait for the write loop's ownership grep to block on the FIFO
  gp=''
  for i in $(seq 1 600); do gp="$(find_blocked_grep)" && [ -n "$gp" ] && break; sleep 0.05; done
  if [ -z "$gp" ]; then echo "SWAPPER: never observed grep blocked on target" ; exit 1; fi
  echo "SWAPPER: grep pid=$gp blocked on $T -- swapping ($SWAP)"
  exec 9>"$T"                       # returns at once: grep is the reader, still a FIFO
  case "$SWAP" in
    symlink-outside)  rm -f "$T"; ln -s "$BASE/outside/marked.md" "$T" ;;
    ancestor-symlink) rm -f "$T"; rmdir "$BASE/consumer/docs/vendor/hindsight"
                      ln -s "$BASE/outside" "$BASE/consumer/docs/vendor/hindsight" ;;
    hardlink-outside) rm -f "$T"; ln "$BASE/outside/shared.md" "$T" ;;
    none)             : ;;
  esac
  echo "SWAPPER: swap complete; releasing grep"
  printf '%s\n' "$MARK" >&9; exec 9>&-
) &
SWAPPER=$!

timeout 60 bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt"
echo "EXIT=$?"
wait $SWAPPER 2>/dev/null
echo "--- swapper log ---"; cat "$BASE/swapper.log" 2>/dev/null
echo "--- outside tree after ---";  find "$BASE/outside" -mindepth 1 -printf '%y %s %p\n' | sort
echo "--- consumer docs after ---"; find "$BASE/consumer/docs" -mindepth 1 -printf '%y %s %p -> %l\n' | sort
for f in canary marked shared; do
  now=$(sha256sum "$BASE/outside/$f.md" 2>/dev/null | awk '{print $1}'); eval "pre=\$pre_$f"
  [ "$now" = "$pre" ] && echo "OUTSIDE $f.md: UNCHANGED" || echo "OUTSIDE $f.md: *** CHANGED *** pre=$pre now=$now"
done
stat -c 'outside/shared.md links=%h ino=%i size=%s' "$BASE/outside/shared.md"
