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
#   - Exit status must not distinguish match from no-match under any encoding,
#     corpus content (e.g. surrogates), or downstream pipe (e.g. | head).
#   - Default corpus path (no --corpus) is a first-class success path: known
#     matches exit 0, print the header, and print candidate rows.
#   - Corpus fields (id/source/instance) are single-line on stdout; control
#     characters (ANSI) must not erase tool-authored structure in a terminal.
#   - No row-level verdict/guard structure (bare DUPLICATE/REJECT/DO NOT ADD
#     prefixes); language check is structural, not a closed phrase list.
#   - Partial corpus load (skipped unparseable lines, BOM-dropped records)
#     must report loaded/skipped counts — silence is not a defined outcome.
#   - Cap is exactly 10 when >10 match; truncation notice numbers must be true
#     (shown == rows printed, total == positive-score count).
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

# Normalize a line to lowercase alphanumeric tokens separated by spaces.
_norm_tokens() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/ /g; s/  */ /g; s/^ //; s/ $//'
}

# Whole-token verdict/guard language (structural — not an enumerable phrase list).
# Matches bare DUPLICATE / REJECT / DO NOT ADD etc. that a fixed multi-word blocklist misses.
_tokens_have_verdict_language() {
  local norm="$1"
  # Multi-word structural forms first.
  if [[ "$norm" == *"do not add"* ]] || [[ "$norm" == *"not accepting"* ]] \
    || [[ "$norm" == *"will not accept"* ]] || [[ "$norm" == *"already exists"* ]]; then
    return 0
  fi
  local tok
  for tok in $norm; do
    case "$tok" in
      duplicate|duplicates|reject|rejected|rejecting|rejection|refuse|refused|refusing|refusal|refusing)
        return 0
        ;;
    esac
  done
  return 1
}

# True if a single output line is a truncation / meta notice (not a candidate row).
_is_meta_line() {
  local low
  low="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  if [[ "$low" == *"more candidate"* ]] || [[ "$low" == *"truncated"* ]] \
    || [[ "$low" == *"showing "*" of "* ]] || [[ "$low" == *"and "*" more"* ]] \
    || [[ "$low" == *"total matches"* ]] || [[ "$low" == *"additional match"* ]] \
    || [[ "$low" == *"omitted"* ]] || [[ "$low" == *"remaining"* ]]; then
    return 0
  fi
  return 1
}

# Verdict / guard language that must never appear as *tool structure*.
#
# Structural (not a closed phrase list):
#   - multi-word legacy phrases (kept; they still catch clear verdicts)
#   - bare tokens DUPLICATE/REJECT/REFUSE/… on any non-header, non-instance-
#     field text (row prefixes like "DUPLICATE - DO NOT ADD | 1.000 | …",
#     forged VERDICT: lines, id/source columns)
#   - lines that are not header/meta/candidate-shaped are fully scanned
#
# Instance text (last field of a well-formed candidate row) is corpus data and
# may legally contain the word "duplicate"; only tool-owned columns are gated.
has_forbidden_verdict_language() {
  local blob="$1"
  local blob_low line low norm owned

  blob_low="$(printf '%s' "$blob" | tr '[:upper:]' '[:lower:]')"
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
    if [[ "$blob_low" == *"$p"* ]]; then
      return 0
    fi
  done

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line// }" ]] && continue
    [[ "$line" == "$HEADER" ]] && continue
    if _is_meta_line "$line"; then
      continue
    fi
    low="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    # Explicit verdict/status markers on a line are always tool structure.
    if [[ "$low" == verdict:* ]] || [[ "$low" == status:* ]] \
      || [[ "$low" == *" verdict:"* ]] || [[ "$low" == rejected:* ]]; then
      return 0
    fi
    # Well-formed candidate: SCORE | ID | source: SRC | INSTANCE
    # Only tool-owned columns (id, source) are scanned for bare tokens.
    if [[ "$line" =~ ^[0-9]+([.][0-9]+)?[[:space:]]*\|[[:space:]]*([^|]+)\|[[:space:]]*(source:[[:space:]]*[^|]+)\|[[:space:]]*(.*)$ ]]; then
      owned="$(printf '%s %s' "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}")"
      norm="$(_norm_tokens "$owned")"
      if _tokens_have_verdict_language "$norm"; then
        return 0
      fi
      # Leading score field is numeric — never a DUPLICATE prefix. Good.
      continue
    fi
    # Non-candidate line (row prefix, forged free text, broken multi-line field):
    # full structural token scan — this is what kills "DUPLICATE - DO NOT ADD | …".
    norm="$(_norm_tokens "$line")"
    if _tokens_have_verdict_language "$norm"; then
      return 0
    fi
  done <<< "$blob"
  return 1
}

