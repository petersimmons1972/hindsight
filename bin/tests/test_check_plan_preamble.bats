#!/usr/bin/env bats
# Contract tests for the PLAN-06 amendment (founder decision B, 2026-08-03).
#
# Three things are pinned here and nothing else:
#   1. bin/check-plan-preamble.sh's §7 ceiling is SIX entries -- 6 accepted, 7 refused, and the
#      other two ceilings (lines, bytes) are provably untouched.
#   2. plan 06 §7 carries the pipeline/L3/work/ directory entry, and the checker's OWN counter
#      reports 6 for it (the count is read out of the checker's report, never recomputed here --
#      a reimplementation of the counter would pass while the real counter drifted).
#   3. plan 06 §11's UNDO is safe on a tree where pipeline/L3 holds COMMITTED files.
#      That test is behavioural: the undo commands are extracted from the plan document and RUN
#      against a throwaway git repo. A grep for the absence of `rm -rf` would pass against a
#      differently-worded but equally destructive command, so there is no such grep.
#
# The pre-existing lint baseline (3 failures, plans 03 and 05) is pinned as-is: this change must
# neither fix nor add one. Never claim a green plan lint in this repo.

setup() {
  REPO="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  CHECKER="$REPO/bin/check-plan-preamble.sh"
  PLAN06="$REPO/plans/06-l3-invariant-ledger.md"
  INDEX="$REPO/plans/00-INDEX.md"
  TMP="$(mktemp -d "${BATS_TMPDIR:-/tmp}/planlint.XXXXXX")"
  [ -x "$CHECKER" ] || [ -r "$CHECKER" ]
  [ -r "$PLAN06" ]
}

teardown() {
  [ -n "${TMP:-}" ] && [ -d "$TMP" ] && rm -rf "$TMP"
  return 0
}

# ---- helpers ---------------------------------------------------------------

# A sandbox root holding a COPY of the checker, so ROOT resolves inside the sandbox and no test
# ever lints -- or writes to -- the real plans/ tree.
make_root() {
  local root="$1"
  mkdir -p "$root/bin" "$root/plans" "$root/docs"
  cp "$CHECKER" "$root/bin/check-plan-preamble.sh"
  cp "$REPO/docs/INVARIANTS.md" "$root/docs/INVARIANTS.md"
}

# A fixture plan derived from the repo's own plan 06 with §7 replaced by exactly N synthetic
# absolute-path entries. Derived rather than hand-written so the fixture cannot silently rot away
# from the structure the checker demands.
fixture_plan_with() {
  local n="$1" out="$2"
  awk -v n="$n" '
    /^## 7\./ { insec = 1 }
    /^## 8\./ { insec = 0 }
    {
      if (insec && $0 ~ /^\/home\/psimmons\//) {
        if (!done) {
          for (i = 1; i <= n; i++)
            printf "/home/psimmons/projects/hindsight/pipeline/fixture_%d.py\n", i
          done = 1
        }
        next
      }
      print
    }' "$PLAN06" > "$out"
}

# Run the checker with a pristine environment: MAX_FILES is env-overridable, and a test that set it
# would prove nothing about the DEFAULT, which is the thing decision B changes.
run_checker() {
  run env -u MAX_FILES -u MAX_LINES -u MAX_BYTES bash "$1/bin/check-plan-preamble.sh"
}

section_of() { # section_of N file  -> body of "## N." up to the next "## " heading
  awk -v n="$1" 'BEGIN{pat="^## " n "\\."} $0 ~ pat {f=1;next} /^## [0-9]+\./{if(f)f=0} f' "$2"
}

fail_lines() { printf '%s\n' "$output" | grep -c '^FAIL' || true; }

# ---- 1. the §7 ceiling is six ---------------------------------------------

@test "P1: a plan naming SIX files in section 7 is ACCEPTED by default" {
  make_root "$TMP/six"
  fixture_plan_with 6 "$TMP/six/plans/91-fixture.md"
  run_checker "$TMP/six"
  [ "$status" -eq 0 ]
  [[ "$output" == *"91-fixture.md §7 names 6 file(s)"* ]]
  [ "$(fail_lines)" -eq 0 ]
}

