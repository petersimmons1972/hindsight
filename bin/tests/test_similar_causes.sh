#!/usr/bin/env bash
# Attack spec (stage 1) for bin/similar-causes.py.
#
# This suite is committed BEFORE any implementation exists. A later, different
# vendor must make it pass without weakening these assertions.
#
# Contract under test (observable behaviour only — no ranking algorithm pinned):
#
#   bin/similar-causes.py [--corpus DIR] "<free-text description>"
#
#   - Default corpus: pipeline/L1/*.jsonl (repo-relative), field `instance`.
#   - --corpus DIR points at a directory of *.jsonl files (fixtures use this).
#   - Always prints this header on stdout (success path), verbatim:
#       Candidates for human review. This tool does not determine duplication.
#   - Prints at most 10 ranked candidates, each with score and source.
#   - Exit 0 for advisory lookup results (zero or more candidates).
#   - Non-zero ONLY for operational failure: bad usage, empty corpus, unreadable
#     corpus. Finding a similar entry is NEVER an operational failure.
#
# Gate: bash bin/tests/test_similar_causes.sh
#
# CI-17: never read exit status through a pipe.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$ROOT/bin/similar-causes.py"
FIX="$ROOT/bin/tests/fixtures/similar-causes"
CATALOG="$ROOT/catalog/failure-modes.md"
DEFAULT_CORPUS="$ROOT/pipeline/L1"

PASS=0
FAIL=0
RESULTS=()

# ---- helpers ---------------------------------------------------------------

note() { RESULTS+=("$1"); }

pass() {
  PASS=$((PASS + 1))
  note "PASS: $1"
  echo "PASS: $1"
}

fail() {
  FAIL=$((FAIL + 1))
  note "FAIL: $1"
  echo "FAIL: $1" >&2
}

# Run tool; capture stdout/stderr/status without pipes (CI-17).
# Sets: _OUT _ERR _STATUS _COMBINED
run_tool() {
  local outf errf
  outf="$(mktemp)"
  errf="$(mktemp)"
  # Never leave set -e on for callers — this suite must collect every failure.
  set +e
  python3 "$TOOL" "$@" >"$outf" 2>"$errf"
  _STATUS=$?
  _OUT="$(cat "$outf")"
  _ERR="$(cat "$errf")"
  _COMBINED="${_OUT}"$'\n'"${_ERR}"
  rm -f "$outf" "$errf"
  set +e
}

require_tool_present() {
  local name="$1"
  if [[ ! -f "$TOOL" ]]; then
    fail "$name — tool not present at $TOOL (implementation missing; not the assertion under test)"
    return 1
  fi
  if [[ ! -r "$TOOL" ]]; then
    fail "$name — tool unreadable at $TOOL"
    return 1
  fi
  return 0
}

