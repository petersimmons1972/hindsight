#!/usr/bin/env bash
# Does the --undo path enforce the same containment as the write path?
set -u
WT="$1"
MARK='<!-- hindsight: vendored failure-mode catalog -->'
echo "HEAD=$(git -C "$WT" rev-parse --short HEAD)"

echo "############ U1: normal apply then undo (functional baseline)"
B1="$(mktemp -d /tmp/hs-u1.XXXXXX)"; mkdir -p "$B1/consumer/docs/vendor/hindsight"
printf '%s\nPRE-EXISTING-VENDORED-COPY\n' "$MARK" > "$B1/consumer/docs/vendor/hindsight/failure-modes.md"
pre=$(sha256sum "$B1/consumer/docs/vendor/hindsight/failure-modes.md" | awk '{print $1}')
printf '%s\n' "$B1/consumer" > "$B1/consumers.txt"
J=$(bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$B1/consumers.txt" 2>&1 | sed -n 's/^UNDO JOURNAL: //p')
echo "  journal=$J"; echo "  journal contents:"; sed 's/^/    /' "$J"
echo "  after apply: $(stat -c %s "$B1/consumer/docs/vendor/hindsight/failure-modes.md")"
bash "$WT/bin/sync-failure-modes.sh" --undo "$J"; echo "  undo EXIT=$?"
post=$(sha256sum "$B1/consumer/docs/vendor/hindsight/failure-modes.md" | awk '{print $1}')
[ "$pre" = "$post" ] && echo "  RESTORED correctly" || echo "  *** NOT RESTORED *** pre=$pre post=$post"

echo
echo "############ U2: journal naming a target OUTSIDE any consumer root"
B2="$(mktemp -d /tmp/hs-u2.XXXXXX)"; mkdir -p "$B2/outside"
printf 'OUTSIDE-SECRET\n' > "$B2/outside/canary.md"
printf 'ATTACKER-CONTENT\n' > "$B2/payload"
JD="$B2/j"; mkdir -p "$JD"
printf '# hindsight-sync-undo-v1\n' > "$JD/journal.tsv"
printf '%s\t%s\t%s\n' "$B2/outside/canary.md" untracked "$B2/payload" >> "$JD/journal.tsv"
echo "  crafted journal:"; sed 's/^/    /' "$JD/journal.tsv"
echo "  pre : $(sha256sum "$B2/outside/canary.md")"
bash "$WT/bin/sync-failure-modes.sh" --undo "$JD/journal.tsv"; echo "  undo EXIT=$?"
echo "  post: $(sha256sum "$B2/outside/canary.md")"
grep -q ATTACKER-CONTENT "$B2/outside/canary.md" && echo "  *** --undo WROTE OUTSIDE, no containment check ***" || echo "  outside untouched"

echo
echo "############ U3: journal with state=absent naming an outside path (deletion)"
B3="$(mktemp -d /tmp/hs-u3.XXXXXX)"; mkdir -p "$B3/outside"
printf 'DELETE-ME-IF-VULNERABLE\n' > "$B3/outside/victim.md"
JD3="$B3/j"; mkdir -p "$JD3"
printf '# hindsight-sync-undo-v1\n' > "$JD3/journal.tsv"
printf '%s\t%s\t%s\n' "$B3/outside/victim.md" absent - >> "$JD3/journal.tsv"
bash "$WT/bin/sync-failure-modes.sh" --undo "$JD3/journal.tsv"; echo "  undo EXIT=$?"
[ -e "$B3/outside/victim.md" ] && echo "  victim survived" || echo "  *** --undo DELETED an outside file ***"

echo
echo "############ U4: tool-produced journal for a symlinked target, ancestor swapped before undo"
B4="$(mktemp -d /tmp/hs-u4.XXXXXX)"; mkdir -p "$B4/consumer/docs/vendor/hindsight" "$B4/outside"
printf 'OUTSIDE-SECRET\n' > "$B4/outside/canary.md"
ln -s "$B4/outside/canary.md" "$B4/consumer/docs/vendor/hindsight/failure-modes.md"
printf '%s\n' "$B4/consumer" > "$B4/consumers.txt"
J4=$(bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$B4/consumers.txt" 2>&1 | sed -n 's/^UNDO JOURNAL: //p')
echo "  journal row (note: unresolved path?):"; sed 's/^/    /' "$J4"
# operator-timeline: an ancestor becomes a symlink to outside between apply and undo
rm -f "$B4/consumer/docs/vendor/hindsight/failure-modes.md"
rmdir "$B4/consumer/docs/vendor/hindsight"
ln -s "$B4/outside" "$B4/consumer/docs/vendor/hindsight"
echo "  pre outside: $(find "$B4/outside" -type f -printf '%p:%s ')"
bash "$WT/bin/sync-failure-modes.sh" --undo "$J4"; echo "  undo EXIT=$?"
echo "  post outside: $(find "$B4/outside" -type f -o -type l -printf '%y:%p ')"
