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
#
# KNOWN, UNFIXED, and deliberately not pinned by any test here: the checker's §7 counter matches
# only lines that BEGIN with the absolute repo prefix, so an indented path, a #-commented path, a
# `~/`-relative path and a repo-relative path are all uncounted -- a §7 with 6 counted plus 4
# uncounted entries lints as 6. That weakness predates this round. No case below depends on it,
# and none of them makes it worse; closing it is a separate change with its own red.

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
  mkdir -p "$r/pipeline/L3/briefs" "$r/pipeline/tests" "$r/docs" "$r/plans"
  # The plan travels with the victim repo, rooted at the victim, so an undo that derives its
  # own blast radius from §7 has the document to derive it from. An undo that hardcodes the
  # list ignores this file; nothing here requires either shape.
  sed "s#/home/psimmons/projects/hindsight#$r#g" "$PLAN06" > "$r/plans/06-l3-invariant-ledger.md"
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

# ============================================================================
# ROUND 2 -- the defects two independent reviewers found in the round-1 fix.
#
# Everything below is behavioural except the two document-wording assertions that the spec
# demands in prose (the -D guidance and the gitignored-file statement); both of those are
# paired with an execution check so wording alone cannot buy a pass.
#
# JOINT CONSTRAINT, stated once so it is not discovered by thrashing: P15 requires that an
# untracked file directly under pipeline/L3/ is removed by the undo, while P24 requires that
# an untracked file directly under pipeline/tests/ is NOT. Those two paths sit in structurally
# identical positions relative to §7's entries, so no rule derived from §7 satisfies both
# unless §7 itself distinguishes them. Both assertions are contract; resolve it in §7.
# ============================================================================

plan_branch() { grep -oE 'feat/[A-Za-z0-9._/-]+' "$PLAN06" | head -1; }

# A throwaway repo shaped like hindsight BEFORE the plan runs: no pipeline/L3, no validate_l3.py,
# no docs/L3.md -- those are files the plan creates. pipeline/L1 exists and is forbidden to touch.
build_plan_repo() {
  local r="$1" branch
  branch="$(plan_branch)"
  mkdir -p "$r/pipeline/L1" "$r/pipeline/L2" "$r/pipeline/tests/fixtures" "$r/docs" "$r/plans"
  printf '{"id":"l1-1"}\n'     > "$r/pipeline/L1/entries.jsonl"
  printf '{"cluster":1}\n'     > "$r/pipeline/L2/clusters.jsonl"
  printf 'pre-existing test\n' > "$r/pipeline/tests/test_existing.py"
  printf 'invariants\n'        > "$r/docs/INVARIANTS.md"
  printf '*.scratchtmp\n'      > "$r/.gitignore"
  sed "s#/home/psimmons/projects/hindsight#$r#g" "$PLAN06" > "$r/plans/06-l3-invariant-ledger.md"
  git -C "$r" init -q -b main .
  git -C "$r" add -A
  git -C "$r" -c user.email=t@example -c user.name=t commit -qm "main: the plan has not run yet"
  git -C "$r" checkout -qb "$branch"
}

vcommit() { git -C "$1" -c user.email=t@example -c user.name=t commit -qm "$2"; }

# Extract the undo from the DOCUMENT and re-root it at the victim. Refuses to hand back a script
# that still points at a real checkout.
undo_script_for() {
  local victim="$1" out="$2"
  extract_undo | sed "s#/home/psimmons/projects/hindsight#$victim#g" > "$out"
  [ -s "$out" ]
  ! grep -q 'projects/hindsight' "$out"
}

# ---- 8. the undo must not destroy branch-local commits ---------------------

