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

# ==========================================================================
# plan-index-no-silent-row-drop — the parser must not be able to drop a row
# and still report a clean index (issue #69).
#
# Two INDEPENDENT checks, and the tests below are written so that each one is
# exercised with the other satisfied. That is the point of the pair:
#
#   * Check A (table-region integrity) catches a row that is still THERE but
#     no longer parses — even when the pinned id set is tuned to the rows that
#     survived the perturbation, which is the shape a "fix the baseline until
#     it goes green" habit produces.
#   * Check B (pinned expected id set) catches a row that is GONE from the
#     table entirely — which leaves a perfectly well-formed region that
#     Check A has nothing to complain about.
#
# Neither check can see the other's failure. Both must exist.
# ==========================================================================

# Writes the index verbatim from stdin, so line numbers in the fixture are the
# line numbers the checker must report. Deliberately NOT write_index, which
# prepends a known-good header and would hide the header-matching cases.
write_raw_index() { cat >"$BATS_TEST_TMPDIR/00-INDEX.md"; }

# Point the checker at a baseline fixture holding exactly the ids named.
pin_ids() {
  local f="$BATS_TEST_TMPDIR/expected-ids.conf" id
  { echo '# pinned baseline — never regenerate from the index'
    for id in "$@"; do echo "$id"; done
  } >"$f"
  export PLAN_INDEX_EXPECTED_IDS="$f"
}

# Replace the stub with one that records the fact it ran at all. Used to prove
# both checks fire BEFORE any evidence is fetched: `command -v gh` does not
# execute the file, so an existing marker means a real API call was attempted.
arm_gh_marker() {
  MARKER="$BATS_TEST_TMPDIR/gh-was-called"
  { echo '#!/usr/bin/env bash'
    printf ': >%q\n' "$MARKER"
    echo 'echo "gh stub: no call should have happened" >&2'
    echo 'exit 1'
  } >"$STUB/gh"
  chmod +x "$STUB/gh"
}

# The canonical two-row table, with $1 substituted as the SECOND row's id cell.
# Line numbers are fixed: 3 = header, 4 = separator, 5 = row 01, 6 = row two.
raw_two_row_index() {
  { echo '# plans — index'
    echo
    echo '| # | file | issue | status | blocked-by | blocks |'
    echo '|---|---|---|---|---|---|'
    echo '| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |'
    printf '| %s | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |\n' "$1"
  } >"$BATS_TEST_TMPDIR/00-INDEX.md"
}

# --------------------------------------------------------------------------
# CHECK A — table-region integrity
# --------------------------------------------------------------------------

@test "A1 — a row inside the table region that does not parse is FATAL, and names its line and its text" {
  # The reproduction from issue #69: perturb the id cell and the row vanishes
  # from the parse. The baseline is pinned to the SURVIVING id on purpose, so
  # Check B is satisfied and only Check A can be what fires.
  api_state 100 closed issue
  write_decisions
  pin_ids 01
  raw_two_row_index '<!--x-->02'
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  # the 1-based line number of the offending line
  grep -Eq "(line|:)[[:space:]]*6([^0-9]|$)" <<<"$output"
  # the raw offending line, so a reader can see what was skipped
  [[ "$output" == *'<!--x-->02'* ]]
  # and it must say what the rule is
  grep -qi 'silent' <<<"$output"
}

@test "A2 — every id-cell perturbation that defeats the parser is fatal, not silent" {
  # Boundary sweep. Each of these is a real markdown edit a human might make;
  # each one used to take the row out of the parse and leave the run green.
  api_state 100 closed issue
  write_decisions
  pin_ids 01
  for cell in '<!--x-->02' '02&nbsp;' '**02.**' '02[^a]' '`02`.' '02 (held)'; do
    raw_two_row_index "$cell"
    run_checker
    [ "$status" -eq 2 ]
    [[ "$output" != *"OK — every"* ]]
  done
}

@test "A3 — a row in the region with too few cells is fatal rather than skipped" {
  api_state 100 closed issue
  write_decisions
  pin_ids 01
  write_raw_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS |
EOF
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -Eq "(line|:)[[:space:]]*6([^0-9]|$)" <<<"$output"
  grep -qi 'silent' <<<"$output"
}

