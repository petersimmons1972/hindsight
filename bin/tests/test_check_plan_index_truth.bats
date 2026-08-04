#!/usr/bin/env bats
#
# Tests for bin/check-plan-index-truth.sh
#
# Everything here is synthetic. The checker's whole job is to go red on the
# live index today, so a test that read the live index would go green the
# moment the index is repaired — the test would rot into a tautology and the
# checker would lose its only regression guard. Fixtures are written per-test
# into BATS_TEST_TMPDIR and the GitHub API is served by a stub `gh` driven by
# a plain-text state table, so each test states its own world.

setup() {
  BIN="$BATS_TEST_DIRNAME/../check-plan-index-truth.sh"
  export PLAN_INDEX_REPO="acme/testrepo"
  STUB="$BATS_TEST_TMPDIR/stubbin"
  mkdir -p "$STUB"
  # STATE lines:  <number> <open|closed> <issue|pr>
  # RULING lines: <number> <iso-date>   (a founder-ruling comment on that issue)
  : >"$BATS_TEST_TMPDIR/state.txt"
  : >"$BATS_TEST_TMPDIR/rulings.txt"
  write_gh_stub
  export PATH="$STUB:$PATH"
}

write_gh_stub() {
  cat >"$STUB/gh" <<'STUBEOF'
#!/usr/bin/env bash
# Minimal stand-in for the three `gh api` shapes the checker uses.
set -uo pipefail
url=""
for a in "$@"; do case "$a" in /*) url="$a"; break;; esac; done
case "$url" in
  /repos/*/issues/*/comments)
    n="${url#*/issues/}"; n="${n%/comments}"
    while read -r num when; do
      [[ "$num" == "$n" ]] || continue
      printf '%s\t**Founder ruling:** the thing is decided.\n' "$when"
    done <"$GH_STUB_RULINGS"
    exit 0 ;;
  /repos/*/issues/*)
    n="${url##*/}"
    while read -r num state kind; do
      [[ "$num" == "$n" ]] || continue
      printf '%s\t%s\tsynthetic title for #%s\n' "$state" "$kind" "$n"
      exit 0
    done <"$GH_STUB_STATE"
    echo "gh stub: no fixture row for #$n" >&2
    exit 1 ;;
  /repos/*)
    echo "${url#/repos/}"; exit 0 ;;
esac
echo "gh stub: unhandled url '$url'" >&2
exit 1
STUBEOF
  chmod +x "$STUB/gh"
  export GH_STUB_STATE="$BATS_TEST_TMPDIR/state.txt"
  export GH_STUB_RULINGS="$BATS_TEST_TMPDIR/rulings.txt"
}

api_state() { printf '%s %s %s\n' "$1" "$2" "$3" >>"$BATS_TEST_TMPDIR/state.txt"; }
ruling_on()  { printf '%s %s\n' "$1" "$2" >>"$BATS_TEST_TMPDIR/rulings.txt"; }

# A decisions file with no APPLIED row naming any plan, unless a test adds one.
write_decisions() {
  cat >"$BATS_TEST_TMPDIR/DECISIONS.md" <<'EOF'
# DECISIONS
| # | date | ruling | state | evidence / next |
|---|---|---|---|---|
| 1 | 2026-01-01 | something unrelated | OPEN | nothing |
EOF
  cat >>"$BATS_TEST_TMPDIR/DECISIONS.md" <<<"${EXTRA_DECISION:-}"
}

# $1 = the table body (rows only)
write_index() {
  { echo '# plans — index'
    echo
    echo '| # | file | issue | status | blocked-by | blocks |'
    echo '|---|---|---|---|---|---|'
    cat
  } >"$BATS_TEST_TMPDIR/00-INDEX.md" <<<"$1"
}

# The baseline world: every claim in it is live and checkable.
write_clean_world() {
  api_state 100 closed issue
  api_state 101 open   issue
  api_state 102 open   issue
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | 03 |
| 03 | `c.md` | #102 | BLOCKED — held behind 02 | 02 | — |
EOF
)"
}

run_checker() {
  run bash "$BIN" "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
}

# --------------------------------------------------------------------------
# The control. If this ever goes red the later tests prove nothing.
# --------------------------------------------------------------------------

@test "an index whose every edge and blocker is live exits 0" {
  write_clean_world
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every blocked-by"* ]]
  [[ "$output" != *STALE* ]]
  [[ "$output" != *UNVERIFIABLE* ]]
}

# --------------------------------------------------------------------------
# Discharged claims must be caught. One rule per test, so a regression names
# itself instead of collapsing into "the big test failed".
# --------------------------------------------------------------------------

@test "an edge whose target plan is COMPLETE is STALE and names the row" {
  api_state 100 closed issue
  api_state 101 closed issue
  api_state 102 open   issue
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | COMPLETE — PR merged; main green | — | 03 |
| 03 | `c.md` | #102 | BLOCKED — held behind 02 | 02 | — |
EOF
)"
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *STALE* ]]
  [[ "$output" == *"row 03"* ]]
  [[ "$output" == *"blocked-by: 02"* ]]
  [[ "$output" == *"plan 02 is COMPLETE"* ]]
}

@test "a COMPLETE plan still listed as blocking something is STALE" {
  api_state 100 closed issue
  api_state 101 closed issue
  api_state 102 open   issue
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged | — | — |
| 02 | `b.md` | #101 | COMPLETE — PR merged | — | 03 |
| 03 | `c.md` | #102 | BLOCKED — held behind 02 | 02 | — |
EOF
)"
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"row 02"* ]]
  [[ "$output" == *"blocks: 03"* ]]
}

@test "an obligation clause naming an issue that has closed is STALE" {
  api_state 100 open   issue
  api_state 200 closed issue
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | BLOCKED — push-vs-pull; #200 must select a path | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *STALE* ]]
  [[ "$output" == *"#200"* ]]
  [[ "$output" == *"CLOSED"* ]]
}

@test "a discharge statement naming a closed issue is NOT stale" {
  # "#200 is merged" is a statement of fact, not an obligation. Grading it as
  # stale would make the checker fire on every row that cites its own history.
  api_state 100 open   issue
  api_state 200 closed issue
  api_state 101 open   issue
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | BLOCKED — fixture is merged (#200); held behind 02 | 02 | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | 01 |
EOF
)"
  run_checker
  [ "$status" -eq 0 ]
}

@test "a FOUNDER-BLOCKED row whose issue already carries a ruling is STALE" {
  api_state 100 open issue
  api_state 101 open issue
  ruling_on 100 2026-08-04T03:27:31Z
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | FOUNDER-BLOCKED — design choice open; see #101 | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"founder ruling was recorded on #100"* ]]
  [[ "$output" == *"2026-08-04T03:27:31Z"* ]]
}

@test "the two halves of an edge must agree" {
  api_state 100 open issue
  api_state 101 open issue
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | IN-PROGRESS — active | — | 02 |
| 02 | `b.md` | #101 | BLOCKED — held behind something; see #100 | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"the two halves disagree"* ]]
}

@test "a COMPLETE row whose own issue is still open is STALE" {
  api_state 100 open issue
  write_decisions
  write_index '| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"its own #100"* ]]
  [[ "$output" == *"still OPEN"* ]]
}

@test "an APPLIED decision naming a plan contradicts a BLOCKED status" {
  api_state 100 open issue
  EXTRA_DECISION='| 2 | 2026-08-03 | the approach is settled | APPLIED | see `plans/01` and its status line |'
  write_decisions
  write_index '| 01 | `a.md` | #100 | BLOCKED — waiting on a ruling; see #100 | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"are APPLIED and name plans/01"* ]]
}

# --------------------------------------------------------------------------
# UNVERIFIABLE is a failure, never a silent pass.
# --------------------------------------------------------------------------

@test "a blocker with no checkable anchor is reported UNVERIFIABLE and fails" {
  api_state 100 open   issue
  api_state 200 closed pr
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | FOUNDER-BLOCKED — PR #200 rejected; design choice unresolved | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *UNVERIFIABLE* ]]
  [[ "$output" == *"row 01"* ]]
  [[ "$output" == *"prose with no checkable anchor"* ]]
}

@test "an edge pointing outside the table is UNVERIFIABLE, not assumed true" {
  api_state 100 open issue
  write_decisions
  write_index '| 01 | `a.md` | #100 | IN-PROGRESS — active | — | X2 |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *UNVERIFIABLE* ]]
  [[ "$output" == *"is not a plan row in this table"* ]]
}

@test "a WITHDRAWN row with no APPLIED decision backing it is UNVERIFIABLE" {
  api_state 100 open issue
  write_decisions
  write_index '| 01 | `a.md` | #100 | **WITHDRAWN 2026-08-03** — rejected on validity | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *UNVERIFIABLE* ]]
  [[ "$output" == *"no APPLIED row in DECISIONS.md names plans/01"* ]]
}

@test "a WITHDRAWN row backed by an APPLIED decision passes" {
  api_state 100 open issue
  EXTRA_DECISION='| 2 | 2026-08-03 | plan withdrawn, mechanize first | APPLIED | `plans/01` status line and §12 |'
  write_decisions
  write_index '| 01 | `a.md` | #100 | **WITHDRAWN 2026-08-03** — rejected on validity | — | — |'
  run_checker
  [ "$status" -eq 0 ]
}

# --------------------------------------------------------------------------
# The c-001 family: absent evidence must never read as success.
# --------------------------------------------------------------------------

@test "no gh on PATH fails loudly with exit 2, even on a clean index" {
  write_clean_world
  # A PATH carrying every tool the checker needs EXCEPT gh — so the failure is
  # unambiguously "no evidence source", not "no coreutils".
  local farm="$BATS_TEST_TMPDIR/nogh"
  mkdir -p "$farm"
  for t in bash awk tr sed grep cut paste head basename; do
    ln -sf "$(command -v "$t")" "$farm/$t"
  done
  run env PATH="$farm" bash "$BIN" "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
  [ "$status" -eq 2 ]
  [[ "$output" == *"EVIDENCE SOURCE UNREACHABLE"* ]]
  [[ "$output" == *"not installed"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "gh present but the API rejecting us fails with exit 2, not 0" {
  write_clean_world
  printf '#!/usr/bin/env bash\necho "Bad credentials" >&2\nexit 1\n' >"$STUB/gh"
  chmod +x "$STUB/gh"
  # gh-app-token must not be reachable either, or the checker would refresh.
  printf '#!/usr/bin/env bash\nexit 1\n' >"$STUB/gh-app-token"
  chmod +x "$STUB/gh-app-token"
  run env PATH="$STUB:/usr/bin:/bin" bash "$BIN" \
      "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
  [ "$status" -eq 2 ]
  [[ "$output" == *"EVIDENCE SOURCE UNREACHABLE"* ]]
}

@test "the API dying partway through grading fails with exit 2, not a verdict" {
  # The probe succeeds and then issue lookups fail. A checker that swallowed
  # this would report a clean index off two rows it never actually checked.
  write_clean_world
  cat >"$STUB/gh" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do case "$a" in /repos/*/issues/*) exit 1;; esac; done
echo "acme/testrepo"
EOF
  chmod +x "$STUB/gh"
  printf '#!/usr/bin/env bash\nexit 1\n' >"$STUB/gh-app-token"
  chmod +x "$STUB/gh-app-token"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" == *"EVIDENCE SOURCE UNREACHABLE"* ]]
  [[ "$output" != *"OK — every"* ]]
}

# --------------------------------------------------------------------------
# Parser integrity: matching nothing must not read as "nothing wrong".
# --------------------------------------------------------------------------

@test "a table the parser cannot read fails with exit 2 rather than passing" {
  write_clean_world
  printf '# plans — index\n\nno table here at all.\n' >"$BATS_TEST_TMPDIR/00-INDEX.md"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" == *"could not parse any plan rows"* ]]
}

@test "a missing index file fails with exit 2" {
  write_clean_world
  run bash "$BIN" "$BATS_TEST_TMPDIR/nope.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
  [ "$status" -eq 2 ]
  [[ "$output" == *"index not found"* ]]
}