# Minimal ANSI screen model: ESC[2J (erase display) and ESC[H / ESC[;H (cursor
# home) clear the buffer. Used to assert what a terminal actually shows, which
# grep -Fxq on the raw byte stream cannot see.
terminal_render() {
  python3 -c '
import sys
text = sys.stdin.read()
buf = []
i = 0
n = len(text)
while i < n:
    if text[i] == "\x1b" and i + 1 < n and text[i + 1] == "[":
        j = i + 2
        while j < n and not (text[j].isalpha() or text[j] == "@"):
            j += 1
        if j < n:
            cmd = text[j]
            params = text[i + 2 : j]
            if cmd == "J" and params in ("2", "3", ""):
                buf = []
            elif cmd == "H":
                buf = []
            i = j + 1
            continue
    buf.append(text[i])
    i += 1
sys.stdout.write("".join(buf))
' <<< "$1"
}

# Assert no tool-owned field may introduce a line break: every non-empty stdout
# line must be the header, a meta/truncation notice, or a single-line candidate.
# Returns 0 if structure holds; 1 otherwise (reason on stdout for fail msgs).
check_single_line_fields() {
  local text="$1"
  local line bad=0
  local candidates=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line// }" ]] && continue
    if [[ "$line" == "$HEADER" ]]; then
      continue
    fi
    if _is_meta_line "$line"; then
      continue
    fi
    if [[ "$line" == *$'\x1b'* ]]; then
      echo "ANSI/control escape in output line"
      bad=1
      break
    fi
    if [[ ! "$line" =~ ^[0-9]+([.][0-9]+)?[[:space:]]*\| ]]; then
      echo "non-header line is not a scored candidate (field newline or forge): ${line:0:120}"
      bad=1
      break
    fi
    # Candidate rows must be exactly one record: score | id | source: … | instance
    # with no additional raw newlines already handled by line iteration.
    if [[ ! "$line" =~ ^[0-9]+([.][0-9]+)?[[:space:]]*\|[[:space:]]*[^|]+[[:space:]]*\|[[:space:]]*source:[[:space:]]*[^|]+[[:space:]]*\|[[:space:]]*.+$ ]]; then
      echo "candidate row missing required single-line fields: ${line:0:120}"
      bad=1
      break
    fi
    candidates=$((candidates + 1))
  done <<< "$text"
  if [[ "$bad" -ne 0 ]]; then
    return 1
  fi
  if [[ "$candidates" -gt 10 ]]; then
    echo "scored candidate lines exceed cap of 10: $candidates"
    return 1
  fi
  return 0
}

# Parse "Showing X of Y" (or equivalent) from blob; sets _SHOWN _TOTAL or returns 1.
parse_truncation_counts() {
  local blob="$1"
  _SHOWN=""
  _TOTAL=""
  local line low
  while IFS= read -r line || [[ -n "$line" ]]; do
    low="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    # Showing N of M candidates.
    if [[ "$low" =~ showing[[:space:]]+([0-9]+)[[:space:]]+of[[:space:]]+([0-9]+) ]]; then
      _SHOWN="${BASH_REMATCH[1]}"
      _TOTAL="${BASH_REMATCH[2]}"
      return 0
    fi
  done <<< "$blob"
  return 1
}