@test "A4 — the second (3-column) table in the index is still excluded" {
  # Load-bearing: 00-INDEX.md carries a '14 sections' table whose rows have
  # NF=5. Making the old skips fatal wholesale would fail on it. It sits
  # outside the plans-table region, so it must not be graded.
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02
  write_raw_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |

## the 14 sections

| § | section | what it defends against |
|---|---|---|
| 1 | CONTEXT YOU DO NOT HAVE | the conversation the executor never had |
| 2 | REPO FACTS | a mid-tier model that explores and then guesses |
EOF
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "A5 — the region ends at the first non-pipe line, so later junk is not graded" {
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02
  write_raw_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |

prose about the table

| not | a | plan | row |
EOF
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "A6 — a separator row using alignment colons is allowed" {
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02
  write_raw_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|:--|:-:|---:|---|:---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "A7 — the header is matched structurally, not by the literal line it happens to be today" {
  # Same six column names, different case and spacing. A checker that greps for
  # one exact string would refuse a table that is perfectly well formed.
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02
  write_raw_index <<'EOF'
# plans — index

|  #  |  File  |  Issue  |  Status  |  Blocked-By  |  Blocks  |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "A8 — no plans-table header at all is FATAL, never a clean report" {
  # A checker that cannot find its own table must refuse. Rows here still parse
  # under the old awk block, so the old code would have graded them and gone
  # green off a table it never actually located.
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02
  write_raw_index <<'EOF'
# plans — index

| plan | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qiE 'header|table' <<<"$output"
}

@test "A9 — two plans-table headers is FATAL: the checker must not pick one" {
  api_state 100 closed issue
  api_state 101 open   issue
  api_state 107 open   issue
  api_state 108 open   issue
  write_decisions
  pin_ids 01 02 07 08
  write_raw_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |

## and again, pasted below by a bad merge

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 07 | `g.md` | #107 | IN-PROGRESS — packet in flight | — | — |
| 08 | `h.md` | #108 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qiE 'header|table' <<<"$output"
}

@test "A10 — the region check runs before any evidence is fetched" {
  # Ordering matters: a malformed region must be reported as a malformed
  # region, not swallowed by whatever the API happened to say (or fail to say).
  api_state 100 closed issue
  write_decisions
  pin_ids 01
  raw_two_row_index '<!--x-->02'
  arm_gh_marker
  run_checker
  [ "$status" -eq 2 ]
  [ ! -e "$MARKER" ]
  [[ "$output" != *"OK — every"* ]]
}

@test "A11 — a malformed region is still fatal when the evidence source is also dead" {
  # Belt and braces on the c-001 family: two failures at once must not net out
  # to a pass, and must not be downgraded to the exit-1 'index is wrong' lane.
  write_decisions
  pin_ids 01
  raw_two_row_index '<!--x-->02'
  printf '#!/usr/bin/env bash\necho "gh: dial tcp: lookup api.github.com: no such host" >&2\nexit 1\n' >"$STUB/gh"
  chmod +x "$STUB/gh"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  # and the region failure is still the thing reported — a dead API must not
  # be allowed to stand in for it, or the malformed row is never seen at all.
  grep -Eq "(line|:)[[:space:]]*6([^0-9]|$)" <<<"$output"
  [[ "$output" == *'<!--x-->02'* ]]
}

# --------------------------------------------------------------------------
# CHECK B — pinned expected id set
# --------------------------------------------------------------------------

@test "B1 — an expected row missing from the table is FATAL" {
  # Check A cannot see this one: the row is gone, so the region is flawless.
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02 04
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"04"* ]]
}

@test "B2 — a parsed row that is not in the pinned baseline is FATAL" {
  api_state 100 closed issue
  api_state 101 open   issue
  api_state 109 open   issue
  write_decisions
  pin_ids 01 02
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| 09 | `i.md` | #109 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"09"* ]]
}

@test "B3 — a duplicated id is FATAL even though the id SET still matches" {
  # Set equality alone is blind here, which is why the count is explicit.
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| 02 | `b-copy.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qiE 'duplicat|twice|more than once' <<<"$output"
  [[ "$output" == *"02"* ]]
}

@test "B4 — a missing baseline file is FATAL, never an empty set that passes" {
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  export PLAN_INDEX_EXPECTED_IDS="$BATS_TEST_TMPDIR/there-is-no-such-baseline.conf"
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qiE 'baseline|expected' <<<"$output"
}

@test "B5 — a baseline with no ids in it is FATAL and says why" {
  # An empty baseline makes 'every expected row was checked' vacuously true —
  # the same shape as an empty catalog/id-ledger.txt.
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  { echo '# pinned baseline — never regenerate from the index'
    echo
    echo '   '
  } >"$BATS_TEST_TMPDIR/empty-ids.conf"
  export PLAN_INDEX_EXPECTED_IDS="$BATS_TEST_TMPDIR/empty-ids.conf"
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qi 'vacuous' <<<"$output"
}

@test "B6 — comments and blank lines in the baseline are ignored" {
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  { echo '# pinned baseline — never regenerate from the index'
    echo
    echo '01'
    echo '# 09 was never a plan'
    echo '02'
    echo
  } >"$BATS_TEST_TMPDIR/commented-ids.conf"
  export PLAN_INDEX_EXPECTED_IDS="$BATS_TEST_TMPDIR/commented-ids.conf"
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "B7 — the baseline check runs before any evidence is fetched" {
  write_decisions
  pin_ids 01 02 04
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  arm_gh_marker
  run_checker
  [ "$status" -eq 2 ]
  [ ! -e "$MARKER" ]
}

@test "B8 — a baseline mismatch exits 2, not the exit-1 'index is wrong' lane" {
  # Explicit because exit 1 is the lane a reviewer reads as 'stale row',
  # recoverable by editing prose. A checker that cannot account for its own
  # rows has not graded anything and must say so in the hard-failure lane.
  api_state 100 closed issue
  write_decisions
  pin_ids 01 02
  write_index '| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |'
  run_checker
  [ "$status" -ne 0 ]
  [ "$status" -ne 1 ]
  [ "$status" -eq 2 ]
}

# --------------------------------------------------------------------------
# The shipped baseline itself
# --------------------------------------------------------------------------

@test "C1 — conf/plan-index-expected-ids.conf exists and pins a non-empty id set" {
  conf="$BATS_TEST_DIRNAME/../../conf/plan-index-expected-ids.conf"
  [ -r "$conf" ]
  run bash -c "grep -vE '^[[:space:]]*(#|\$)' '$conf' | sed 's/[[:space:]]//g' | sed '/^\$/d' | sort -u | paste -sd, -"
  [ "$status" -eq 0 ]
  [ -n "$output" ]
  [ "$output" = "01,02,03,04,05,06,07,08" ]
}

@test "C2 — the shipped baseline says in the file that it is never regenerated" {
  conf="$BATS_TEST_DIRNAME/../../conf/plan-index-expected-ids.conf"
  [ -r "$conf" ]
  grep -qi 'regenerat' "$conf"
  grep -qiE 'never|do not|don.t' "$conf"
}

@test "C3 — a fixture index with no override is not measured against the shipped baseline" {
  # Renamed in round 2. The body is unchanged and still passes, but its old
  # title ("the shipped baseline is what the checker reads when no override is
  # set") asserts the exact rule round 1 shipped and round 2 rejects: a fixture
  # in BATS_TEST_TMPDIR is NOT the canonical index, so the shipped baseline
  # must not be applied to it. The canonical branch is exercised by the E group.
  local n
  for n in 100 101 102 103 104 105 106 107; do api_state "$n" open issue; done
  write_decisions
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | IN-PROGRESS — packet in flight | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| 03 | `c.md` | #102 | IN-PROGRESS — packet in flight | — | — |
| 04 | `d.md` | #103 | IN-PROGRESS — packet in flight | — | — |
| 05 | `e.md` | #104 | IN-PROGRESS — packet in flight | — | — |
| 06 | `f.md` | #105 | IN-PROGRESS — packet in flight | — | — |
| 07 | `g.md` | #106 | IN-PROGRESS — packet in flight | — | — |
| 08 | `h.md` | #107 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

# ==========================================================================
# ROUND 2 — the pinned baseline is CONDITIONAL, and the two checks must stay
# independent.
#
# Round 1 made Check B unconditional. Every synthetic fixture above builds an
# index whose plan ids are whatever that test needs (01/02, 07/09, 03 alone),
# so a baseline pinning 01..08 rejected all of them and 42 cases regressed.
# The checker is legitimately run against non-canonical indices — fixtures,
# copies, a candidate index in a worktree — and on those the pinned id set is
# meaningless. So:
#
#   * PLAN_INDEX_EXPECTED_IDS explicitly set  -> Check B runs against that file
#   * else index resolves to the canonical    -> Check B runs against conf/
#   * else                                    -> Check B is SKIPPED, LOUDLY
#
# "Loudly" is not decoration. A check that silently does not run is the same
# c-001 shape as a check that silently passes; the only difference is where the
# silence lives. And the skip must never rescue Check A, which is what the D/E
# pairs below pin from both sides.
# ==========================================================================

# stderr only — the skip warning is a stderr contract, and merging it into
# stdout would let a "warning" printed into the report body satisfy the test.
run_checker_stderr() {
  run bash -c 'bash "$1" "$2" "$3" 2>&1 1>/dev/null' _ \
      "$BIN" "$BATS_TEST_TMPDIR/00-INDEX.md" "$BATS_TEST_TMPDIR/DECISIONS.md"
}

# Assert $output (captured from stderr) carries the Check-B-skipped warning.
# Matched by meaning, not by one literal sentence: it has to name the thing
# that did not run, say that it did not run, and not read as a verification.
assert_skip_warning() {
  grep -qiE 'pinn|expected id|baseline'            <<<"$output"
  grep -qiE 'skip|not run|did not run|no baseline' <<<"$output"
  grep -qiE 'check a|region|integrity|structur'    <<<"$output"
  ! grep -qiE '\bverified\b'                       <<<"$output"
}

assert_no_skip_warning() {
  ! grep -qiE '(pinn|expected id|baseline).*(skip|not run|did not run)' <<<"$output"
  ! grep -qiE '(skip|did not run).*(pinn|expected id|baseline)'         <<<"$output"
}

# A self-contained fake repo, so the CANONICAL branch can be exercised without
# reading the live plans/00-INDEX.md. Reading the live file would make these
# tests go green the moment the real index is edited — a tautology, not a test.
# REPO_ROOT is derived from the script's own location, so a copy under
# $tmp/bin makes $tmp/plans/00-INDEX.md canonical for that copy.
make_fake_repo() {
  FAKE="$BATS_TEST_TMPDIR/fakerepo"
  mkdir -p "$FAKE/bin" "$FAKE/plans" "$FAKE/conf" "$FAKE/docs"
  cp "$BIN" "$FAKE/bin/check-plan-index-truth.sh"
  chmod +x "$FAKE/bin/check-plan-index-truth.sh"
  FAKE_BIN="$FAKE/bin/check-plan-index-truth.sh"
  cat >"$FAKE/docs/DECISIONS.md" <<'EOF'
# DECISIONS
| # | date | ruling | state | evidence / next |
|---|---|---|---|---|
| 1 | 2026-01-01 | something unrelated | OPEN | nothing |
EOF
}

fake_baseline() {  # ids... -> $FAKE/conf/plan-index-expected-ids.conf
  local id
  { echo '# PINNED BASELINE — never regenerate from plans/00-INDEX.md'
    for id in "$@"; do echo "$id"; done
  } >"$FAKE/conf/plan-index-expected-ids.conf"
}

fake_index() { cat >"$FAKE/plans/00-INDEX.md"; }   # verbatim, line numbers intact

fake_index_table() {  # rows on stdin, wrapped in a well-formed plans table
  { echo '# plans — index'
    echo
    echo '| # | file | issue | status | blocked-by | blocks |'
    echo '|---|---|---|---|---|---|'
    cat
  } >"$FAKE/plans/00-INDEX.md"
}

# No index argument: the checker must resolve its own canonical default.
run_fake() { run bash "$FAKE_BIN" "$@"; }
run_fake_stderr() { run bash -c 'bash "$1" 2>&1 1>/dev/null' _ "$FAKE_BIN"; }

# --------------------------------------------------------------------------
# D — a non-canonical index with no override: Check B skips, and says so
# --------------------------------------------------------------------------

@test "D1 — a fixture whose ids are nowhere near the shipped baseline still passes" {
  # THE round-1 regression, stated as a test. These ids (07, 09) are exactly
  # the shape the older fixtures use; an unconditional 01..08 baseline rejects
  # them and the suite collapses. The index is well formed, so it must pass.
  api_state 107 open issue
  api_state 109 open issue
  write_decisions
  write_index "$(cat <<'EOF'
| 07 | `g.md` | #107 | IN-PROGRESS — packet in flight | — | 09 |
| 09 | `i.md` | #109 | BLOCKED — held behind 07 | 07 | — |
EOF
)"
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "D2 — a single-row fixture with an id the shipped baseline does not carry passes" {
  # Deliberately an id (42) that can never be in conf/. If this goes red the
  # baseline is being applied unconditionally again.
  api_state 142 open issue
  write_decisions
  write_index '| 42 | `z.md` | #142 | IN-PROGRESS — packet in flight | — | — |'
  run_checker
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
}

@test "D3 — the skipped pinned-id check is announced on stderr" {
  # A check that silently does not run is indistinguishable, to a reader of the
  # exit code, from a check that ran and passed. The skip must be visible.
  api_state 107 open issue
  write_decisions
  write_index '| 07 | `g.md` | #107 | IN-PROGRESS — packet in flight | — | — |'
  run_checker_stderr
  [ "$status" -eq 0 ]
  assert_skip_warning
}

@test "D4 — the skip notice never reads as a verification" {
  api_state 107 open issue
  write_decisions
  write_index '| 07 | `g.md` | #107 | IN-PROGRESS — packet in flight | — | — |'
  run_checker_stderr
  [ "$status" -eq 0 ]
  assert_skip_warning
  ! grep -qiE 'OK — every|\bverified\b|all rows accounted' <<<"$output"
}

@test "D5 — Check A still fires on a fixture index with no baseline at all" {
  # The primary reason Check A takes no baseline: a skipped Check B must not
  # leave the row-drop hole open on every non-canonical index.
  api_state 100 closed issue
  write_decisions
  raw_two_row_index '<!--x-->02'
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -Eq "(line|:)[[:space:]]*6([^0-9]|$)" <<<"$output"
  [[ "$output" == *'<!--x-->02'* ]]
  grep -qi 'silent' <<<"$output"
}

@test "D6 — the same fixture also announces that only Check A applied" {
  api_state 100 closed issue
  write_decisions
  raw_two_row_index '<!--x-->02'
  run_checker_stderr
  [ "$status" -eq 2 ]
  assert_skip_warning
}

@test "D7 — a too-short row on a fixture with no baseline is fatal, not skipped" {
  api_state 100 closed issue
  write_decisions
  write_raw_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS |
EOF
  run_checker
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qi 'silent' <<<"$output"
}

@test "D8 — an explicit override on a fixture makes Check B run, and prints no skip notice" {
  api_state 100 closed issue
  api_state 101 open   issue
  write_decisions
  pin_ids 01 02
  write_index "$(cat <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
)"
  run_checker_stderr
  [ "$status" -eq 0 ]
  assert_no_skip_warning
}

# --------------------------------------------------------------------------
# E — the canonical index: Check B is mandatory there
#
# Exercised against a throwaway repo tree rather than the live plans/00-INDEX.md
# on purpose. What is under test is the RESOLUTION rule, not today's content.
# --------------------------------------------------------------------------

@test "E1 — a canonical index matching its shipped baseline passes and skips nothing" {
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 open   issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
  run_fake_stderr
  [ "$status" -eq 0 ]
  assert_no_skip_warning
}

@test "E2 — a canonical index with NO baseline file is FATAL, never a silent skip" {
  # The whole point of pinning: on the canonical index the baseline is not
  # optional. Deleting it must not be a way to switch the check off.
  make_fake_repo
  rm -f "$FAKE/conf/plan-index-expected-ids.conf"
  api_state 100 closed issue
  api_state 101 open   issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qiE 'baseline|expected id' <<<"$output"
}

@test "E3 — a canonical index whose baseline holds no ids is FATAL and says why" {
  make_fake_repo
  { echo '# PINNED BASELINE — never regenerate from plans/00-INDEX.md'
    echo
    echo '   '
  } >"$FAKE/conf/plan-index-expected-ids.conf"
  api_state 100 closed issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qi 'vacuous' <<<"$output"
}

@test "E4 — a row deleted outright from the canonical table is FATAL via Check B" {
  # Check A has nothing to say here: every line left in the region parses
  # perfectly. Only the pinned set knows a row is gone.
  make_fake_repo
  fake_baseline 01 02 03
  api_state 100 closed issue
  api_state 101 open   issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"03"* ]]
}

@test "E5 — a row moved out of the canonical table region is FATAL via Check B" {
  # The subtler deletion: the text is still in the file, so a reviewer skimming
  # the diff sees the row present. It is outside the region, so it is not a row.
  make_fake_repo
  fake_baseline 01 02 03
  api_state 100 closed issue
  api_state 101 open   issue
  api_state 102 open   issue
  fake_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |

parked below the table for now:

| 03 | `c.md` | #102 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"03"* ]]
}

@test "E6 — a duplicated canonical row is FATAL even though the id SET still matches" {
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 open   issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| 02 | `b-copy.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qiE 'duplicat|twice|more than once' <<<"$output"
}

@test "E7 — an id in the canonical table but absent from the baseline is FATAL" {
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 open   issue
  api_state 109 open   issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| 09 | `i.md` | #109 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"09"* ]]
}

@test "E8 — canonicality is decided by the resolved path, not by the string passed in" {
  # Same file, spelled through a parent directory. A string compare would call
  # this a foreign index and skip the pinned check — which is a one-character
  # way to switch Check B off on the real index.
  make_fake_repo
  fake_baseline 01 02 03
  api_state 100 closed issue
  api_state 101 open   issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run bash "$FAKE_BIN" "$FAKE/bin/../plans/00-INDEX.md" "$FAKE/docs/DECISIONS.md"
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"03"* ]]
}