@test "P2: SEVEN files in section 7 is still REFUSED -- the ceiling moved, it did not vanish" {
  make_root "$TMP/seven"
  fixture_plan_with 7 "$TMP/seven/plans/91-fixture.md"
  run_checker "$TMP/seven"
  [ "$status" -eq 1 ]
  [[ "$output" == *"91-fixture.md §7 names 7 files > 6"* ]]
}

@test "P3: FIVE files is still accepted -- the ceiling is a maximum, not an exact count" {
  make_root "$TMP/five"
  fixture_plan_with 5 "$TMP/five/plans/91-fixture.md"
  run_checker "$TMP/five"
  [ "$status" -eq 0 ]
  [[ "$output" == *"91-fixture.md §7 names 5 file(s)"* ]]
}

@test "P4: ZERO absolute paths in section 7 still FAILS -- unbounded blast radius" {
  make_root "$TMP/zero"
  fixture_plan_with 0 "$TMP/zero/plans/91-fixture.md"
  run_checker "$TMP/zero"
  [ "$status" -eq 1 ]
  [[ "$output" == *"names no absolute paths"* ]]
}

@test "P5: MAX_FILES remains env-overridable and an override BELOW the new default still bites" {
  make_root "$TMP/ovr"
  fixture_plan_with 6 "$TMP/ovr/plans/91-fixture.md"
  run env MAX_FILES=4 bash "$TMP/ovr/bin/check-plan-preamble.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"names 6 files > 4"* ]]
}

# ---- 2. the checker's evidence source, absent, must FAIL LOUD --------------

@test "P6: no docs/INVARIANTS.md -> exit 2, never a silent pass" {
  make_root "$TMP/noinv"
  fixture_plan_with 6 "$TMP/noinv/plans/91-fixture.md"
  rm -f "$TMP/noinv/docs/INVARIANTS.md"
  run_checker "$TMP/noinv"
  [ "$status" -eq 2 ]
}

@test "P7: an INVARIANTS.md carrying no rule ids -> exit 2, refuses to pass vacuously" {
  make_root "$TMP/emptyinv"
  fixture_plan_with 6 "$TMP/emptyinv/plans/91-fixture.md"
  printf '# INVARIANTS\n\nno table here at all.\n' > "$TMP/emptyinv/docs/INVARIANTS.md"
  run_checker "$TMP/emptyinv"
  [ "$status" -eq 2 ]
}

@test "P8: an empty plans/ directory -> exit 2, refuses to report success on zero evidence" {
  make_root "$TMP/noplans"
  run_checker "$TMP/noplans"
  [ "$status" -eq 2 ]
}

# ---- 3. plan 06 itself ------------------------------------------------------

@test "P9: plan 06 section 7 names the pipeline/L3/work/ directory entry" {
  run bash -c "printf '%s\n' \"\$(awk '/^## 7\\./{f=1;next} /^## 8\\./{f=0} f' '$PLAN06')\""
  [ "$status" -eq 0 ]
  [[ "$output" == *"/home/psimmons/projects/hindsight/pipeline/L3/work/"* ]]
}

@test "P10: the checker's own counter reports SIX entries for plan 06, and plan 06 lints clean" {
  make_root "$TMP/p06"
  cp "$PLAN06" "$TMP/p06/plans/"
  run_checker "$TMP/p06"
  [ "$status" -eq 0 ]
  [[ "$output" == *"06-l3-invariant-ledger.md §7 names 6 file(s)"* ]]
  [ "$(fail_lines)" -eq 0 ]
}

@test "P11: sections 6 and 14 state no hardcoded file count that section 7 can contradict" {
  local s6 s14
  s6="$(section_of 6 "$PLAN06")"
  s14="$(section_of 14 "$PLAN06")"
  [ -n "$s6" ]
  [ -n "$s14" ]
  # a cardinal immediately qualifying "file(s)" is a count that drifts the moment §7 changes
  run bash -c "printf '%s\n%s\n' \"\$1\" \"\$2\" | grep -inE '(^|[^[:alnum:]])(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[0-9]+)[[:space:]]+files?([^[:alnum:]]|\$)'" _ "$s6" "$s14"
  [ "$status" -ne 0 ]
}

