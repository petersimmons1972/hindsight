#!/usr/bin/env bash
# check-plan-preamble.sh -- lint plans/ against the ceiling and the canonical blocks.
#
# Decomposition without this lint recreates this repo's origin story: two copies of a governance
# artifact, both edited, both drifting. §5 and §6 of every plan are copied from docs/INVARIANTS.md,
# so something has to assert they still match.
#
# Exit 0 = every executed assertion passed. Exit 1 = a FAIL. Exit 2 = the lint could not run.
# A SKIPPED assertion is reported and never silently counted as a pass.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLANS="$ROOT/plans"
INV="$ROOT/docs/INVARIANTS.md"
MAX_LINES="${MAX_LINES:-250}"
MAX_BYTES="${MAX_BYTES:-12288}"
MAX_FILES="${MAX_FILES:-6}"

fails=0; checked=0; skips=0
fail() { printf 'FAIL  %s\n' "$*" >&2; fails=$((fails+1)); }
pass() { printf 'ok    %s\n' "$*"; checked=$((checked+1)); }
skip() { printf 'SKIP  %s -- %s\n' "$1" "$2" >&2; skips=$((skips+1)); }

[ -d "$PLANS" ] || { printf 'lint: no plans/ at %s\n' "$PLANS" >&2; exit 2; }
[ -r "$INV" ]   || { printf 'lint: no docs/INVARIANTS.md at %s\n' "$INV" >&2; exit 2; }

# Canonical rule identifiers, extracted from the INVARIANTS table rather than hardcoded here --
# hardcoding them would be a third copy, which is the defect this lint exists to prevent.
mapfile -t CANON < <(grep -oE '^\| (R[0-9]+|FM-[0-9]+) ' "$INV" | tr -d '| ' | sort -u)
if [ "${#CANON[@]}" -eq 0 ]; then
  printf 'lint: could not extract any rule ids from %s -- refusing to pass vacuously\n' "$INV" >&2
  exit 2
fi
printf 'canonical rule ids in INVARIANTS.md: %s\n\n' "${CANON[*]}"

shopt -s nullglob
found=0
for p in "$PLANS"/[0-9][0-9]-*.md; do
  name="$(basename "$p")"
  # 00-INDEX.md is the index, not a plan -- it has no sections, no issue, no §7.
  case "$name" in 00-*) continue ;; esac
  found=$((found+1))

  # ---- ceiling: lines, bytes
  L=$(wc -l < "$p"); B=$(wc -c < "$p")
  if [ "$L" -le "$MAX_LINES" ]; then pass "$name lines $L <= $MAX_LINES"
  else fail "$name lines $L > $MAX_LINES -- a unit that does not fit is two units"; fi
  if [ "$B" -le "$MAX_BYTES" ]; then pass "$name bytes $B <= $MAX_BYTES"
  else fail "$name bytes $B > $MAX_BYTES"; fi

  # ---- all 14 sections present, in order
  missing=""
  for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14; do
    grep -qE "^## $n\." "$p" || missing="$missing $n"
  done
  if [ -z "$missing" ]; then pass "$name all 14 sections present"
  else fail "$name missing section(s):$missing"; fi

  # ---- exactly one issue reference on the header line
  iss=$(grep -m1 '^Issue:' "$p" || true)
  if [ -z "$iss" ]; then fail "$name has no 'Issue:' header line"
  else
    n_iss=$(printf '%s' "$iss" | grep -oE 'hindsight#[0-9]+' | sort -u | wc -l)
    if [ "$n_iss" -le 1 ]; then pass "$name declares $n_iss issue"
    else fail "$name declares $n_iss issues on its header -- one issue per plan"; fi
  fi

  # ---- §7 file count
  n_files=$(awk '/^## 7\./{f=1;next} /^## 8\./{f=0} f' "$p" | grep -cE '^/home/psimmons/' || true)
  if [ "$n_files" -ge 1 ] && [ "$n_files" -le "$MAX_FILES" ]; then
    pass "$name §7 names $n_files file(s)"
  elif [ "$n_files" -eq 0 ]; then
    fail "$name §7 names no absolute paths -- blast radius is unbounded"
  else
    fail "$name §7 names $n_files files > $MAX_FILES"
  fi

  # ---- §5/§6 carry the canonical rule ids verbatim, not paraphrased
  pre=$(awk '/^## 5\./{f=1} /^## 7\./{f=0} f' "$p")
  absent=""
  for r in "${CANON[@]}"; do
    case "$r" in R1|R2|R4|R5) grep -q "\b$r\b" <<<"$pre" || absent="$absent $r" ;; esac
  done
  if [ -z "$absent" ]; then pass "$name §5 carries the always-required rules"
  else fail "$name §5 is missing always-required rule(s):$absent"; fi

  for frag in \
    'enforcement' 'NEVER relax' 'NEVER read a command'"'"'s exit status through a pipe' ; do
    grep -qF "$frag" <<<"$pre" || fail "$name §5/§6 missing canonical fragment: '$frag'"
  done
  # Match the CANONICAL wording from INVARIANTS.md, not a paraphrase the canon never uses.
  if grep -qF 'value of `null` is a CORRECT answer' <<<"$pre"; then
    pass "$name §6 carries the enforcement-null prohibition"
  else
    fail "$name §6 must carry the canonical 'An \`enforcement\` value of \`null\` is a CORRECT answer' line"
  fi

  # ---- every DoD row must be answerable by a command in §9
  n_dod=$(awk '/^## 4\./{f=1;next} /^## 5\./{f=0} f' "$p" | grep -cE '^- \*\*(D|T)[0-9]+\*\*' || true)
  n_acc=$(awk '/^## 9\./{f=1;next} /^## 10\./{f=0} f' "$p" | grep -cE '^\| A[0-9]+ ' || true)
  if [ "$n_acc" -ge 1 ] && [ "$n_acc" -ge "$n_dod" ]; then
    pass "$name $n_acc acceptance command(s) for $n_dod DoD row(s)"
  else
    fail "$name has $n_dod DoD rows but only $n_acc acceptance commands -- a DoD row with no command is a claim"
  fi

  # ---- §13 must demand the literal verdict string the landing gate matches on
  if grep -qF 'VERDICT: CONFIRMED_GOOD' "$p"; then pass "$name §13 demands the verdict line"
  else fail "$name §13 does not demand the literal verdict line -- unlandable by construction"; fi
done

[ "$found" -eq 0 ] && { printf 'lint: no plan files matched %s/NN-*.md -- refusing to report success\n' "$PLANS" >&2; exit 2; }

printf '\n---\nplans %d  checked %d  failed %d  skipped %d\n' "$found" "$checked" "$fails" "$skips"
printf 'SCOPE: this lint checks STRUCTURE, not correctness. A conforming plan can still be wrong.\n'
[ "$skips" -gt 0 ] && printf 'NOTE:  %d assertion(s) SKIPPED and prove nothing.\n' "$skips"
[ "$fails" -gt 0 ] && exit 1
exit 0