@test "E9 — a copy of the canonical index somewhere else is NOT canonical" {
  # The other direction of E8. A candidate index under review is not the
  # canonical one, so its arbitrary ids must not be graded against conf/ —
  # and the skip has to be announced.
  make_fake_repo
  fake_baseline 01 02 03
  api_state 107 open issue
  mkdir -p "$FAKE/tmp"
  { echo '# plans — index'
    echo
    echo '| # | file | issue | status | blocked-by | blocks |'
    echo '|---|---|---|---|---|---|'
    echo '| 07 | `g.md` | #107 | IN-PROGRESS — packet in flight | — | — |'
  } >"$FAKE/tmp/candidate.md"
  run bash "$FAKE_BIN" "$FAKE/tmp/candidate.md" "$FAKE/docs/DECISIONS.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK — every"* ]]
  run bash -c 'bash "$1" "$2" "$3" 2>&1 1>/dev/null' _ \
      "$FAKE_BIN" "$FAKE/tmp/candidate.md" "$FAKE/docs/DECISIONS.md"
  [ "$status" -eq 0 ]
  assert_skip_warning
}

@test "E10 — an explicit override beats the shipped baseline on the canonical index" {
  # conf/ alone would pass this table. The override names an id that is not
  # there, so the run must fail — proving which file was actually read.
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 open   issue
  pin_ids 01 02 03
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"03"* ]]
}