@test "P12: sections 6 and 14 still bind modification to section 7, and cover a DIRECTORY entry" {
  local both
  both="$(section_of 6 "$PLAN06")
$(section_of 14 "$PLAN06")"
  # still an imperative restriction anchored on §7
  printf '%s\n' "$both" | grep -qE '(§ ?7|section 7)'
  printf '%s\n' "$both" | grep -qE 'NEVER|ONLY|Modify'
  # and a directory entry must plainly authorise what sits beneath it
  printf '%s\n' "$both" | grep -qiE 'director(y|ies)'
  printf '%s\n' "$both" | grep -qiE '(under|beneath|within|inside|below|recursively)'
}

# ---- 4. THE UNDO IS SAFE (behavioural) -------------------------------------

# Build a throwaway repo shaped like hindsight mid-W1: pipeline/L3 holds a COMMITTED brief, plus
# uncommitted work (a dirtied tracked file and an untracked scratch file).
build_victim_repo() {
  local r="$1" branch="$2"
  mkdir -p "$r/pipeline/L3/briefs" "$r/pipeline/tests" "$r/docs"
  printf 'committed brief -- must survive the undo\n' > "$r/pipeline/L3/briefs/w1-family.md"
  printf '{"id":1}\n'  > "$r/pipeline/L3/invariants.jsonl"
  printf 'validator\n' > "$r/pipeline/validate_l3.py"
  printf 'L3 doc\n'    > "$r/docs/L3.md"
  git -C "$r" init -q -b main .
  git -C "$r" add -A
  git -C "$r" -c user.email=t@example -c user.name=t commit -qm "committed briefs exist"
  git -C "$r" checkout -qb "$branch"
  # uncommitted work of every shape the undo must remove
  printf 'DIRTY\n' >> "$r/pipeline/validate_l3.py"
  printf 'DIRTY\n' >> "$r/pipeline/L3/invariants.jsonl"
  mkdir -p "$r/pipeline/L3/work"
  printf 'scratch\n' > "$r/pipeline/L3/work/spool.jsonl"
  printf 'scratch\n' > "$r/pipeline/L3/untracked-draft.md"
}

# Read the undo out of the DOCUMENT, so the test dies if document and tested behaviour diverge.
extract_undo() {
  awk '/^## 11\./{f=1;next} /^## 12\./{f=0} f' "$PLAN06" \
    | awk '/^[[:space:]]*```/{c++; next} c==1'
}

@test "P13: section 11 actually contains an extractable undo block" {
  run extract_undo
  [ "$status" -eq 0 ]
  [ -n "$output" ]
  [[ "$output" == *"git"* ]]
}

@test "P14: the undo from section 11 PRESERVES committed files under pipeline/L3" {
  local branch victim script
  branch="$(grep -oE 'feat/[A-Za-z0-9._/-]+' "$PLAN06" | head -1)"
  [ -n "$branch" ]
  victim="$TMP/victim"
  mkdir -p "$victim"
  build_victim_repo "$victim" "$branch"

  script="$TMP/undo.sh"
  extract_undo | sed "s#/home/psimmons/projects/hindsight#$victim#g" > "$script"
  [ -s "$script" ]

  # SAFETY REFUSAL: never run an undo that still points at a real checkout.
  run grep -c 'projects/hindsight' "$script"
  [ "$status" -ne 0 ]

  run bash "$script"
  [ "$status" -eq 0 ]

  # the committed brief is the whole point
  [ -f "$victim/pipeline/L3/briefs/w1-family.md" ]
  run cat "$victim/pipeline/L3/briefs/w1-family.md"
  [[ "$output" == *"committed brief"* ]]
  # and the other committed content under pipeline/L3 survives too
  [ -f "$victim/pipeline/L3/invariants.jsonl" ]
}

