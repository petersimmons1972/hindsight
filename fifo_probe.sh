#!/usr/bin/env bash
# Diagnostic: enumerate every blocking read the sync tool performs on a FIFO
# target, naming the process that opened it each time.
set -u
WT="$1"
MARK='<!-- hindsight: vendored failure-mode catalog -->'
BASE="$(mktemp -d /tmp/hs-probe.XXXXXX)"
mkdir -p "$BASE/consumer/docs/vendor/hindsight" "$BASE/outside"
( cd "$BASE/consumer" && git init -q . )
printf 'OUTSIDE-SECRET\n' > "$BASE/outside/canary.md"
printf '%s\n' "$BASE/consumer" > "$BASE/consumers.txt"
T="$BASE/consumer/docs/vendor/hindsight/failure-modes.md"
mkfifo "$T"
FIFO_INO="$(stat -c %i "$T")"

who_has_it() {
  local p fd tgt out=''
  for p in /proc/[0-9]*; do
    for fd in "$p"/fd/*; do
      tgt="$(readlink "$fd" 2>/dev/null)" || continue
      case "$tgt" in
        *"pipe:"*) ;;
        *) if [ "$tgt" = "$T" ]; then out="$out $(cat "$p/comm" 2>/dev/null):${p#/proc/}"; fi ;;
      esac
    done
  done
  printf '%s' "$out"
}

( for i in 1 2 3 4 5; do
    exec 9>"$T" || break
    printf 'OPEN #%d readers:%s\n' "$i" "$(who_has_it)" >&2
    printf '%s\n' "$MARK" >&9
    exec 9>&-
  done
) &
PROBE=$!
bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt"
echo "EXIT=$?"
kill $PROBE 2>/dev/null; wait $PROBE 2>/dev/null
echo "BASE=$BASE"