@test "E11 — an override pointing at nothing is FATAL, never a fallback to conf/" {
  # Falling back would make a typo'd override silently grade against a file the
  # caller did not ask for, and a deliberate override silently ignorable.
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 open   issue
  export PLAN_INDEX_EXPECTED_IDS="$BATS_TEST_TMPDIR/there-is-no-such-baseline.conf"
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -qiE 'baseline|expected id' <<<"$output"
}

@test "E12 — the canonical baseline check runs before any evidence is fetched" {
  make_fake_repo
  fake_baseline 01 02 03
  arm_gh_marker
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [ ! -e "$MARKER" ]
}

# --------------------------------------------------------------------------
# F — THE PROPERTY. The two checks are independent, so neither can be
# laundered using the other.
#
# The founder named this as the likely failure mode of this exact patch: fix
# the region check, then "repair" the baseline until the run goes green, and
# the row-drop hole is open again behind a check that reports clean.
# --------------------------------------------------------------------------

@test "F1 — a perturbed canonical row is FATAL even when the baseline was tuned to hide it" {
  # `03` is perturbed out of the parse AND deleted from the baseline, so the
  # parsed id set and the pinned id set agree exactly: Check B is satisfied.
  # Only Check A can catch this, and it must.
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 open   issue
  fake_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| <!--x-->03 | `c.md` | #102 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -Eq "(line|:)[[:space:]]*7([^0-9]|$)" <<<"$output"
  [[ "$output" == *'<!--x-->03'* ]]
  grep -qi 'silent' <<<"$output"
}

