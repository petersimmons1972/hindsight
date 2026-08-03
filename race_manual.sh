#!/usr/bin/env bash
# Deterministic TOCTOU run against bin/sync-failure-modes.sh.  $1=worktree $2=swap
#
# The target is a FIFO.  Every read the tool performs on it is a blocking
# open(2).  A blocking open does not yet appear in /proc/PID/fd, so the reliable
# signal is the WRITER side: our `exec 9>fifo` returns exactly when some reader
# has completed its open().
#
#   reader 1 = undo-journal `cp --no-dereference target backup`  -> release as-is
#   (wait until nothing holds the FIFO, i.e. cp has exited)
#   reader 2 = write-loop  `grep -Fqx MARKER target`             -> SWAP, then release
#
# so the swap is strictly after the tool's ownership check opened the path and
# strictly before the tool writes.
set -u
WT="$1"; SWAP="$2"
MARK='<!-- hindsight: vendored failure-mode catalog -->'
BASE="$(mktemp -d /tmp/hs-man.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor/hindsight" "$BASE/outside"
( cd "$BASE/consumer" && git init -q . )
printf 'OUTSIDE-SECRET-DO-NOT-TOUCH\n' > "$BASE/outside/canary.md"
printf '%s\nOUTSIDE-MARKED-FILE\n'   "$MARK" > "$BASE/outside/marked.md"
printf '%s\nOUTSIDE-HARDLINK-BODY\n' "$MARK" > "$BASE/outside/shared.md"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
T="$BASE/consumer/docs/vendor/hindsight/failure-modes.md"
mkfifo "$T"
for f in canary marked shared; do eval "pre_$f=\$(sha256sum \"\$BASE/outside/\$f.md\" | awk '{print \$1}')"; done
echo "BASE=$BASE  SWAP=$SWAP  HEAD=$(git -C "$WT" rev-parse --short HEAD)"

holders() {  # names of processes with the FIFO open, excluding this shell
  local p c fd out=''
  for p in /proc/[0-9]*; do
    [ "${p#/proc/}" = "$$" ] && continue
    [ -r "$p/comm" ] || continue; read -r c < "$p/comm" 2>/dev/null || continue
    for fd in "$p"/fd/*; do
      [ "$(readlink -- "$fd" 2>/dev/null)" = "$T" ] && { out="$out $c:${p#/proc/}"; break; }
    done
  done
  printf '%s' "$out"
}

timeout 90 bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt" \
  > "$BASE/tool.out" 2> "$BASE/tool.err" &
TOOL=$!

echo "READER-1: waiting for the undo-journal read to open the FIFO"
exec 9>"$T"
echo "READER-1: opened by ->$(holders)"
printf '%s\n' "$MARK" >&9
exec 9>&-
for i in $(seq 1 200); do [ -z "$(holders)" ] && break; sleep 0.05; done
echo "READER-1: drained after $i polls (holders now: '$(holders)')"

echo "READER-2: waiting for the write-loop ownership grep to open the FIFO"
exec 9>"$T"
H2="$(holders)"
echo "READER-2: opened by ->$H2"
echo "SWAP ($SWAP) executing now, while reader 2 is blocked in read()"
case "$SWAP" in
  symlink-outside)  rm -f "$T"; ln -s "$BASE/outside/marked.md" "$T" ;;
  ancestor-symlink) rm -f "$T"; rmdir "$BASE/consumer/docs/vendor/hindsight"
                    ln -s "$BASE/outside" "$BASE/consumer/docs/vendor/hindsight" ;;
  hardlink-outside) rm -f "$T"; ln "$BASE/outside/shared.md" "$T" ;;
  none)             : ;;
esac
echo "SWAP done: $(ls -ld "$T" 2>&1)"
printf '%s\n' "$MARK" >&9
exec 9>&-

wait $TOOL; echo "TOOL EXIT=$?"
echo "--- tool stderr ---"; cat "$BASE/tool.err"
echo "--- outside tree ---";  find "$BASE/outside" -mindepth 1 -printf '%y %s %p\n' | sort
echo "--- consumer docs ---"; find "$BASE/consumer/docs" -mindepth 1 -printf '%y %s %p -> %l\n' | sort
for f in canary marked shared; do
  now=$(sha256sum "$BASE/outside/$f.md" 2>/dev/null | awk '{print $1}'); eval "pre=\$pre_$f"
  [ "$now" = "$pre" ] && echo "OUTSIDE $f.md: UNCHANGED" || echo "OUTSIDE $f.md: *** CHANGED *** pre=$pre now=$now"
done
stat -c 'outside/shared.md links=%h ino=%i size=%s' "$BASE/outside/shared.md"