# Stderr (or combined) must disclose load/skip counts when records were skipped.
# Accepts flexible phrasing as long as both a loaded count and a skipped count appear.
has_load_skip_report() {
  local blob
  blob="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  # Must mention skip/drop/ignore AND a load/parse/record count of some form.
  local has_skip=0 has_load=0
  if [[ "$blob" == *"skip"* ]] || [[ "$blob" == *"skipped"* ]] \
    || [[ "$blob" == *"drop"* ]] || [[ "$blob" == *"dropped"* ]] \
    || [[ "$blob" == *"ignor"* ]] || [[ "$blob" == *"unparseable"* ]] \
    || [[ "$blob" == *"malformed"* ]] || [[ "$blob" == *"invalid"* ]]; then
    has_skip=1
  fi
  if [[ "$blob" == *"load"* ]] || [[ "$blob" == *"loaded"* ]] \
    || [[ "$blob" == *"record"* ]] || [[ "$blob" == *"entries"* ]] \
    || [[ "$blob" == *"entry"* ]] || [[ "$blob" == *"parsed"* ]] \
    || [[ "$blob" == *"usable"* ]]; then
    has_load=1
  fi
  # Also accept a compact "N loaded, M skipped" style with two integers near skip words.
  if [[ "$has_skip" -eq 1 && "$has_load" -eq 1 ]]; then
    # Prefer a form that includes at least one digit (a count).
    if [[ "$blob" =~ [0-9] ]]; then
      return 0
    fi
  fi
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

# T16: pin the cap at exactly 10 for many_matches (15 positive-score entries).
# A mutant with MAX_CANDIDATES=2 or 9 previously survived "1 ≤ n ≤ 10".
t16_cap_at_ten() {
  local name="T16 prints exactly 10 candidates when >10 match"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/many_matches" \
    "Silent truncation of candidate list advisory lookup overflow test token XQZ9"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -ne 10 ]]; then
    fail "$name — printed $n scored candidate lines (cap must be exactly 10 for this 15-hit fixture)"
    return
  fi
  pass "$name"
}

# T17: truncation notice must disclose the true total (15) and shown (10).
# A mutant hardcoding "Showing 10 of 10 candidates." previously survived.
t17_truncation_disclosed() {
  local name="T17 truncation notice discloses correct shown/total (10 of 15)"
  require_tool_present "$name" || return 0
  run_tool --corpus "$FIX/many_matches" \
    "Silent truncation of candidate list advisory lookup overflow test token XQZ9"
  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -ne 10 ]]; then
    fail "$name — printed $n lines (need exactly 10 before trusting notice)"
    return
  fi
  if ! parse_truncation_counts "$_COMBINED"; then
    fail "$name — no parseable 'Showing N of M' truncation notice. out=${_OUT}"
    return
  fi
  if [[ "$_SHOWN" -ne 10 ]]; then
    fail "$name — notice shown=$_SHOWN (want 10)"
    return
  fi
  if [[ "$_TOTAL" -ne 15 ]]; then
    fail "$name — notice total=$_TOTAL (want 15, the true positive-score count)"
    return
  fi
  if [[ "$_SHOWN" -ge "$_TOTAL" ]]; then
    fail "$name — notice claims shown ($_SHOWN) >= total ($_TOTAL); not a real truncation"
    return
  fi
  if [[ "$_SHOWN" -ne "$n" ]]; then
    fail "$name — notice shown=$_SHOWN disagrees with printed scored rows=$n"
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