@test "P21: a brief committed ONLY on the feature branch SURVIVES the undo" {
  local victim="$TMP/v21" script="$TMP/undo21.sh" branch sha
  branch="$(plan_branch)"
  mkdir -p "$victim"
  build_plan_repo "$victim"

  mkdir -p "$victim/pipeline/L3/briefs"
  printf 'W1 family brief -- committed on the feature branch only\n' \
    > "$victim/pipeline/L3/briefs/w1-family.md"
  git -C "$victim" add pipeline/L3/briefs/w1-family.md
  vcommit "$victim" "W1 family brief"
  sha="$(git -C "$victim" rev-parse HEAD)"

  # plus the ordinary uncommitted mess the undo exists to clear
  printf 'validator\n' > "$victim/pipeline/validate_l3.py"
  mkdir -p "$victim/pipeline/L3/work"
  printf 'spool\n' > "$victim/pipeline/L3/work/spool.jsonl"

  undo_script_for "$victim" "$script"
  run bash "$script"   # a refusal to delete an unmerged branch is the safety property, not a bug

  # the branch still exists and still carries the commit
  run git -C "$victim" rev-parse --verify --quiet "refs/heads/$branch"
  [ "$status" -eq 0 ]
  run git -C "$victim" branch --contains "$sha"
  [ "$status" -eq 0 ]
  [ -n "$output" ]
  # and the brief's content is still retrievable from that commit
  run git -C "$victim" show "$sha:pipeline/L3/briefs/w1-family.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"W1 family brief"* ]]
  # the undo still returned the operator to main
  run git -C "$victim" rev-parse --abbrev-ref HEAD
  [ "$output" = "main" ]
}

@test "P22: a STAGED edit to a forbidden path does not survive and is not carried onto main" {
  local victim="$TMP/v22" script="$TMP/undo22.sh"
  mkdir -p "$victim"
  build_plan_repo "$victim"

  printf '{"id":"FORBIDDEN-EDIT"}\n' >> "$victim/pipeline/L1/entries.jsonl"
  git -C "$victim" add pipeline/L1/entries.jsonl     # staged, never committed

  undo_script_for "$victim" "$script"
  run bash "$script"
  [ "$status" -eq 0 ]

  [ -f "$victim/pipeline/L1/entries.jsonl" ]
  ! grep -q 'FORBIDDEN-EDIT' "$victim/pipeline/L1/entries.jsonl"
  run git -C "$victim" diff --cached --name-only
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  run git -C "$victim" status --porcelain
  [ "$status" -eq 0 ]
  ! printf '%s\n' "$output" | grep -q 'pipeline/L1/entries.jsonl'
  run git -C "$victim" rev-parse --abbrev-ref HEAD
  [ "$output" = "main" ]
}

# ---- 9. the clean is complete, and stops exactly at §7's authorised set -----

@test "P23: files the plan CREATES do not survive as untracked on main" {
  local victim="$TMP/v23" script="$TMP/undo23.sh"
  mkdir -p "$victim"
  build_plan_repo "$victim"

  mkdir -p "$victim/pipeline/L3"
  printf 'validator\n'  > "$victim/pipeline/validate_l3.py"
  printf 'L3 doc\n'     > "$victim/docs/L3.md"
  printf '{"row":1}\n'  > "$victim/pipeline/L3/invariants.jsonl"
  printf 'test\n'       > "$victim/pipeline/tests/test_validate_l3.py"

  undo_script_for "$victim" "$script"
  run bash "$script"
  [ "$status" -eq 0 ]

  [ ! -e "$victim/pipeline/validate_l3.py" ]
  [ ! -e "$victim/docs/L3.md" ]
  [ ! -e "$victim/pipeline/L3/invariants.jsonl" ]
  [ ! -e "$victim/pipeline/tests/test_validate_l3.py" ]
  # the pre-existing test file was never the plan's to delete
  [ -f "$victim/pipeline/tests/test_existing.py" ]
}