@test "P15: the same undo REMOVES uncommitted work -- it reverts, it does not merely spare" {
  local branch victim script
  branch="$(grep -oE 'feat/[A-Za-z0-9._/-]+' "$PLAN06" | head -1)"
  victim="$TMP/victim2"
  mkdir -p "$victim"
  build_victim_repo "$victim" "$branch"

  script="$TMP/undo2.sh"
  extract_undo | sed "s#/home/psimmons/projects/hindsight#$victim#g" > "$script"
  run grep -c 'projects/hindsight' "$script"
  [ "$status" -ne 0 ]

  run bash "$script"
  [ "$status" -eq 0 ]

  # untracked scratch is gone
  [ ! -e "$victim/pipeline/L3/work/spool.jsonl" ]
  [ ! -e "$victim/pipeline/L3/untracked-draft.md" ]
  # tracked files are back at their committed content
  run grep -c DIRTY "$victim/pipeline/validate_l3.py"
  [ "$status" -ne 0 ]
  run grep -c DIRTY "$victim/pipeline/L3/invariants.jsonl"
  [ "$status" -ne 0 ]
  # and the tree is clean -- no lingering staged deletions of committed content
  run git -C "$victim" status --porcelain
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

# ---- 5. the pre-existing baseline must not move ----------------------------

@test "P16: the real plan lint still reports EXACTLY the three known pre-existing failures" {
  run env -u MAX_FILES -u MAX_LINES -u MAX_BYTES bash "$CHECKER"
  [ "$status" -eq 1 ]
  [ "$(fail_lines)" -eq 3 ]
  [[ "$output" == *"failed 3"* ]]
  # the three known ones, and their thresholds -- which pins MAX_LINES and MAX_BYTES untouched
  [[ "$output" == *"03-recurrence-trend-instrument.md lines 266 > 250"* ]]
  [[ "$output" == *"03-recurrence-trend-instrument.md bytes 17095 > 12288"* ]]
  [[ "$output" == *"05-enforcement-locality.md has no 'Issue:' header line"* ]]
  # nothing new, and in particular nothing from the plan being amended
  printf '%s\n' "$output" | grep '^FAIL' | grep -qv '0[35]-' && false
  return 0
}

@test "P17: no assertion was deleted to buy the baseline -- the checked count does not shrink" {
  run env -u MAX_FILES -u MAX_LINES -u MAX_BYTES bash "$CHECKER"
  local n
  n="$(printf '%s\n' "$output" | sed -n 's/^plans [0-9]* *checked \([0-9]*\) .*/\1/p')"
  [ -n "$n" ]
  [ "$n" -ge 69 ]
}

# ---- 6. the documents that quote the ceiling agree with the gate -----------

@test "P18: plans/00-INDEX.md's stated file ceiling equals the checker's actual default" {
  local declared stated
  declared="$(sed -n 's/^MAX_FILES=.*:-\([0-9]\+\)}.*/\1/p' "$CHECKER" | head -1)"
  [ -n "$declared" ]
  stated="$(grep -oE '≤ ?[0-9]+ files' "$INDEX" | head -1 | grep -oE '[0-9]+')"
  [ -n "$stated" ]
  [ "$stated" -eq "$declared" ]
}

@test "P19: PLAN.md X5 still invokes the plan-preamble gate (no collateral edit)" {
  run grep -F 'bash bin/check-plan-preamble.sh' "$REPO/PLAN.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"| X5 |"* ]]
}

# ---- 7. out-of-scope files stay out of scope -------------------------------

@test "P20: this change does not touch plans 03 or 05, nor the L3 ground-truth fixture" {
  run git -C "$REPO" diff --name-only origin/main...HEAD
  [ "$status" -eq 0 ]
  printf '%s\n' "$output" | grep -qE '^plans/0[35]-' && false
  printf '%s\n' "$output" | grep -qF 'pipeline/tests/fixtures/l3_ground_truth.jsonl' && false
  return 0
}