# Refuse to treat "python can't open file" / missing-script noise as an
# operational-failure success. The failure mode we attack is corpus ops, not argv.
assert_not_missing_script_noise() {
  local name="$1"
  local blob="$2"
  if [[ "$blob" == *"can't open file"* ]] || [[ "$blob" == *"No such file or directory"* && "$blob" == *"similar-causes.py"* ]]; then
    fail "$name — exit/output is missing-script noise, not the intended operational failure"
    return 1
  fi
  if [[ "$blob" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — raw Python traceback leaked (must fail loudly with a defined message, not a stack)"
    return 1
  fi
  return 0
}

HEADER='Candidates for human review. This tool does not determine duplication.'

# Verdict / guard language that must never appear (guard-semantics reintroduction).
# Case-insensitive scan of combined streams.
has_forbidden_verdict_language() {
  local blob
  blob="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  # Phrases that assert a duplication decision or rejection action.
  local patterns=(
    'duplicate detected'
    'is a duplicate'
    'are duplicates'
    'duplicates found'
    'already exists in the catalog'
    'already exists in the corpus'
    'rejected as duplicate'
    'rejecting duplicate'
    'refusing entry'
    'refuse entry'
    'entry refused'
    'similarity exceeds threshold'
    'above threshold'
    'below threshold — ok'
    'guard failed'
    'check-duplicate'
    'duplicate-cause'
    'verdict: duplicate'
    'verdict: reject'
    'status: duplicate'
    'status: reject'
    'not accepting'
    'will not accept'
    'blocking add'
    'blocked as duplicate'
  )
  local p
  for p in "${patterns[@]}"; do
    if [[ "$blob" == *"$p"* ]]; then
      return 0
    fi
  done
  return 1
}

sha_tree() {
  # Stable hash of file contents under a path (files only, sorted paths).
  local dir="$1"
  if [[ ! -d "$dir" ]]; then
    echo "MISSING_DIR"
    return
  fi
  # Portable: find + sort + sha256sum of contents list.
  (
    cd "$dir" || exit 0
    find . -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum 2>/dev/null
  ) | sha256sum | awk '{print $1}'
}

sha_file() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "MISSING_FILE"
    return
  fi
  sha256sum "$f" | awk '{print $1}'
}

# Count candidate-ish lines: lines after the header that look like result rows.
# We do not pin row format beyond: score present + source/id present.
# Implementer may use any layout; we count non-empty non-header non-meta lines
# that carry a number (score).
count_scored_candidate_lines() {
  local text="$1"
  local count=0
  local line
  local seen_header=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line// }" ]] && continue
    if [[ "$line" == "$HEADER" ]]; then
      seen_header=1
      continue
    fi
    # Meta/truncation notices are not candidates.
    local low
    low="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    if [[ "$low" == *"more candidate"* ]] || [[ "$low" == *"truncated"* ]] \
      || [[ "$low" == *"showing "*" of "* ]] || [[ "$low" == *"and "*" more"* ]] \
      || [[ "$low" == *"total matches"* ]] || [[ "$low" == *"additional match"* ]]; then
      continue
    fi
    # Candidate rows must include a score (integer or float) somewhere.
    if [[ "$line" =~ [0-9]+([.][0-9]+)? ]]; then
      count=$((count + 1))
    fi
  done <<< "$text"
  echo "$count"
}

has_truncation_notice() {
  local blob
  blob="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  if [[ "$blob" == *"truncated"* ]] || [[ "$blob" == *"more candidate"* ]] \
    || [[ "$blob" == *"showing "*" of "* ]] || [[ "$blob" == *"and "*" more"* ]] \
    || [[ "$blob" == *"total matches"* ]] || [[ "$blob" == *">10"* ]] \
    || [[ "$blob" == *"more than 10"* ]] || [[ "$blob" == *"additional match"* ]] \
    || [[ "$blob" == *"omitted"* ]] || [[ "$blob" == *"remaining"* ]]; then
    return 0
  fi
  return 1
}

# ---- tests -----------------------------------------------------------------

# T01: tool must exist (distinguishes missing-impl from assertion failure).
t01_tool_exists() {
  local name="T01 tool file exists"
  if [[ -f "$TOOL" ]]; then
    pass "$name"
  else
    fail "$name — expected $TOOL (attack spec is red until implementer ships it)"
  fi
}

# T02: advisory header always present on a successful lookup.
t02_header_on_lookup() {
  local name="T02 success path prints exact advisory header"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" "double-claim race when two hosts share a queue"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS on populated corpus lookup (must be 0); err=${_ERR}"
    return
  fi
  if [[ "$_OUT" != *"$HEADER"* ]]; then
    fail "$name — missing exact header on stdout. out=${_OUT}"
    return
  fi
  # Header must appear as its own line (verbatim), not only as a substring of
  # a longer marketing sentence that reintroduces guard tone.
  if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
    fail "$name — header not present as an exact line"
    return
  fi
  pass "$name"
}

# T03: finding a near-exact match still exits 0 (guard regression).
t03_match_still_exit_0() {
  local name="T03 near-match never exits non-zero (no guard rejection)"
  require_tool_present "$name" || return 0
  # Query is nearly identical to tiny-001 instance text.
  run_tool --corpus "$FIX/tiny" \
    "Poller double-claim race when two hosts share a queue label."
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS when similar entry exists (guard semantics reintroduced); err=${_ERR}"
    return
  fi
  pass "$name"
}

# T04: no verdict / rejection language anywhere on a strong match.
t04_no_verdict_language() {
  local name="T04 no duplicate/reject verdict language on strong match"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" \
    "Poller double-claim race when two hosts share a queue label."
  # Language check first so a guard that rejects still fails for the right reason.
  if has_forbidden_verdict_language "$_COMBINED"; then
    fail "$name — forbidden guard/verdict phrasing present: ${_COMBINED}"
    return
  fi
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS on strong match (guard exit without named verdict words); err=${_ERR}"
    return
  fi
  pass "$name"
}

# T05: empty corpus directory → non-zero + says so (not silent zero candidates).
t05_empty_dir_fails_loud() {
  local name="T05 empty corpus dir exits non-zero and names emptiness"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/empty_dir" "anything"
  assert_not_missing_script_noise "$name" "$_COMBINED" || return 0
  if [[ "$_STATUS" -eq 0 ]]; then
    fail "$name — exit 0 on empty corpus (fail-silent: empty load looks like zero hits)"
    return
  fi
  local low
  low="$(printf '%s' "$_COMBINED" | tr '[:upper:]' '[:lower:]')"
  if [[ "$low" != *"empty"* ]] && [[ "$low" != *"no entries"* ]] \
    && [[ "$low" != *"no corpus"* ]] && [[ "$low" != *"0 entries"* ]] \
    && [[ "$low" != *"zero"* ]] && [[ "$low" != *"no jsonl"* ]] \
    && [[ "$low" != *"unreadable"* ]] && [[ "$low" != *"cannot load"* ]] \
    && [[ "$low" != *"failed to load"* ]] && [[ "$low" != *"no files"* ]]; then
    fail "$name — non-zero but message does not indicate empty/unloadable corpus: ${_COMBINED}"
    return
  fi
  pass "$name"
}

# T06: empty jsonl file(s) → non-zero (zero records is empty corpus).
t06_empty_jsonl_fails_loud() {
  local name="T06 empty jsonl corpus exits non-zero and says so"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/empty_jsonl" "anything"
  assert_not_missing_script_noise "$name" "$_COMBINED" || return 0
  if [[ "$_STATUS" -eq 0 ]]; then
    fail "$name — exit 0 when all jsonl files have zero records"
    return
  fi
  local low
  low="$(printf '%s' "$_COMBINED" | tr '[:upper:]' '[:lower:]')"
  if [[ "$low" != *"empty"* ]] && [[ "$low" != *"no entries"* ]] \
    && [[ "$low" != *"no corpus"* ]] && [[ "$low" != *"0 entries"* ]] \
    && [[ "$low" != *"zero"* ]] && [[ "$low" != *"no records"* ]] \
    && [[ "$low" != *"failed to load"* ]] && [[ "$low" != *"cannot load"* ]]; then
    fail "$name — non-zero but does not explain empty corpus: ${_COMBINED}"
    return
  fi
  pass "$name"
}

# T07: unreadable corpus → non-zero + says so.
t07_unreadable_corpus_fails_loud() {
  local name="T07 unreadable corpus exits non-zero and says so"
  require_tool_present "$name" || return 0
  local udir
  udir="$(mktemp -d "$FIX/unreadable.XXXXXX")"
  # Seed a file then lock the directory.
  echo '{"id":"u1","instance":"secret entry"}' >"$udir/x.jsonl"
  chmod 000 "$udir" 2>/dev/null || true
  # Also cover file-unreadable if dir perms are ignored as root (unlikely here).
  if [[ -r "$udir" ]]; then
    chmod 000 "$udir/x.jsonl" 2>/dev/null || true
  fi
  run_tool --corpus "$udir" "secret entry"
  # restore for cleanup
  chmod 755 "$udir" 2>/dev/null || true
  chmod 644 "$udir/x.jsonl" 2>/dev/null || true
  rm -rf "$udir"

  assert_not_missing_script_noise "$name" "$_COMBINED" || return 0
  if [[ "$_STATUS" -eq 0 ]]; then
    fail "$name — exit 0 on unreadable corpus (fail-silent)"
    return
  fi
  local low
  low="$(printf '%s' "$_COMBINED" | tr '[:upper:]' '[:lower:]')"
  if [[ "$low" != *"unreadable"* ]] && [[ "$low" != *"permission"* ]] \
    && [[ "$low" != *"not readable"* ]] && [[ "$low" != *"cannot read"* ]] \
    && [[ "$low" != *"can't read"* ]] && [[ "$low" != *"failed to"* ]] \
    && [[ "$low" != *"error"* ]] && [[ "$low" != *"denied"* ]] \
    && [[ "$low" != *"cannot open"* ]] && [[ "$low" != *"unable"* ]]; then
    fail "$name — non-zero but message does not indicate unreadable corpus: ${_COMBINED}"
    return
  fi
  pass "$name"
}

# T08: zero candidates from a *populated* corpus is exit 0 + header (inverse of T05/T06).
t08_zero_hits_populated_is_ok() {
  local name="T08 zero candidates on populated corpus exits 0 with header"
  require_tool_present "$name" || return 0
  # Query shares no tokens with the fixture body.
  run_tool --corpus "$FIX/zero_score_ok" "zzzz-not-a-token-qqqq-9999-wwww"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS for zero-hit populated lookup; err=${_ERR}"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
    fail "$name — missing exact header on zero-hit path"
    return
  fi
  pass "$name"
}

# T09: missing --corpus path → non-zero operational failure.
t09_missing_corpus_path() {
  local name="T09 missing --corpus path exits non-zero"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/does-not-exist-$$" "query"
  assert_not_missing_script_noise "$name" "$_COMBINED" || return 0
  if [[ "$_STATUS" -eq 0 ]]; then
    fail "$name — exit 0 when corpus path does not exist"
    return
  fi
  pass "$name"
}

# T10: no args → non-zero usage, no traceback.
t10_no_args() {
  local name="T10 no arguments exits non-zero without traceback"
  require_tool_present "$name" || return 0
  run_tool
  assert_not_missing_script_noise "$name" "$_COMBINED" || return 0
  if [[ "$_STATUS" -eq 0 ]]; then
    fail "$name — exit 0 with no query argument"
    return
  fi
  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on bad usage"
    return
  fi
  pass "$name"
}

# T11: empty string query → defined non-zero usage (not crash).
t11_empty_string_query() {
  local name="T11 empty-string query exits non-zero without traceback"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" ""
  assert_not_missing_script_noise "$name" "$_COMBINED" || return 0
  if [[ "$_STATUS" -eq 0 ]]; then
    fail "$name — empty query must be bad usage (non-zero), not a silent lookup"
    return
  fi
  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on empty query"
    return
  fi
  pass "$name"
}

# T12: whitespace-only query → non-zero, no traceback.
t12_whitespace_query() {
  local name="T12 whitespace-only query exits non-zero without traceback"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" "   	  "
  assert_not_missing_script_noise "$name" "$_COMBINED" || return 0
  if [[ "$_STATUS" -eq 0 ]]; then
    fail "$name — whitespace-only query must be bad usage (non-zero)"
    return
  fi
  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on whitespace query"
    return
  fi
  pass "$name"
}

# T13: non-ASCII query does not traceback; advisory exit 0 on populated corpus.
t13_non_ascii() {
  local name="T13 non-ASCII query is defined (no traceback, exit 0)"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" "双重声明 レース 🔥 café résumé"
  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on non-ASCII query"
    return
  fi
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS on valid non-ASCII free text; err=${_ERR}"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
    fail "$name — missing header"
    return
  fi
  pass "$name"
}

# T14: query longer than any corpus entry — no traceback, exit 0.
t14_very_long_query() {
  local name="T14 very long query no traceback, exit 0"
  require_tool_present "$name" || return 0
  local long
  long="$(python3 -c 'print("double-claim race queue label " * 400)')"
  run_tool --corpus "$FIX/tiny" "$long"
  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on long query"
    return
  fi
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS on long query; err=${_ERR}"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
    fail "$name — missing header"
    return
  fi
  pass "$name"
}

# T15: determinism — same argv twice → byte-identical stdout.
t15_determinism() {
  local name="T15 same query twice yields byte-identical stdout"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/ties" "Identical cause text used to pin deterministic tie ordering across runs."
  local s1=$_STATUS o1="$_OUT"
  run_tool --corpus "$FIX/ties" "Identical cause text used to pin deterministic tie ordering across runs."
  local s2=$_STATUS o2="$_OUT"
  if [[ "$s1" -ne 0 || "$s2" -ne 0 ]]; then
    fail "$name — non-zero exit (s1=$s1 s2=$s2)"
    return
  fi
  if [[ "$o1" != "$o2" ]]; then
    fail "$name — stdout differs across identical runs"
    return
  fi
  pass "$name"
}

# T16: never more than 10 candidates printed.
t16_cap_at_ten() {
  local name="T16 never prints more than 10 candidates"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/many_matches" \
    "Silent truncation of candidate list advisory lookup overflow test token XQZ9"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -gt 10 ]]; then
    fail "$name — printed $n scored candidate lines (cap is 10)"
    return
  fi
  if [[ "$n" -lt 1 ]]; then
    # Fixture is constructed so any non-trivial ranker returns hits; zero is
    # either a broken ranker that scores everything 0 (then cap is moot) or
    # a silent drop. Require at least one hit for this distinctive token set.
    fail "$name — expected scored candidates for distinctive many_matches query, got $n"
    return
  fi
  pass "$name"
}

# T17: if more than 10 would match, truncation is disclosed (not silent).
t17_truncation_disclosed() {
  local name="T17 >10 matches discloses truncation (not silent top-10)"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/many_matches" \
    "Silent truncation of candidate list advisory lookup overflow test token XQZ9"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -gt 10 ]]; then
    fail "$name — printed $n lines (cap broken); truncation notice irrelevant"
    return
  fi
  # 15 near-identical entries: a score>0 policy that returns fewer than 10
  # still must not pretend the corpus had only those. We require either a
  # truncation notice OR an explicit total/count that is > printed.
  if ! has_truncation_notice "$_COMBINED"; then
    fail "$name — no truncation/total disclosure when many_matches has 15 near-identical hits. out=${_OUT}"
    return
  fi
  pass "$name"
}

# T18: each printed candidate includes a score and a source reference.
t18_score_and_source() {
  local name="T18 candidates include score and source"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" "double-claim race two hosts queue label"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -lt 1 ]]; then
    fail "$name — no scored candidates for a near-match query against tiny corpus"
    return
  fi
  # Source: expect at least one of id / path / jsonl filename markers.
  local low
  low="$(printf '%s' "$_OUT" | tr '[:upper:]' '[:lower:]')"
  if [[ "$low" != *"tiny-"* ]] && [[ "$low" != *"alpha.jsonl"* ]] \
    && [[ "$low" != *"beta.jsonl"* ]] && [[ "$low" != *"source"* ]] \
    && [[ "$low" != *"alpha.md"* ]] && [[ "$low" != *".jsonl"* ]]; then
    fail "$name — candidates lack a visible source/id reference: ${_OUT}"
    return
  fi
  pass "$name"
}

# T19: read-only — default corpus + catalog hashes unchanged after a run.
t19_readonly_default_corpus() {
  local name="T19 read-only: pipeline/L1 and catalog hashes unchanged"
  require_tool_present "$name" || return 0
  if [[ ! -d "$DEFAULT_CORPUS" ]]; then
    fail "$name — default corpus missing at $DEFAULT_CORPUS"
    return
  fi
  local h_l1_before h_cat_before h_l1_after h_cat_after
  h_l1_before="$(sha_tree "$DEFAULT_CORPUS")"
  h_cat_before="$(sha_file "$CATALOG")"
  run_tool "fail-silent gate that reports pass when a check never ran"
  h_l1_after="$(sha_tree "$DEFAULT_CORPUS")"
  h_cat_after="$(sha_file "$CATALOG")"
  if [[ "$h_l1_before" != "$h_l1_after" ]]; then
    fail "$name — pipeline/L1 content hash changed ($h_l1_before -> $h_l1_after)"
    return
  fi
  if [[ "$h_cat_before" != "$h_cat_after" ]]; then
    fail "$name — catalog/failure-modes.md hash changed"
    return
  fi
  # Also require the tool actually ran against default corpus (exit 0 or
  # operational — either is fine for the hash check, but traceback is not).
  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on default-corpus run"
    return
  fi
  pass "$name"
}

# T20: fixture corpus also unmodified (hash) after run.
t20_readonly_fixture() {
  local name="T20 read-only: --corpus fixture tree unmodified"
  require_tool_present "$name" || return 0
  local before after
  before="$(sha_tree "$FIX/tiny")"
  run_tool --corpus "$FIX/tiny" "health check reports healthy dependency down"
  after="$(sha_tree "$FIX/tiny")"
  if [[ "$before" != "$after" ]]; then
    fail "$name — fixture corpus mutated"
    return
  fi
  pass "$name"
}

# T21: threshold / --reject / --check-duplicate style flags must not reintroduce
# guard exits. Unknown flags may be usage errors; accepted flags must not reject.
t21_threshold_flag_cannot_reject() {
  local name="T21 threshold/reject flags cannot force non-zero on match"
  require_tool_present "$name" || return 0
  # Common sneaks under pressure to "just make it a gate again".
  local flags=(
    "--threshold=0.01"
    "--min-score=0.01"
    "--reject-above=0.01"
    "--check-duplicate"
    "--check-duplicate-cause"
    "--fail-on-match"
    "--guard"
  )
  local f
  for f in "${flags[@]}"; do
    run_tool --corpus "$FIX/tiny" "$f" \
      "Poller double-claim race when two hosts share a queue label."
    # Verdict language is never allowed, with or without the advisory header.
    if has_forbidden_verdict_language "$_COMBINED"; then
      fail "$name — $f produced verdict/reject language: ${_COMBINED}"
      return
    fi
    if [[ "$_STATUS" -ne 0 ]]; then
      local low
      low="$(printf '%s' "$_COMBINED" | tr '[:upper:]' '[:lower:]')"
      # Usage / unknown-flag errors are the only permitted non-zero here.
      if [[ "$low" == *"usage"* ]] || [[ "$low" == *"unknown"* ]] \
        || [[ "$low" == *"unrecognized"* ]] || [[ "$low" == *"invalid option"* ]] \
        || [[ "$low" == *"not recognized"* ]] || [[ "$low" == *"unexpected argument"* ]] \
        || [[ "$low" == *"unrecognized arguments"* ]] || [[ "$low" == *"error: argument"* ]]; then
        continue
      fi
      fail "$name — $f caused exit $_STATUS on a match without a usage error (guard sneak): ${_COMBINED}"
      return
    fi
  done
  pass "$name"
}

# T22: scores, when multiple candidates appear, are non-increasing.
t22_scores_non_increasing() {
  local name="T22 candidate scores are non-increasing"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/many_matches" \
    "Silent truncation of candidate list advisory lookup overflow test token XQZ9"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  # Extract first floating/int token per scored candidate line; verify order.
  local prev="" line score
  local checked=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line// }" ]] && continue
    [[ "$line" == "$HEADER" ]] && continue
    local low
    low="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    if [[ "$low" == *"truncated"* ]] || [[ "$low" == *"more candidate"* ]] \
      || [[ "$low" == *"showing "*" of "* ]] || [[ "$low" == *"and "*" more"* ]]; then
      continue
    fi
    if [[ "$line" =~ ([0-9]+\.[0-9]+|[0-9]+) ]]; then
      score="${BASH_REMATCH[1]}"
      if [[ -n "$prev" ]]; then
        # awk for float compare
        if ! awk -v a="$prev" -v b="$score" 'BEGIN { exit !(a+0 >= b+0) }'; then
          fail "$name — score order $prev then $score (not non-increasing)"
          return
        fi
      fi
      prev="$score"
      checked=$((checked + 1))
    fi
  done <<< "$_OUT"
  if [[ "$checked" -lt 2 ]]; then
    fail "$name — need ≥2 scored candidates to test order, got $checked"
    return
  fi
  pass "$name"
}

# T23: malformed JSONL must not produce a bare traceback; either skip-bad-lines
# with exit 0 + header, or operational non-zero naming the parse error.
t23_malformed_no_traceback() {
  local name="T23 malformed JSONL: no traceback; defined outcome"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/malformed" "credential leakage in argv"
  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — raw traceback on malformed line"
    return
  fi
  if [[ "$_STATUS" -eq 0 ]]; then
    if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
      fail "$name — exit 0 but missing header after partial parse"
      return
    fi
  else
    # Operational failure path: must mention parse/json/invalid/malformed.
    local low
    low="$(printf '%s' "$_COMBINED" | tr '[:upper:]' '[:lower:]')"
    if [[ "$low" != *"parse"* ]] && [[ "$low" != *"json"* ]] \
      && [[ "$low" != *"invalid"* ]] && [[ "$low" != *"malformed"* ]] \
      && [[ "$low" != *"decode"* ]] && [[ "$low" != *"error"* ]]; then
      fail "$name — non-zero without parse-related message: ${_COMBINED}"
      return
    fi
  fi
  pass "$name"
}

# T24: header is unconditional even when candidates are printed (not only on empty).
t24_header_with_candidates() {
  local name="T24 header present even when candidates are listed"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" "Exit status read through a pipe reports the last command"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
    fail "$name — header missing when candidates expected"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -lt 1 ]]; then
    fail "$name — expected at least one candidate for near-exact pipe-status query"
    return
  fi
  pass "$name"
}