@test "P24: untracked WIP OUTSIDE section 7's authorised set is NOT deleted" {
  local victim="$TMP/v24" script="$TMP/undo24.sh"
  mkdir -p "$victim"
  build_plan_repo "$victim"

  printf 'unrelated wip\n' > "$victim/pipeline/tests/unrelated_wip.py"
  printf 'unrelated wip\n' > "$victim/pipeline/L2/scratch_notes.md"
  printf 'unrelated wip\n' > "$victim/wip_notes.txt"
  # something the undo IS authorised to remove, so a no-op undo cannot pass this test
  mkdir -p "$victim/pipeline/L3/work"
  printf 'spool\n' > "$victim/pipeline/L3/work/spool.jsonl"

  undo_script_for "$victim" "$script"
  run bash "$script"
  [ "$status" -eq 0 ]

  [ ! -e "$victim/pipeline/L3/work/spool.jsonl" ]
  [ -f "$victim/pipeline/tests/unrelated_wip.py" ]
  [ -f "$victim/pipeline/L2/scratch_notes.md" ]
  [ -f "$victim/wip_notes.txt" ]
}

@test "P25: the undo never force-deletes a branch, and the document says what to do instead" {
  local s11
  ! grep -qE 'branch[[:space:]]+-D([[:space:]]|$)' "$PLAN06"
  ! grep -qE 'branch[[:space:]]+--delete[[:space:]]+--force' "$PLAN06"
  ! grep -qE 'branch[[:space:]]+--force[[:space:]]+--delete' "$PLAN06"
  s11="$(section_of 11 "$PLAN06")"
  [ -n "$s11" ]
  printf '%s\n' "$s11" | grep -qi 'branch'
  if extract_undo | grep -qE 'git[[:space:]]+branch[[:space:]]+(-d|--delete)'; then
    # a safe delete can refuse; the document must say that is the safety property working
    printf '%s\n' "$s11" | grep -qiE 'refus|declin|unmerged|will not delete'
  else
    # no delete at all: the document must hand the branch to the operator
    printf '%s\n' "$s11" | grep -qiE '(delete|remove)[^.]{0,80}branch|branch[^.]{0,80}(delete|remove)'
  fi
}

@test "P26: the document states the gitignored-file behaviour and the undo matches the statement" {
  local victim="$TMP/v26" script="$TMP/undo26.sh" s11
  s11="$(section_of 11 "$PLAN06")"
  printf '%s\n' "$s11" | grep -qiE 'gitignore|ignored'

  mkdir -p "$victim"
  build_plan_repo "$victim"
  mkdir -p "$victim/pipeline/L3/work"
  printf 'spool\n'   > "$victim/pipeline/L3/work/spool.jsonl"
  printf 'ignored\n' > "$victim/pipeline/L3/work/scratch.scratchtmp"
  run git -C "$victim" status --porcelain --ignored
  [[ "$output" == *"scratch.scratchtmp"* ]]

  undo_script_for "$victim" "$script"
  run bash "$script"
  [ "$status" -eq 0 ]
  [ ! -e "$victim/pipeline/L3/work/spool.jsonl" ]

  if grep -qE 'clean[^;&|]*-[a-zA-Z]*x' "$script"; then
    [ ! -e "$victim/pipeline/L3/work/scratch.scratchtmp" ]
  else
    [ -f "$victim/pipeline/L3/work/scratch.scratchtmp" ]
  fi
}

@test "P27: the cleaned set is DERIVED from section 7 -- editing section 7 moves it" {
  local victim="$TMP/v27" script="$TMP/undo27.sh" p
  mkdir -p "$victim"
  build_plan_repo "$victim"
  p="$victim/plans/06-l3-invariant-ledger.md"
  # swap one §7 entry for a different directory: the count is unchanged, the authorised set is not
  sed -i "s#^$victim/docs/L3.md\$#$victim/pipeline/L4scratch/#" "$p"
  grep -q "^$victim/pipeline/L4scratch/\$" "$p"
  ! grep -q "^$victim/docs/L3.md\$" "$p"

  mkdir -p "$victim/pipeline/L4scratch"
  printf 'now authorised\n' > "$victim/pipeline/L4scratch/spool.jsonl"
  printf 'no longer authorised\n' > "$victim/docs/L3.md"

  undo_script_for "$victim" "$script"
  run bash "$script"
  [ "$status" -eq 0 ]

  [ ! -e "$victim/pipeline/L4scratch/spool.jsonl" ]
  [ -f "$victim/docs/L3.md" ]
}