@test "F2 — the same laundering attempt fails for every perturbation shape" {
  # Boundary sweep of F1: each cell defeats the id regex or the field count,
  # and in each case the baseline is pre-tuned to the surviving two rows.
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 open   issue
  local cell
  for cell in '<!--x-->03' '03&nbsp;' '**03.**' '03[^a]' '`03`.' '03 (held)' 'O3'; do
    { echo '# plans — index'
      echo
      echo '| # | file | issue | status | blocked-by | blocks |'
      echo '|---|---|---|---|---|---|'
      echo '| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |'
      echo '| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |'
      printf '| %s | `c.md` | #102 | IN-PROGRESS — packet in flight | — | — |\n' "$cell"
    } >"$FAKE/plans/00-INDEX.md"
    run_fake
    [ "$status" -eq 2 ]
    [[ "$output" != *"OK — every"* ]]
  done
}

@test "F3 — a dropped COLUMN on the canonical index cannot be laundered either" {
  # The other silent skip: NF < 7. The row keeps its id, so a naive Check B
  # that read ids with a looser regex would still see 03 and pass.
  make_fake_repo
  fake_baseline 01 02 03
  api_state 100 closed issue
  api_state 101 open   issue
  fake_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| 03 | `c.md` | #102 | IN-PROGRESS — packet in flight |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  grep -Eq "(line|:)[[:space:]]*7([^0-9]|$)" <<<"$output"
  grep -qi 'silent' <<<"$output"
}