# T23: malformed JSONL must not produce a bare traceback.
# Skip-bad-lines is allowed only when the skip is *audible*: a load/skip count
# must appear (stderr or stdout). Silent partial load is the defect — not the skip.
t23_malformed_no_traceback() {
  local name="T23 malformed JSONL: no traceback; skip must be reported"
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
    # Fixture has 1 garbage line + 1 good record → at least one skip occurred.
    if ! has_load_skip_report "$_COMBINED"; then
      fail "$name — skipped unparseable line(s) with no loaded/skipped count (silent partial load). err=${_ERR}"
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

# ---- stage-1b hardening (holes from stage-3 DEFECTIVE verifiers) ------------
#
# Property under test for exit-status oracles (hole 1): no invocation may
# distinguish "match found" from "no match" by exit status, under any encoding,
# corpus content, or downstream pipe. Concrete probes below are instances of
# that property — not an exhaustive list of mechanisms.

# T28 (hole 1): PYTHONIOENCODING=ascii + em-dash corpus → match must still exit 0.
# Current impl: UnicodeEncodeError on match → exit 1; no-match → exit 0 (oracle).
t28_ascii_encoding_exit_not_match_oracle() {
  local name="T28 exit status must not discriminate match under PYTHONIOENCODING=ascii"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/emdash.XXXXXX")"
  printf '%s\n' \
    '{"id":"em-1","instance":"Poller double-claim race — two hosts share a queue label.","source_path":"e.md"}' \
    >"$cdir/a.jsonl"

  local outf errf st_match st_nomatch
  outf="$(mktemp)"; errf="$(mktemp)"
  set +e
  PYTHONIOENCODING=ascii python3 "$TOOL" --corpus "$cdir" \
    "Poller double-claim race two hosts share a queue label" >"$outf" 2>"$errf"
  st_match=$?
  local out_match err_match
  out_match="$(cat "$outf")"; err_match="$(cat "$errf")"
  PYTHONIOENCODING=ascii python3 "$TOOL" --corpus "$cdir" \
    "zzzqqq xylophone wombat qqqzzz" >"$outf" 2>"$errf"
  st_nomatch=$?
  local out_nomatch
  out_nomatch="$(cat "$outf")"
  rm -f "$outf" "$errf"
  rm -rf "$cdir"

  if [[ "$st_match" -ne "$st_nomatch" ]]; then
    fail "$name — match exit=$st_match != no-match exit=$st_nomatch (exit-status oracle). match_err=${err_match}"
    return
  fi
  if [[ "$st_match" -ne 0 || "$st_nomatch" -ne 0 ]]; then
    fail "$name — valid lookup must exit 0 for match and no-match (got $st_match / $st_nomatch). err=${err_match}"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$out_match" || ! grep -Fxq "$HEADER" <<<"$out_nomatch"; then
    fail "$name — missing advisory header under ascii codec"
    return
  fi
  pass "$name"
}

# T29 (hole 1): | head -1 must not yield exit 120 on match and 0 on no-match.
# BrokenPipeError handler at shutdown is dead code; CPython exits 120 on flush.
t29_pipe_head_exit_not_match_oracle() {
  local name="T29 piped-to-head exit status must not discriminate match from no-match"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/pipebig.XXXXXX")"
  # ~17KB+ of match output so head -1 closes the pipe before Python finishes.
  python3 - "$cdir" <<'PY'
import sys
from pathlib import Path
d = Path(sys.argv[1])
body = ("Poller double-claim race queue label hosts share " + ("x" * 800) + " ") * 3
for i in range(15):
    (d / f"r{i}.jsonl").write_text(
        f'{{"id":"b{i}","instance":"{body} {i}","source_path":"s{i}.md"}}\n',
        encoding="utf-8",
    )
PY

  local st_match st_nomatch
  set +e
  python3 "$TOOL" --corpus "$cdir" \
    "Poller double-claim race queue label hosts share" 2>/dev/null \
    | head -1 >/dev/null
  st_match=${PIPESTATUS[0]}
  python3 "$TOOL" --corpus "$cdir" \
    "zzzqqq xylophone wombat qqqzzz" 2>/dev/null \
    | head -1 >/dev/null
  st_nomatch=${PIPESTATUS[0]}
  rm -rf "$cdir"

  if [[ "$st_match" -ne "$st_nomatch" ]]; then
    fail "$name — match pipe exit=$st_match != no-match pipe exit=$st_nomatch (head-pipe oracle)"
    return
  fi
  if [[ "$st_match" -ne 0 || "$st_nomatch" -ne 0 ]]; then
    fail "$name — both piped lookups must exit 0 (got match=$st_match nomatch=$st_nomatch)"
    return
  fi
  pass "$name"
}

# T30 (hole 1): lone surrogate in instance (legal JSON) must not make match exit 1
# while no-match exits 0 — same exit-status oracle, no env var required.
t30_surrogate_exit_not_match_oracle() {
  local name="T30 surrogate in corpus must not make match exit differ from no-match"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/surr.XXXXXX")"
  # JSON \ud800 is accepted by json.loads; encoding to utf-8 stdout then fails.
  printf '%s\n' \
    '{"id":"s1","instance":"queue race poller \ud800 hosts share","source_path":"a.md"}' \
    >"$cdir/a.jsonl"

  local outf errf st_match st_nomatch
  outf="$(mktemp)"; errf="$(mktemp)"
  set +e
  python3 "$TOOL" --corpus "$cdir" "queue race poller hosts share" >"$outf" 2>"$errf"
  st_match=$?
  local err_match
  err_match="$(cat "$errf")"
  python3 "$TOOL" --corpus "$cdir" "zzzqqq xylophone wombat qqqzzz" >"$outf" 2>"$errf"
  st_nomatch=$?
  rm -f "$outf" "$errf"
  rm -rf "$cdir"

  if [[ "$st_match" -ne "$st_nomatch" ]]; then
    fail "$name — match exit=$st_match != no-match exit=$st_nomatch (surrogate oracle). err=${err_match}"
    return
  fi
  if [[ "$st_match" -ne 0 || "$st_nomatch" -ne 0 ]]; then
    fail "$name — both must exit 0 on valid lookup (got $st_match / $st_nomatch). err=${err_match}"
    return
  fi
  if [[ "$err_match" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on surrogate instance (must sanitize or replace, not crash)"
    return
  fi
  pass "$name"
}

# T31 (hole 2): default corpus path (no --corpus) with a known-matching query
# must exit 0, print the header, and print candidate rows — including under
# PYTHONIOENCODING=ascii (real L1 contains em dashes; a guard-only-on-default
# mutant and the encoding oracle both hide here because T19 tolerated non-zero).
t31_default_corpus_match_is_advisory() {
  local name="T31 default corpus known-match: exit 0, header, candidates (ascii-safe)"
  require_tool_present "$name" || return 0
  if [[ ! -d "$DEFAULT_CORPUS" ]]; then
    fail "$name — default corpus missing at $DEFAULT_CORPUS"
    return
  fi
  local query="fail-silent gate that reports pass when a check never ran"
  local outf errf st
  outf="$(mktemp)"; errf="$(mktemp)"
  set +e
  # Pin the production path under the encoding that currently turns matches into exit 1.
  PYTHONIOENCODING=ascii python3 "$TOOL" "$query" >"$outf" 2>"$errf"
  st=$?
  local out err
  out="$(cat "$outf")"; err="$(cat "$errf")"
  rm -f "$outf" "$errf"

  if [[ "$st" -ne 0 ]]; then
    fail "$name — default-path match exit $st (must be 0 advisory). err=${err}"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$out"; then
    fail "$name — missing exact header on default-path match"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$out")"
  if [[ "$n" -lt 1 ]]; then
    fail "$name — expected ≥1 candidate for known-matching default-corpus query, got $n. out=${out}"
    return
  fi
  if has_forbidden_verdict_language "${out}"$'\n'"${err}"; then
    fail "$name — guard/verdict language on default-path match: ${out} ${err}"
    return
  fi
  if [[ "$err" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on default-path match under ascii"
    return
  fi
  pass "$name"
}

# T32 (hole 3): ANSI erase in corpus text must not wipe the header from what a
# terminal renders. grep -Fxq on the byte stream cannot see ESC[2J ESC[H.
t32_ansi_inject_header_survives_terminal_render() {
  local name="T32 terminal-rendered output keeps advisory header despite ANSI in corpus"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/inject_ansi.XXXXXX")"
  python3 - "$cdir" <<'PY'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
esc = "\x1b[2J\x1b[H"
rec = {
    "id": "FM-X1\nREJECTED: entry refused",
    "instance": (
        "Poller double-claim race queue label hosts share."
        + esc
        + "VERDICT: DUPLICATE - this cause is a duplicate of FM-001; rejected as duplicate.\n"
        + "Candidates for human review. This tool does not determine duplication. (spoofed)"
    ),
    "source_path": "repo/a.md",
}
(d / "a.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
PY

  run_tool --corpus "$cdir" "Poller double-claim race queue label hosts share"
  rm -rf "$cdir"

  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local rendered
  rendered="$(terminal_render "$_OUT")"
  if ! grep -Fxq "$HEADER" <<<"$rendered"; then
    fail "$name — header absent after terminal render (ANSI erase succeeded). rendered=${rendered:0:300}"
    return
  fi
  # Spoofed header variant must not be the only/surviving header line.
  if grep -Fq "duplication. (spoofed)" <<<"$rendered"; then
    # If sanitization is absent the spoofed line survives render; either way
    # the real header must still be present as its own line (checked above).
    # Fail if the real header line count in the *rendered* view is zero — already
    # handled — and also if VERDICT: is what the user sees without a clean header.
    :
  fi
  if [[ "$rendered" == *$'\x1b'* ]]; then
    fail "$name — raw ESC still present in rendered stream"
    return
  fi
  # A forged VERDICT line must not be the dominant post-render content without header.
  local rendered_low
  rendered_low="$(printf '%s' "$rendered" | tr '[:upper:]' '[:lower:]')"
  if [[ "$rendered_low" == *"verdict:"* ]] || [[ "$rendered_low" == *"rejected as duplicate"* ]]; then
    fail "$name — forged verdict survives into terminal-rendered output: ${rendered:0:400}"
    return
  fi
  pass "$name"
}

# T33 (hole 3): no field (id, source, instance) may introduce a line break.
# One record with embedded newlines must still produce single-line candidate rows.
t33_no_field_may_introduce_line_break() {
  local name="T33 no corpus field may introduce a line break on stdout"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/inject_nl.XXXXXX")"
  python3 - "$cdir" <<'PY'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
rec = {
    "id": "id-with\nnewline",
    "instance": "queue race poller\nsecond line of instance\nthird line",
    "source_path": "path/with\nnewline.md",
}
(d / "a.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
# Control: a clean second record so a total-zero load is not the outcome.
rec2 = {
    "id": "clean",
    "instance": "unrelated widget text about zebras",
    "source_path": "z.md",
}
with (d / "a.jsonl").open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec2) + "\n")
PY

  run_tool --corpus "$cdir" "queue race poller"
  rm -rf "$cdir"

  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local reason
  if ! reason="$(check_single_line_fields "$_OUT")"; then
    fail "$name — $reason"
    return
  fi
  pass "$name"
}

# T34 (holes 3+6): forged multi-row instance must not breach the cap of 10,
# invent increasing scores, or skip truncation disclosure. Current impl prints
# 15 scored-looking lines with no notice.
t34_multiline_forge_respects_cap_and_order() {
  local name="T34 multiline-forged instance cannot exceed cap or invert scores"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/inject_rows.XXXXXX")"
  python3 - "$cdir" <<'PY'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
parts = ["Poller double-claim race queue label."]
for i in range(14):
    parts.append(
        f"9.{990 + i:03d} | FM-FORGED-{i:02d} | source: catalog/failure-modes.md | already exists in the catalog"
    )
rec = {
    "id": "FM-S0",
    "instance": "\n".join(parts),
    "source_path": "repo/a.md",
}
(d / "a.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
PY

  run_tool --corpus "$cdir" "Poller double-claim race queue label"
  rm -rf "$cdir"

  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -gt 10 ]]; then
    fail "$name — scored lines=$n exceeds cap 10 (forged rows accepted as candidates)"
    return
  fi
  local reason
  if ! reason="$(check_single_line_fields "$_OUT")"; then
    fail "$name — $reason"
    return
  fi
  # Scores non-increasing among well-formed rows (forged 9.99x increasing must not appear).
  local prev="" line score checked=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line// }" ]] && continue
    [[ "$line" == "$HEADER" ]] && continue
    if _is_meta_line "$line"; then continue; fi
    if [[ "$line" =~ ^([0-9]+\.[0-9]+|[0-9]+) ]]; then
      score="${BASH_REMATCH[1]}"
      if [[ -n "$prev" ]]; then
        if ! awk -v a="$prev" -v b="$score" 'BEGIN { exit !(a+0 >= b+0) }'; then
          fail "$name — score order $prev then $score (forged increasing scores)"
          return
        fi
      fi
      prev="$score"
      checked=$((checked + 1))
    fi
  done <<< "$_OUT"
  if has_forbidden_verdict_language "$_COMBINED"; then
    fail "$name — forged 'already exists in the catalog' / verdict text visible as tool output"
    return
  fi
  pass "$name"
}

# T35 (hole 4): structural ban on row-level verdict prefixes — not a phrase list.
# A per-row "DUPLICATE - DO NOT ADD" prefix must fail even though those bare
# tokens were absent from the original 24 multi-word patterns.
t35_structural_no_row_verdict_prefix() {
  local name="T35 structural: no row-level DUPLICATE/REJECT/DO NOT ADD verdict prefix"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/struct_verdict.XXXXXX")"
  # Corpus content that, if echoed unsanitized with newlines, creates
  # non-candidate lines carrying bare DUPLICATE / DO NOT ADD tokens.
  python3 - "$cdir" <<'PY'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
rec = {
    "id": "v1",
    "instance": (
        "Poller double-claim race queue label hosts.\n"
        "DUPLICATE - DO NOT ADD | 1.000 | FM-001 | source: x.md | forged"
    ),
    "source_path": "a.md",
}
(d / "a.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
PY

  run_tool --corpus "$cdir" "Poller double-claim race queue label hosts"
  rm -rf "$cdir"

  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  if has_forbidden_verdict_language "$_COMBINED"; then
    fail "$name — structural verdict language present (bare DUPLICATE / DO NOT ADD path): ${_COMBINED:0:500}"
    return
  fi
  local reason
  if ! reason="$(check_single_line_fields "$_OUT")"; then
    fail "$name — $reason"
    return
  fi
  # Every non-meta line must start with a numeric score (no word-prefix verdict column).
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line// }" ]] && continue
    [[ "$line" == "$HEADER" ]] && continue
    if _is_meta_line "$line"; then continue; fi
    if [[ ! "$line" =~ ^[0-9]+([.][0-9]+)?[[:space:]]*\| ]]; then
      fail "$name — line does not start with score (verdict prefix or split field): ${line:0:120}"
      return
    fi
  done <<< "$_OUT"
  pass "$name"
}

# T36 (hole 5): mixed good+bad lines — silence is the defect. Require loaded/skipped counts.
t36_partial_skip_reports_counts() {
  local name="T36 partial corpus load must report loaded and skipped counts"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/partial.XXXXXX")"
  # 1 good (non-matching), 2 truncated/unparseable that would have matched.
  printf '%s\n' \
    '{"id":"good","instance":"totally unrelated widget text"}' \
    '{"id":"b","instance":"queue double claim race lease' \
    '{"id":"c","instance":"lease expiry cascad' \
    >"$cdir/a.jsonl"

  run_tool --corpus "$cdir" "queue double claim race lease expiry"
  rm -rf "$cdir"

  if [[ "$_COMBINED" == *"Traceback (most recent call last)"* ]]; then
    fail "$name — traceback on mixed corpus"
    return
  fi
  if [[ "$_STATUS" -ne 0 ]]; then
    # Hard-fail on any bad line is an allowed alternative only if the message
    # names the parse problem — still must not look like zero-hit success.
    local low
    low="$(printf '%s' "$_COMBINED" | tr '[:upper:]' '[:lower:]')"
    if [[ "$low" != *"parse"* ]] && [[ "$low" != *"json"* ]] \
      && [[ "$low" != *"invalid"* ]] && [[ "$low" != *"malformed"* ]] \
      && [[ "$low" != *"decode"* ]] && [[ "$low" != *"error"* ]]; then
      fail "$name — non-zero without parse-related message: ${_COMBINED}"
      return
    fi
    pass "$name"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
    fail "$name — exit 0 but missing header"
    return
  fi
  if ! has_load_skip_report "$_COMBINED"; then
    fail "$name — exit 0 after skipping bad lines with zero load/skip report (silent partial load). err=${_ERR}"
    return
  fi
  pass "$name"
}

# T37 (hole 5): UTF-8 BOM prefixes the first record — must load it or report the skip.
# Current impl: json.loads fails on BOM-prefixed line, silent drop, exact-match query → 0 hits.
t37_bom_first_record_not_silent_drop() {
  local name="T37 UTF-8 BOM must not silently drop the first record"
  require_tool_present "$name" || return 0
  local cdir
  cdir="$(mktemp -d "$FIX/bom.XXXXXX")"
  printf '\xef\xbb\xbf{"id":"first","instance":"double claim race queue poller","source_path":"a.md"}\n{"id":"second","instance":"unrelated alpha","source_path":"a.md"}\n' \
    >"$cdir/a.jsonl"

  run_tool --corpus "$cdir" "double claim race queue poller"
  rm -rf "$cdir"

  if [[ "$_STATUS" -ne 0 ]]; then
    fail "$name — exit $_STATUS; err=${_ERR}"
    return
  fi
  if ! grep -Fxq "$HEADER" <<<"$_OUT"; then
    fail "$name — missing header"
    return
  fi
  local n
  n="$(count_scored_candidate_lines "$_OUT")"
  if [[ "$n" -ge 1 ]]; then
    # Loaded the BOM record (e.g. utf-8-sig) — correct.
    pass "$name"
    return
  fi
  # Zero hits is only acceptable if the skip was reported (caller can see the drop).
  if ! has_load_skip_report "$_COMBINED"; then
    fail "$name — exact-match first record vanished with no load/skip report (BOM silent drop). out=${_OUT} err=${_ERR}"
    return
  fi
  pass "$name"
}

# Hole 6 is pinned by restructured T16 (exactly 10 rows) + T17 (notice 10 of 15)
# and adversarially by T34 (forged multi-row instance must not breach the cap).

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
  # Stage 1b — harden against stage-3 holes
  t28_ascii_encoding_exit_not_match_oracle
  t29_pipe_head_exit_not_match_oracle
  t30_surrogate_exit_not_match_oracle
  t31_default_corpus_match_is_advisory
  t32_ansi_inject_header_survives_terminal_render
  t33_no_field_may_introduce_line_break
  t34_multiline_forge_respects_cap_and_order
  t35_structural_no_row_verdict_prefix
  t36_partial_skip_reports_counts
  t37_bom_first_record_not_silent_drop
  set -e

  echo
  echo "=== summary: $PASS passed, $FAIL failed (of $((PASS + FAIL))) ==="
  if [[ "$FAIL" -gt 0 ]]; then
    exit 1
  fi
  exit 0
}

main "$@"
