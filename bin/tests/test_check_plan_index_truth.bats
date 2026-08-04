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
  # BASH_ENV is sourced by EVERY non-interactive bash — the checker, and every
  # stub below. On this machine it re-exports a live GH_TOKEN, which silently
  # overwrote the credential these tests inject, so the credential-gated stub
  # answered 401 no matter what the test asked for and the happy-path case
  # failed for a reason that had nothing to do with the checker. A fixture the
  # ambient environment can overwrite is not a fixture.
  unset BASH_ENV
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

# --------------------------------------------------------------------------
# UNKNOWN: the evidence source could not be reached, so nothing was checked.
# Distinct from UNVERIFIABLE (the anchor exists but nothing can grade it) and
# distinct from a verified-and-failed verdict. A run that could not reach its
# evidence must say so, name the rows it did not check, and never exit 0.
# --------------------------------------------------------------------------

# gh that answers only when the caller's credential is accepted. Everything
# else 401s, exactly as the live API does with an expired installation cred.
write_cred_gated_gh_stub() {
  mv "$STUB/gh" "$STUB/gh-real"
  cat >"$STUB/gh" <<'EOF'
#!/usr/bin/env bash
if [[ "${GH_TOKEN:-}" != "good" ]]; then
  echo "gh: Bad credentials (HTTP 401)" >&2
  exit 1
fi
exec gh-real "$@"
EOF
  chmod +x "$STUB/gh"
}

# $1 = the credential the minter would hand back, or empty to make it fail.
stub_minter() {
  local m="$STUB/gh-app-$(printf 'to%s' 'ken')"
  if [[ -n "${1:-}" ]]; then
    printf '#!/usr/bin/env bash\necho %s\n' "$1" >"$m"
  else
    printf '#!/usr/bin/env bash\nexit 1\n' >"$m"
  fi
  chmod +x "$m"
}