@test "F4 — Check A does not need a baseline to exist at all" {
  # Stated as its own case because it is the load-bearing half of the
  # independence claim: if Check A ever consults the baseline, a canonical run
  # with a deleted conf/ could report the wrong failure, and a fixture run
  # could report none.
  make_fake_repo
  rm -f "$FAKE/conf/plan-index-expected-ids.conf"
  api_state 100 closed issue
  fake_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| <!--x-->02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *'<!--x-->02'* ]]
}

@test "F5 — a dead evidence source does not stand in for the region failure" {
  # Two failures at once must not net out to a pass, and the region failure has
  # to be the one reported: an operator told only "the API is down" reruns the
  # check tomorrow and never learns a row was dropped.
  make_fake_repo
  fake_baseline 01 02
  printf '#!/usr/bin/env bash\necho "gh: dial tcp: lookup api.github.com: no such host" >&2\nexit 1\n' >"$STUB/gh"
  chmod +x "$STUB/gh"
  fake_index <<'EOF'
# plans — index

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
| <!--x-->03 | `c.md` | #102 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *'<!--x-->03'* ]]
}

@test "F6 — a dead evidence source does not stand in for the baseline failure either" {
  make_fake_repo
  fake_baseline 01 02 03
  printf '#!/usr/bin/env bash\necho "gh: Bad credentials (HTTP 401)" >&2\nexit 1\n' >"$STUB/gh"
  chmod +x "$STUB/gh"
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | IN-PROGRESS — packet in flight | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" != *"OK — every"* ]]
  [[ "$output" == *"03"* ]]
}