# T25: --corpus is part of the contract (required for fixtures / testability).
t25_corpus_flag_required_contract() {
  local name="T25 --corpus flag selects fixture over default L1"
  require_tool_present "$name" || return 0
  # Distinctive tiny-only content must surface when --corpus=tiny.
  run_tool --corpus "$FIX/tiny" "health check reports healthy while the dependency is down"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — --corpus rejected or failed: status=$_STATUS err=${_ERR}"
    return
  fi
  local low
  low="$(printf '%s' "$_OUT" | tr '[:upper:]' '[:lower:]')"
  if [[ "$low" != *"tiny-003"* ]] && [[ "$low" != *"health check"* ]] \
    && [[ "$low" != *"localhost"* ]] && [[ "$low" != *"beta.jsonl"* ]] \
    && [[ "$low" != *"dependency"* ]]; then
    fail "$name — output does not reflect tiny fixture content (flag ignored?): ${_OUT}"
    return
  fi
  pass "$name"
}

# T26: exit code 0 with candidates does not write "ERROR" as a success marker
# (structured status agrees with exit — CI-1).
t26_exit_agrees_with_status_words() {
  local name="T26 exit 0 path does not print error/fail status words"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/tiny" "double-claim race when two hosts share a queue"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — expected exit 0; got $_STATUS"
    return
  fi
  local low
  low="$(printf '%s' "$_COMBINED" | tr '[:upper:]' '[:lower:]')"
  # Allow the advisory header; forbid status-shaped failure markers on success.
  if [[ "$low" == *"error:"* ]] || [[ "$low" == *"[error]"* ]] \
    || [[ "$low" == *"status: fail"* ]] || [[ "$low" == *"status: error"* ]] \
    || [[ "$low" == *"exit code 1"* ]] || [[ "$low" == *"failed with"* ]]; then
    fail "$name — success path carries error/fail status language: ${_COMBINED}"
    return
  fi
  pass "$name"
}

