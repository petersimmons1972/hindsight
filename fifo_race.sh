#!/usr/bin/env bash
# Deterministic TOCTOU harness.
#
# The sync tool reads the target twice: once in the undo-journal phase
# (cp --no-dereference target backup) and once in the write loop
# (grep -Fqx MARKER target).  Making the target a FIFO turns each of those
# reads into a blocking read(2) that we control.
#
#   open #1  -> journal-phase cp     : we release it untouched
#   open #2  -> write-loop grep      : we SWAP the path, then release
#
# so the swap lands strictly between the tool's ownership check and its write.
# $1 = worktree, $2 = swap mode
set -u
WT="$1"; SWAP="$2"
MARK='<!-- hindsight: vendored failure-mode catalog -->'
BASE="$(mktemp -d /tmp/hs-race.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor/hindsight" "$BASE/outside"
( cd "$BASE/consumer" && git init -q . )
printf 'OUTSIDE-SECRET-DO-NOT-TOUCH\n' > "$BASE/outside/canary.md"
printf '%s\nOUTSIDE-HARDLINK-BODY\n' "$MARK" > "$BASE/outside/shared.md"
printf '%s\nFOREIGN-FILE-INSIDE-REPO\n' 'not the marker' > "$BASE/foreign-src.md"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
T="$BASE/consumer/docs/vendor/hindsight/failure-modes.md"
mkfifo "$T"

echo "BASE=$BASE  SWAP=$SWAP  WT=$(git -C "$WT" rev-parse --short HEAD)"
echo "-- pre canary --";  sha256sum "$BASE/outside/canary.md"
echo "-- pre shared --";  sha256sum "$BASE/outside/shared.md"; stat -c 'links=%h ino=%i size=%s' "$BASE/outside/shared.md"

(
  # open #1: release the journal-phase read with the target still a FIFO
  exec 9>"$T"; printf '%s\n' "$MARK" >&9; exec 9>&-
  # open #2: the write loop's ownership grep.  This blocks until it opens.
  exec 9>"$T"
  case "$SWAP" in
    symlink-outside)  rm -f "$T"; ln -s "$BASE/outside/canary.md" "$T" ;;
    ancestor-symlink) rm -f "$T"; rmdir "$BASE/consumer/docs/vendor/hindsight"
                      ln -s "$BASE/outside" "$BASE/consumer/docs/vendor/hindsight" ;;
    hardlink-outside) rm -f "$T"; ln "$BASE/outside/shared.md" "$T" ;;
    foreign-inside)   rm -f "$T"; cp "$BASE/foreign-src.md" "$T" ;;
    none)             : ;;
  esac
  printf '%s\n' "$MARK" >&9; exec 9>&-
) &
SWAPPER=$!

bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt"
echo "EXIT=$?"
wait $SWAPPER 2>/dev/null

echo "-- post canary --"; sha256sum "$BASE/outside/canary.md"
echo "-- post shared --"; sha256sum "$BASE/outside/shared.md"; stat -c 'links=%h ino=%i size=%s' "$BASE/outside/shared.md"
echo "-- outside tree --"
find "$BASE/outside" -mindepth 1 -printf '%y %s %p\n' | sort
echo "-- consumer docs --"
find "$BASE/consumer/docs" -mindepth 1 -printf '%y %s %p -> %l\n' | sort