# ---- 10. a section-7 DIRECTORY entry cannot hand over the whole repo -------

# A fixture plan whose §7 is exactly the given entries, derived from plan 06 so the rest of the
# structure the checker demands stays intact.
fixture_plan_with_entries() {
  local out="$1"; shift
  LIST="$(printf '%s\n' "$@")" awk '
    BEGIN { list = ENVIRON["LIST"] }
    /^## 7\./ { insec = 1 }
    /^## 8\./ { insec = 0 }
    {
      if (insec && $0 ~ /^\/home\/psimmons\//) {
        if (!done) { printf "%s\n", list; done = 1 }
        next
      }
      print
    }' "$PLAN06" > "$out"
}

# The FAIL the checker emits must name the plan and explain the bound -- a bare count message
# would leave the operator with no idea what to change.
assert_bounded_reject() {
  printf '%s\n' "$output" | grep '^FAIL' | grep -q '91-fixture.md'
  printf '%s\n' "$output" | grep '^FAIL' \
    | grep -qiE 'director|root|segment|beneath|below|broad|sweeping|top-level|whole repo'
}

@test "P28: a section 7 naming the REPOSITORY ROOT as a directory is REJECTED" {
  make_root "$TMP/dirroot"
  fixture_plan_with_entries "$TMP/dirroot/plans/91-fixture.md" \
    '/home/psimmons/projects/hindsight/'
  run_checker "$TMP/dirroot"
  [ "$status" -eq 1 ]
  assert_bounded_reject
}

@test "P29: a section 7 naming a TOP-LEVEL source directory is REJECTED" {
  make_root "$TMP/dirtop"
  fixture_plan_with_entries "$TMP/dirtop/plans/91-fixture.md" \
    '/home/psimmons/projects/hindsight/pipeline/'
  run_checker "$TMP/dirtop"
  [ "$status" -eq 1 ]
  assert_bounded_reject
}

@test "P30: a plausible work directory deep in the tree is ACCEPTED" {
  make_root "$TMP/dirok"
  fixture_plan_with_entries "$TMP/dirok/plans/91-fixture.md" \
    '/home/psimmons/projects/hindsight/pipeline/L3/work/'
  run_checker "$TMP/dirok"
  [ "$status" -eq 0 ]
  [[ "$output" == *"91-fixture.md §7 names 1 file(s)"* ]]
  [ "$(fail_lines)" -eq 0 ]
}

@test "P31: satisfying the COUNT does not buy a sweeping directory entry" {
  make_root "$TMP/dirmix"
  fixture_plan_with_entries "$TMP/dirmix/plans/91-fixture.md" \
    '/home/psimmons/projects/hindsight/pipeline/a.py' \
    '/home/psimmons/projects/hindsight/pipeline/b.py' \
    '/home/psimmons/projects/hindsight/pipeline/c.py' \
    '/home/psimmons/projects/hindsight/pipeline/d.py' \
    '/home/psimmons/projects/hindsight/pipeline/e.py' \
    '/home/psimmons/projects/hindsight/'
  run_checker "$TMP/dirmix"
  [ "$status" -eq 1 ]
  assert_bounded_reject
}

# ---- 11. every stated ceiling is pinned to the gate's default --------------

declared_max_files() {  # root -> the checker's DEFAULT MAX_FILES
  sed -n 's/^MAX_FILES=.*:-\([0-9]\+\)}.*/\1/p' "$1/bin/check-plan-preamble.sh" 2>/dev/null | head -1
}