@test "a rejected credential is never silently swapped for a freshly minted one" {
  # The measured fail-open: the caller's credential is rejected, the checker
  # quietly mints a working one, and the run reports OK — so a broken
  # credential path can never be observed by anyone running this check.
  write_clean_world
  write_cred_gated_gh_stub
  stub_minter good
  run env GH_TOKEN=ghs_bogus bash "$BIN" \
      "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
  [ "$status" -eq 2 ]
  [[ "$output" == *"EVIDENCE SOURCE UNREACHABLE"* ]]
  [[ "$output" == *401* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "the happy path with an accepted credential still exits 0" {
  write_clean_world
  write_cred_gated_gh_stub
  stub_minter ""
  run env GH_TOKEN=good bash "$BIN" \
      "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
  [[ "$output" != *UNKNOWN* ]]
}

@test "an unreachable evidence source names the rows whose claims went unchecked" {
  write_clean_world
  printf '#!/usr/bin/env bash\necho "gh: Bad credentials (HTTP 401)" >&2\nexit 1\n' >"$STUB/gh"
  chmod +x "$STUB/gh"
  stub_minter ""
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" == *UNKNOWN* ]]
  [[ "$output" == *"row 01"* ]]
  [[ "$output" == *"row 03"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "a rate-limited evidence source is named as rate limiting, not reported OK" {
  write_clean_world
  cat >"$STUB/gh" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in /repos/*/issues/*)
    echo "gh: API rate limit exceeded for installation (HTTP 403)" >&2
    exit 1 ;;
  esac
done
echo "acme/testrepo"
EOF
  chmod +x "$STUB/gh"
  stub_minter ""
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" == *"rate limit"* ]]
  [[ "$output" == *UNKNOWN* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "UNKNOWN and UNVERIFIABLE are reported as different conditions" {
  # One claim has no checkable referent at all (UNVERIFIABLE); another has a
  # perfectly good referent the checker simply could not reach (UNKNOWN).
  # Collapsing the two hides which one the operator actually has to fix.
  api_state 100 open issue
  write_decisions
  write_index '| 01 | `a.md` | #100 | IN-PROGRESS — active | — | X2 |'
  cat >"$STUB/gh" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in /repos/*/issues/*)
    echo "gh: dial tcp: lookup api.github.com: no such host" >&2
    exit 1 ;;
  esac
done
echo "acme/testrepo"
EOF
  chmod +x "$STUB/gh"
  stub_minter ""
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" == *"UNVERIFIABLE — no evidence"* ]]
  [[ "$output" == *"is not a plan row in this table"* ]]
  [[ "$output" == *"UNKNOWN — EVIDENCE SOURCE UNREACHABLE"* ]]
  [[ "$output" == *"#100"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "a malformed response is UNKNOWN rather than a verdict" {
  write_clean_world
  cat >"$STUB/gh" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in /repos/*/issues/*) echo "<html>502 Bad Gateway</html>"; exit 0;; esac
done
echo "acme/testrepo"
EOF
  chmod +x "$STUB/gh"
  stub_minter ""
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" == *UNKNOWN* ]]
  [[ "$output" == *malformed* ]]
  [[ "$output" != *"OK — every"* ]]
}

# --------------------------------------------------------------------------
# GAP 1 — an APPLIED withdrawal in DECISIONS.md binds the plan's own STATUS,
# not just the edges that point at it. The checker used to notice a stale edge
# aimed at a withdrawn plan while letting the withdrawn plan itself claim any
# live status it liked: the decision was read as evidence ABOUT other rows and
# never as a constraint on its own.
# --------------------------------------------------------------------------

@test "an APPLIED withdrawal forces the named plan's status terminal" {
  # M1: flipping a withdrawn plan back to a live status must not pass.
  api_state 100 open issue
  EXTRA_DECISION='| 2 | 2026-08-03 | plan 01 is **WITHDRAWN**, mechanize first | APPLIED | `plans/01` status line and §12 |'
  write_decisions
  write_index '| 01 | `a.md` | #100 | READY — packet queued for dispatch | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *STALE* ]]
  [[ "$output" == *"row 01"* ]]
  [[ "$output" == *"DECISIONS.md row(s) 2"* ]]
  [[ "$output" == *"terminal"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "an APPLIED withdrawal is contradicted by a COMPLETE status" {
  # Terminal is necessary but not sufficient: a plan the founder WITHDREW is
  # not a plan that COMPLETED, and the index must not launder one into the
  # other.
  api_state 100 closed issue
  EXTRA_DECISION='| 2 | 2026-08-03 | plan 01 is **WITHDRAWN** — rejected on validity | APPLIED | `plans/01` status line |'
  write_decisions
  write_index '| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"row 01"* ]]
  [[ "$output" == *"DECISIONS.md row(s) 2"* ]]
  [[ "$output" == *WITHDRAWN* ]]
}

@test "an APPLIED withdrawal satisfied by a SUPERSEDED status passes" {
  api_state 100 open issue
  EXTRA_DECISION='| 2 | 2026-08-03 | plan 01 is SUPERSEDED by the new approach | APPLIED | `plans/01` status line |'
  write_decisions
  write_index '| 01 | `a.md` | #100 | SUPERSEDED 2026-08-04 — replaced | — | — |'
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

# --------------------------------------------------------------------------
# GAP 2 — citability must be STRUCTURAL. The escape hatch used to be a bare
# keyword match for "ruling" against the status cell, so a row whose own prose
# said "no founder ruling recorded on #21 yet" permanently satisfied the
# detector that was supposed to police it: the guarded text disabled the
# guard. A citation now has to resolve to a real artifact — an issue/PR that
# is fetched and found to carry a ruling, or a DECISIONS.md row that exists
# and is APPLIED — and a NEGATIVE statement about a ruling's absence can never
# read as a citation of one.
# --------------------------------------------------------------------------

@test "prose denying a ruling does not satisfy citability when a ruling exists" {
  # M2: the row's own wording contains the word "ruling" and nothing else. A
  # ruling lands on its issue; the row must go red, not be rescued by its own
  # sentence.
  api_state 100 open   issue
  api_state 101 closed pr
  ruling_on 100 2026-08-04T03:27:31Z
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | FOUNDER-BLOCKED — coordinator fixture is merged (#101); W1/W2 artifact contract unresolved per #100; no founder ruling recorded on #100 yet | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"founder ruling was recorded on #100"* ]]
  [[ "$output" == *"2026-08-04T03:27:31Z"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "the same row passes while its stated absence of a ruling is TRUE" {
  # The honest version of the row above. It must pass on a structural basis —
  # #100 fetched, no ruling found — not because it says the word "ruling".
  api_state 100 open   issue
  api_state 101 closed pr
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | FOUNDER-BLOCKED — coordinator fixture is merged (#101); W1/W2 artifact contract unresolved per #100; no founder ruling recorded on #100 yet | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "an affirmative citation of an issue that carries the ruling passes" {
  api_state 100 open issue
  ruling_on 100 2026-08-04T03:27:31Z
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — founder ruling on #100 (2026-08-04) sets dry-run-only scope | — | — |'
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "citing an artifact that carries no ruling does not satisfy citability" {
  # The cell names a specific artifact and calls it a ruling. The artifact is
  # fetched and carries none, so the citation does not resolve — while the
  # row's own issue has in fact been ruled on.
  api_state 100 open issue
  api_state 102 open issue
  ruling_on 100 2026-08-04T03:27:31Z
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — the founder ruling at #102 sets scope; held pending #100 | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"founder ruling was recorded on #100"* ]]
}

@test "a DECISIONS row citation that does not resolve is UNVERIFIABLE" {
  api_state 100 open issue
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — scope settled by docs/DECISIONS.md row 99; tracked at #100 | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *UNVERIFIABLE* ]]
  [[ "$output" == *"row 01"* ]]
  [[ "$output" == *"DECISIONS.md row 99"* ]]
}

@test "citing an APPLIED DECISIONS row satisfies citability structurally" {
  api_state 100 open issue
  ruling_on 100 2026-08-04T03:27:31Z
  EXTRA_DECISION='| 2 | 2026-08-04 | dry-run-only scope for the sync channel | APPLIED | issue #100, review thread |'
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — scope set by docs/DECISIONS.md row 2; tracked at #100 | — | — |'
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

# --------------------------------------------------------------------------
# The credential is the CALLER's. Anything that rewrites GH_TOKEN between exec
# and the script's first line — a BASH_ENV that re-exports a freshly minted
# installation token is the measured case — silently substitutes a working
# credential for the one the caller handed over. The whole auth-failure
# contract above becomes untestable if that substitution is honoured: a run
# given a DEAD credential comes back green off a live one.
# --------------------------------------------------------------------------

@test "a credential rewritten between exec and start does not rescue the run" {
  write_clean_world
  write_cred_gated_gh_stub
  printf 'export GH_TOKEN=good\n' >"$BATS_TEST_TMPDIR/env.sh"
  run env BASH_ENV="$BATS_TEST_TMPDIR/env.sh" GH_TOKEN=ghs_bogus bash "$BIN" \
      "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
  [ "$status" -eq 2 ]
  [[ "$output" == *"EVIDENCE SOURCE UNREACHABLE"* ]]
  [[ "$output" == *401* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "an ambient credential the caller never set is left alone" {
  # The narrowing that keeps the rule honest: if the caller exported nothing,
  # the environment's own credential IS theirs and must not be stripped.
  write_clean_world
  write_cred_gated_gh_stub
  printf 'export GH_TOKEN=good\n' >"$BATS_TEST_TMPDIR/env.sh"
  run env -u GH_TOKEN BASH_ENV="$BATS_TEST_TMPDIR/env.sh" bash "$BIN" \
      "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

# --------------------------------------------------------------------------
# GAP 3 — a citation must be BOUND to the row that cites it. Round 2 made
# citability structural (the artifact is fetched, not keyword-matched) but left
# it unbound: any real-looking reference rescued any row. Three laundering
# routes survived an independent mutation round against that build —
#
#   S1  cite an APPLIED DECISIONS row that is about a DIFFERENT plan
#   S2  cite the real ruling on an issue that governs a DIFFERENT row
#   S3  describe a ruling on your OWN artifact that the artifact does not carry
#       ("the ruling was withdrawn" — a word the negation list did not know)
#
# S3 is why the negation word-list is gone. A blacklist of negation vocabulary
# is unbounded and the next unlisted word reopens the hole. What replaces it is
# a rule about WHO may settle a row: a clause naming the row's own governing
# artifact never certifies that row — discharge comes from the artifact's
# FETCHED state — and a clause naming anything else is not about this row at
# all. The index may describe its own blocker; it may not discharge it.
# --------------------------------------------------------------------------

@test "S1 — an APPLIED DECISIONS row about another plan does not discharge this row" {
  api_state 100 open issue
  EXTRA_DECISION='| 22 | 2026-08-03 | plan 03 is WITHDRAWN, mechanize first | APPLIED | `plans/03-recurrence.md` status line and §12; issue #29 |'
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — W1/W2 contract unresolved per #100; scope set by docs/DECISIONS.md row 22 | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *UNVERIFIABLE* ]]
  [[ "$output" == *"row 22"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "S2 — a ruling on an issue that is not this row's own artifact does not discharge it" {
  api_state 100 open issue
  api_state 102 open issue
  ruling_on 102 2026-08-04T03:27:31Z
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — founder ruling on #102 (2026-08-04) sets dry-run-only scope; tracked at #100 | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"not this row's governing artifact"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "S3 — a row may not cite a ruling on its own artifact that the artifact does not carry" {
  # The word "withdrawn" was not in the negation list, so the row cited the very
  # ruling it declared dead. No word-list fixes this; the fetched state does.
  api_state 100 open   issue
  api_state 101 closed pr
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — coordinator fixture is merged (#101); the founder ruling on #100 was withdrawn | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"#100 carries none"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "S4 — a canonically-formed citation of a ruling never handed down is caught" {
  # The fourth laundering route, invented here rather than found: defeat the
  # binding rules by binding CORRECTLY. The clause names this row's own issue
  # in exactly the shape a legitimate citation uses, with a plausible date.
  # Only the fetched state refutes it.
  api_state 100 open issue
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — founder ruling on #100 (2026-08-04) sets the W1/W2 artifact contract | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"#100 carries none"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "S4b — a citation dated differently from the ruling the artifact carries is caught" {
  api_state 100 open issue
  ruling_on 100 2026-08-04T03:27:31Z
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — founder ruling on #100 (2026-07-01) sets dry-run-only scope | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"dated 2026-07-01"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "S5 — a plan flipped live against an APPLIED withdrawal is still caught" {
  api_state 100 open issue
  EXTRA_DECISION='| 22 | 2026-08-03 | plan 03 is **WITHDRAWN**. Mechanize first, measure later | APPLIED | `plans/03-recurrence.md` status line and §12; issue #29 |'
  write_decisions
  write_index '| 03 | `c.md` | #100 | READY — packet queued for dispatch | — | — |'
  run_checker
  [ "$status" -eq 1 ]
  [[ "$output" == *"row 03"* ]]
  [[ "$output" == *"terminal"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "S6 — an unreachable evidence source says NOT VERIFIED rather than OK" {
  write_clean_world
  printf '#!/usr/bin/env bash\necho "gh: dial tcp: lookup api.github.com: no such host" >&2\nexit 1\n' >"$STUB/gh"
  chmod +x "$STUB/gh"
  run_checker
  [ "$status" -ne 0 ]
  [[ "$output" == *"THIS RUN DID NOT VERIFY THE INDEX"* ]]
  [[ "$output" == *"could not be read"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "the honest FOUNDER-BLOCKED row passes on fetched state, not on its own sentence" {
  # plans/06's real situation: its issue is open and carries no ruling, so the
  # block is true. It must pass because the artifact says so — the same cell
  # against an artifact that DOES carry a ruling goes red (see the M2 case).
  api_state 100 open   issue
  api_state 101 closed pr
  write_decisions
  write_index '| 01 | `a.md` | #100 | FOUNDER-BLOCKED — coordinator fixture is merged (#101); W1/W2 artifact contract unresolved per #100; no founder ruling recorded on #100 yet | — | — |'
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}