# T27: does not create new files under repo root / fixture / L1 during run.
t27_no_sidecar_writes() {
  local name="T27 no new sidecar files under fixture or L1"
  require_tool_present "$name" || return 0
  local marker
  marker="$(mktemp "$ROOT/bin/tests/fixtures/similar-causes/.pre.XXXXXX")"
  # Snapshot file lists.
  local list_before list_after
  list_before="$(find "$FIX/tiny" "$DEFAULT_CORPUS" -type f 2>/dev/null | sort)"
  run_tool --corpus "$FIX/tiny" "double-claim"
  list_after="$(find "$FIX/tiny" "$DEFAULT_CORPUS" -type f 2>/dev/null | sort)"
  rm -f "$marker"
  if [[ "$list_before" != "$list_after" ]]; then
    fail "$name — file set under tiny/L1 changed during run"
    return
  fi
  pass "$name"
}

# ---- runner ----------------------------------------------------------------

main() {
  echo "=== similar-causes attack spec ==="
  echo "ROOT=$ROOT"
  echo "TOOL=$TOOL (exists=$([[ -f $TOOL ]] && echo yes || echo NO))"
  echo

  set +e
  t01_tool_exists
  t02_header_on_lookup
  t03_match_still_exit_0
  t04_no_verdict_language
  t05_empty_dir_fails_loud
  t06_empty_jsonl_fails_loud
  t07_unreadable_corpus_fails_loud
  t08_zero_hits_populated_is_ok
  t09_missing_corpus_path
  t10_no_args
  t11_empty_string_query
  t12_whitespace_query
  t13_non_ascii
  t14_very_long_query
  t15_determinism
  t16_cap_at_ten
  t17_truncation_disclosed
  t18_score_and_source
  t19_readonly_default_corpus
  t20_readonly_fixture
  t21_threshold_flag_cannot_reject
  t22_scores_non_increasing
  t23_malformed_no_traceback
  t24_header_with_candidates
  t25_corpus_flag_required_contract
  t26_exit_agrees_with_status_words
  t27_no_sidecar_writes
  set -e

  echo
  echo "=== summary: $PASS passed, $FAIL failed (of $((PASS + FAIL))) ==="
  if [[ "$FAIL" -gt 0 ]]; then
    exit 1
  fi
  exit 0
}

main "$@"