@test "F7 — an unreachable evidence source is still fatal on a canonical index that satisfies both checks" {
  # MUST NOT REGRESS: neither new check may become a reason to stop caring
  # about the evidence source. Both are satisfied here; the API is dead; the
  # run must still refuse to say OK.
  make_fake_repo
  fake_baseline 01 02
  printf '#!/usr/bin/env bash\necho "gh: dial tcp: lookup api.github.com: no such host" >&2\nexit 1\n' >"$STUB/gh"
  chmod +x "$STUB/gh"
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | BLOCKED — held behind 01; see #101 | — | — |
EOF
  run_fake
  [ "$status" -eq 2 ]
  [[ "$output" == *"THIS RUN DID NOT VERIFY THE INDEX"* ]]
  [[ "$output" != *"OK — every"* ]]
}

@test "F8 — a canonical index that satisfies both new checks can still fail on stale claims" {
  # The last independence direction. Check A and Check B are preconditions, not
  # a verdict: a well-formed, fully-accounted-for table whose claims are stale
  # must still land in the exit-1 lane rather than being waved through.
  make_fake_repo
  fake_baseline 01 02
  api_state 100 closed issue
  api_state 101 closed issue
  fake_index_table <<'EOF'
| 01 | `a.md` | #100 | COMPLETE — PR merged; main green | — | — |
| 02 | `b.md` | #101 | COMPLETE — PR merged; main green | — | 01 |
EOF
  run_fake
  [ "$status" -eq 1 ]
  [[ "$output" == *STALE* ]]
  [[ "$output" != *"OK — every"* ]]
}