# Every prose statement of the file ceiling under $1, as path:line:match.
# Exit 2 when there is no evidence at all -- an empty sweep must never read as agreement.
stated_ceilings() {
  local hits
  hits="$(grep -rnoE '(≤|<=)[[:space:]]*[0-9]+[- ]?files?' --include='*.md' "$1" 2>/dev/null || true)"
  [ -n "$hits" ] || return 2
  printf '%s\n' "$hits"
}

# Statements that disagree with the gate. Exit 2 if either side of the comparison is missing.
ceiling_mismatches() {
  local want hits
  want="$(declared_max_files "$1")"
  [ -n "$want" ] || return 2
  hits="$(stated_ceilings "$1")" || return 2
  printf '%s\n' "$hits" | awk -v want="$want" '{
    m = $0; sub(/^.*:[0-9]+:/, "", m)
    if (match(m, /[0-9]+/)) { v = substr(m, RSTART, RLENGTH) + 0; if (v != want + 0) print $0 }
  }'
}

@test "P32: every stated file ceiling in the repo equals the checker's default" {
  local n
  [ -n "$(declared_max_files "$REPO")" ]
  run stated_ceilings "$REPO"
  [ "$status" -eq 0 ]
  n="$(printf '%s\n' "$output" | grep -c .)"
  [ "$n" -ge 4 ]
  # the four the reviewers named must all still be in the sweep's reach
  [ "$(printf '%s\n' "$output" | grep -c '/PLAN\.md:')" -ge 2 ]
  printf '%s\n' "$output" | grep -q '/plans/00-INDEX\.md:'
  printf '%s\n' "$output" | grep -q '/plans/AUTOMATION-QUEUE\.md:'
  run ceiling_mismatches "$REPO"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "P33: desyncing any ONE stated ceiling is caught by that sweep" {
  local root="$TMP/sync" want bad f
  mkdir -p "$root/bin" "$root/plans"
  cp "$CHECKER" "$root/bin/check-plan-preamble.sh"
  cp "$REPO/PLAN.md" "$root/PLAN.md"
  cp "$REPO/plans/00-INDEX.md" "$REPO/plans/AUTOMATION-QUEUE.md" "$root/plans/"
  want="$(declared_max_files "$root")"
  [ -n "$want" ]
  bad=$((want + 1))

  # bring the copies into sync first, so the mutation is the only difference
  for f in PLAN.md plans/00-INDEX.md plans/AUTOMATION-QUEUE.md; do
    sed -i -E "s/(≤|<=)[[:space:]]*[0-9]+([- ]?files?)/\1${want}\2/g" "$root/$f"
    cp "$root/$f" "$root/$f.orig"
  done
  run ceiling_mismatches "$root"
  [ "$status" -eq 0 ]
  [ -z "$output" ]

  for f in PLAN.md plans/00-INDEX.md plans/AUTOMATION-QUEUE.md; do
    sed -i -E "s/(≤|<=)[[:space:]]*[0-9]+([- ]?files?)/\1${bad}\2/g" "$root/$f"
    run ceiling_mismatches "$root"
    [ "$status" -eq 0 ]
    [ -n "$output" ]
    printf '%s\n' "$output" | grep -q "$(basename "$f")"
    cp "$root/$f.orig" "$root/$f"
  done
}

@test "P34: the ceiling sweep FAILS LOUD when its evidence is missing" {
  mkdir -p "$TMP/vac/bin"
  cp "$CHECKER" "$TMP/vac/bin/check-plan-preamble.sh"
  run ceiling_mismatches "$TMP/vac"          # a checker but no prose statement anywhere
  [ "$status" -eq 2 ]
  mkdir -p "$TMP/vac2/plans"
  cp "$REPO/plans/00-INDEX.md" "$TMP/vac2/plans/"
  run ceiling_mismatches "$TMP/vac2"         # statements but no checker to compare against
  [ "$status" -eq 2 ]
}
