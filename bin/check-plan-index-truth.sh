#!/usr/bin/env bash
# check-plan-index-truth.sh — refuse to let plans/00-INDEX.md assert a
# dependency or a block that the evidence has already discharged.
#
# Background: the index carries `blocked-by` / `blocks` columns and
# BLOCKED / FOUNDER-BLOCKED status cells. Twice now a human review found rows
# asserting blockers that were already discharged — a completed plan still
# listed as a blocker, an issue cited as "must decide" that had closed
# COMPLETED, a FOUNDER-BLOCKED row whose ruling had already been handed down.
# Nothing detected any of it. That is this repo's own thesis: a registry that
# is a diary rather than a gate.
#
# Contract: every claim in the table is checked against evidence this script
# can actually fetch — the referenced issue's/PR's state via `gh`, the target
# plan's own status cell, founder-ruling comments on the plan's own issue, and
# `docs/DECISIONS.md` rows. Nothing is graded on prose.
#
# Every cited artifact lands in exactly one of THREE states, never two:
#
#   verified-open / verified-closed — the API answered, and the answer is
#       graded against the row's claim.
#   UNKNOWN — the API did not answer, or answered with something this script
#       cannot read: no credentials, rejected credentials, rate limit, network
#       failure, malformed body. UNKNOWN is NEVER folded into "the claim
#       holds". It is reported, the rows that depend on it are named, and the
#       run exits 2.
#
# Three rules that make this a gate rather than decoration:
#
#   1. A claim this script cannot verify is reported UNVERIFIABLE and counted
#      as a failure. It is never silently assumed true. (An unverifiable
#      blocker is exactly how a stale row survives a reviewer.)
#   2. If the evidence source is unreachable — no `gh`, no network, bad
#      credentials, rate limited — this script exits 2 and prints which rows
#      went unchecked. It never goes green on absent evidence. That is the
#      c-001 family (a terminal signal treated as success) this repo exists
#      to kill.
#   3. The credential is the CALLER's. This script will not mint, refresh or
#      fall back to another one, and will not retry: silently repairing a
#      rejected credential means a broken credential path can never be
#      observed by anyone running this check, and a retry loop hides a rate
#      limit behind a delay. Export a working GH_TOKEN and run it again.
#
# UNKNOWN and UNVERIFIABLE are deliberately separate buckets and are printed
# separately. UNVERIFIABLE = the anchor itself is missing, so no evidence
# source could settle it; the index must be fixed. UNKNOWN = the anchor is
# fine and the evidence source could not be reached; the run must be repeated.
#
# Usage:
#   check-plan-index-truth.sh [index-path] [decisions-path]
#
# Env:
#   PLAN_INDEX_REPO   owner/repo to query (default petersimmons1972/hindsight)
#   GH_TOKEN          the credential `gh` will use; supplied by the caller
#
# Exit codes:
#   0  every claim in the table is verified live
#   1  one or more claims are STALE or UNVERIFIABLE (each is printed)
#   2  the evidence source was unreachable for at least one claim (UNKNOWN),
#      or the index could not be parsed

set -uo pipefail

PROG="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INDEX="${1:-$REPO_ROOT/plans/00-INDEX.md}"
DECISIONS="${2:-$REPO_ROOT/docs/DECISIONS.md}"
REPO="${PLAN_INDEX_REPO:-petersimmons1972/hindsight}"
SOURCE_LABEL="$REPO via \`gh\`"

die2() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 2; }

[[ -f "$INDEX" ]] || die2 "index not found: $INDEX"
[[ -f "$DECISIONS" ]] || die2 "decisions file not found: $DECISIONS"

command -v gh >/dev/null 2>&1 || die2 \
  "EVIDENCE SOURCE UNREACHABLE: \`gh\` is not installed. Refusing to grade
  claims with no way to check them. This is a hard failure, not a skip."

# ------------------------------------------------------- the caller's cred ---
# Rule 3 says this script runs on the CALLER's credential and never substitutes
# another. Anything that rewrites GH_TOKEN between exec and line 1 defeats that
# silently — a BASH_ENV that re-exports a freshly minted installation token is
# measured doing exactly this. The result is the c-001 shape this repo exists to
# kill: hand the checker a DEAD credential and it returns green off a live one
# the caller never supplied, so a broken credential path cannot be observed by
# anyone running this check, and the auth-failure test above silently passes.
#
# /proc/$$/environ still holds the environment as it was at exec — the only
# place the caller's own value survives the rewrite. Two deliberate narrowings:
# if the caller set no GH_TOKEN at all, an ambient one is legitimately theirs
# and is left alone; and where /proc is unavailable nothing is claimed and
# nothing is changed, because a guess here would be worse than the gap.
if [[ -r "/proc/$$/environ" ]]; then
  if tr '\0' '\n' <"/proc/$$/environ" | grep -q '^GH_TOKEN='; then
    caller_tok="$(tr '\0' '\n' <"/proc/$$/environ" | sed -n 's/^GH_TOKEN=//p' | head -1)"
    if [[ "$caller_tok" != "${GH_TOKEN:-}" ]]; then
      printf '%s: GH_TOKEN was rewritten between exec and start (BASH_ENV or similar).\n' "$PROG" >&2
      printf '%s: running on the credential the CALLER supplied, not the substituted one.\n' "$PROG" >&2
      export GH_TOKEN="$caller_tok"
      # ...and it must not follow us into the processes we spawn to gather the
      # evidence, or the substitution simply happens one level down and the
      # restore above buys nothing. Any shell-script `gh` wrapper would be
      # re-clobbered exactly the way this script was.
      unset BASH_ENV
    fi
  fi
fi

# ------------------------------------------------------------------ parsing ---
# Driven by the table's own structure, never by the strings that happen to be
# stale today. A row is any pipe table line whose first cell is a plan id.
# Parsed BEFORE the evidence source is probed, so that a dead source can name
# the specific rows whose claims it left unchecked.
#
# CHECK A — table-region integrity (issue #69, the c-001 row-drop hole).
# Unconditional: applies to every index, canonical or fixture. The old parser
# below (single awk pass, no header anchor) silently dropped any row whose id
# cell was perturbed or whose column count was short. Locate the plans-table
# header STRUCTURALLY — a pipe row whose trimmed, lowercased cells are
# exactly `#, file, issue, status, blocked-by, blocks` — and require exactly
# one match. Zero or two-or-more is fatal: a checker that cannot
# unambiguously find its own table must refuse rather than report a clean
# index. The region runs from that header to the first following line that
# does not start with optional whitespace then `|`. Every line in the region
# other than the header and a separator row (cells made only of `-`/`:`) must
# parse — NF >= 7 (`-F'|'`) and field 2, stripped of whitespace/`*`/backtick,
# matching `^[0-9]+$` — or the run is fatal, naming the 1-based line number
# and the raw offending line. No region line may be silently skipped.

# Resolve which baseline (if any) Check B will use, and announce a skip up
# front — before Check A can fatally exit — so the skip notice is printed
# regardless of whether the region itself turns out to be malformed. A
# skipped check must be visible no matter which check fires first.
requested_index="$(realpath -m -- "$INDEX")"
canonical_index="$(realpath -m -- "$REPO_ROOT/plans/00-INDEX.md")"

run_check_b=0
if [[ -n "${PLAN_INDEX_EXPECTED_IDS+set}" ]]; then
  eids_baseline="$PLAN_INDEX_EXPECTED_IDS"
  run_check_b=1
elif [[ "$requested_index" == "$canonical_index" ]]; then
  eids_baseline="$REPO_ROOT/conf/plan-index-expected-ids.conf"
  run_check_b=1
fi

if (( ! run_check_b )); then
  printf '%s: pinned expected-id check (Check B) SKIPPED for %s — this is not the canonical index and PLAN_INDEX_EXPECTED_IDS is not set. Only Check A (table-region integrity / structural check) applied. This is not a verification of the id set.\n' \
    "$PROG" "$INDEX" >&2
fi

hdr_info="$(awk -F'|' '
  BEGIN { split("#,file,issue,status,blocked-by,blocks", want, ",") }
  /^[[:space:]]*\|/ {
    if (NF == 8) {
      ok = 1
      for (i = 2; i <= 7; i++) {
        c = $i; gsub(/^[[:space:]]+|[[:space:]]+$/, "", c); c = tolower(c)
        if (c != want[i - 1]) { ok = 0; break }
      }
      if (ok) { cnt++; if (cnt == 1) first = NR }
    }
  }
  END { printf "%d\t%d\n", cnt+0, first+0 }
' "$INDEX")"
header_count="${hdr_info%%$'\t'*}"
header_line="${hdr_info##*$'\t'}"

if (( header_count == 0 )); then
  die2 \
    "could not parse any plan rows out of $INDEX — the table shape changed.
  Refusing to report a clean index off a parser that matched nothing.
  (no plans-table header — # | file | issue | status | blocked-by | blocks —
  found structurally in the file.)"
elif (( header_count > 1 )); then
  die2 \
    "found $header_count plans-table header rows in $INDEX, not exactly one.
  A checker that cannot unambiguously find its own table must refuse rather
  than report a clean index."
fi

region_result="$(awk -F'|' -v start="$header_line" '
  NR == start { instart = 1; last = start; next }
  instart != 1 { next }
  {
    if ($0 !~ /^[[:space:]]*\|/) { exit }
    last = NR
    is_sep = (NF >= 3)
    for (i = 2; i <= NF - 1 && is_sep; i++) {
      c = $i; gsub(/[[:space:]]+/, "", c)
      if (c !~ /^[-:]+$/) is_sep = 0
    }
    if (is_sep) next
    if (NF < 7) { printf "FATAL\t%d\t%s\n", NR, $0; exit }
    id = $2; gsub(/[[:space:]*`]/, "", id)
    if (id !~ /^[0-9]+$/) { printf "FATAL\t%d\t%s\n", NR, $0; exit }
    file = $3; issue = $4; status = $5; bby = $6; blk = $7
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", file)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", issue)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", status)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", bby)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", blk)
    printf "OK\t%s\t%s\t%s\t%s\t%s\t%s\n", id, file, issue, status, bby, blk
  }
  END { printf "REGIONEND\t%d\n", last }
' "$INDEX")"

ROWS=()
region_end="$header_line"
while IFS=$'\t' read -r tag a b c d e f; do
  [[ -z "$tag" ]] && continue
  if [[ "$tag" == "REGIONEND" ]]; then
    region_end="$a"
    continue
  fi
  if [[ "$tag" == "FATAL" ]]; then
    die2 \
      "index region line $a does not parse and cannot be silently skipped: $b
  Every line inside the plans-table region must parse (NF >= 7, a numeric id
  cell) or the run refuses — no row may be silently dropped from the count."
  fi
  ROWS+=("$a"$'\t'"$b"$'\t'"$c"$'\t'"$d"$'\t'"$e"$'\t'"$f")
done <<<"$region_result"

((${#ROWS[@]} > 0)) || die2 \
  "could not parse any plan rows out of $INDEX — the table shape changed.
  Refusing to report a clean index off a parser that matched nothing."

declare -A R_FILE=() R_ISSUE=() R_STATUS=() R_BBY=() R_BLK=() R_CLASS=()
IDS=()
for row in "${ROWS[@]}"; do
  IFS=$'\t' read -r id file issue status bby blk <<<"$row"
  IDS+=("$id")
  R_FILE["$id"]="$file"; R_ISSUE["$id"]="$issue"; R_STATUS["$id"]="$status"
  R_BBY["$id"]="$bby";   R_BLK["$id"]="$blk"
  # status class = first token, stripped of markdown emphasis
  cls="${status//\*/}"; cls="${cls%%[[:space:]]*}"
  R_CLASS["$id"]="$(tr '[:lower:]' '[:upper:]' <<<"$cls")"
done

# CHECK B — pinned expected id set (conditional on the index being canonical).
# Uses the idiom this repo already uses in bin/add-failure-mode.sh (lines
# 51-52): resolve both paths with `realpath -m` and compare the resolved
# forms, never the strings passed in.
#
#   PLAN_INDEX_EXPECTED_IDS explicitly set  -> Check B runs against that file
#   else index resolves to the canonical    -> Check B runs against conf/
#   else                                    -> Check B is SKIPPED, loudly
#
# When it runs: an expected id missing from the parse, a parsed id absent
# from the baseline, or any id appearing MORE THAN ONCE in the table (counted
# explicitly — set equality alone cannot see a duplicated row) is fatal.

if (( run_check_b )); then
  [[ -r "$eids_baseline" ]] || die2 \
    "pinned expected-id baseline not found or unreadable: $eids_baseline
  An explicitly requested (or canonical) baseline must never silently vanish."

  mapfile -t eids_list < <(grep -vE '^[[:space:]]*(#|$)' "$eids_baseline" \
    | sed -e 's/[[:space:]]//g' | sed -e '/^$/d')

  (( ${#eids_list[@]} > 0 )) || die2 \
    "pinned expected-id baseline $eids_baseline contains no ids.
  An empty baseline would make 'every expected row was checked' vacuously
  true, the same shape as an empty catalog/id-ledger.txt."

  declare -A eid_count=()
  for id in "${IDS[@]}"; do eid_count["$id"]=$(( ${eid_count["$id"]:-0} + 1 )); done

  for id in "${!eid_count[@]}"; do
    if (( eid_count["$id"] > 1 )); then
      die2 \
        "id $id appears more than once (${eid_count[$id]} times) in the
  plans table — a duplicated row. Set equality alone cannot see this; the
  occurrence count is checked explicitly."
    fi
  done

  declare -A eid_baseline_set=()
  for id in "${eids_list[@]}"; do eid_baseline_set["$id"]=1; done

  for id in "${eids_list[@]}"; do
    [[ -n "${eid_count[$id]:-}" ]] || die2 \
      "expected id $id (pinned baseline $eids_baseline) is missing from the
  parsed plans table in $INDEX — a row was dropped."
  done

  for id in "${!eid_count[@]}"; do
    [[ -n "${eid_baseline_set[$id]:-}" ]] || die2 \
      "parsed id $id in $INDEX is not present in the pinned baseline
  $eids_baseline."
  done
fi

# CHECK C — region containment (round 3, adversarial refutation of round 2).
# Check A only validates lines INSIDE the region; Check B only compares ids
# PARSED FROM the region. Neither can see a plan row sitting outside the
# region — a second table, a row above the header, a row stranded by a blank
# line mid-table. Check C's candidate set is computed from the WHOLE FILE,
# independently of the region, and proves nothing plan-row-shaped sits
# outside [$header_line, $region_end].
#
# A line is PLAN-ROW-SHAPED if, split on `|`, it has NF >= 7 and field 2
# (stripped of whitespace, `*`, and backtick) matches ^[0-9]+$. Lines inside a
# CLOSED fenced code block (a matched pair of ``` markers) are exempt — a
# documented example is not a row a reader would mistake for real. An
# unterminated fence exempts nothing: only markers that pair up count.
containment_hit="$(awk -F'|' -v rs="$header_line" -v re="$region_end" '
  {
    lines[NR] = $0
    nf[NR] = NF
    f2[NR] = $2
  }
  END {
    mcount = 0
    for (i = 1; i <= NR; i++) {
      if (lines[i] ~ /^[[:space:]]*```/) { mcount++; marker[mcount] = i }
    }
    pairs = int(mcount / 2)
    for (k = 1; k <= pairs; k++) {
      a = marker[2*k - 1]; b = marker[2*k]
      for (i = a; i <= b; i++) exempt[i] = 1
    }
    for (i = 1; i <= NR; i++) {
      if (exempt[i]) continue
      if (nf[i] < 7) continue
      id = f2[i]
      gsub(/[[:space:]*`]/, "", id)
      if (id !~ /^[0-9]+$/) continue
      if (i < rs || i > re) {
        printf "%d\t%s\n", i, lines[i]
        exit
      }
    }
  }
' "$INDEX")"

if [[ -n "$containment_hit" ]]; then
  hit_line="${containment_hit%%$'\t'*}"
  hit_text="${containment_hit#*$'\t'}"
  die2 \
    "index line $hit_line looks like a plan row but sits outside the plans-table
  region (region: lines $header_line-$region_end) — it is never graded: $hit_text
  Move it into the table or remove it; a plan row outside the table region is
  invisible to every check this tool runs."
fi

# ---------------------------------------------------------------- evidence ---
# The evidence source is probed BEFORE any claim is graded. A checker that
# grades claims against a dead API is a checker that passes.

declare -A ISSUE_STATE=()   # N -> open|closed|unknown
declare -A ISSUE_KIND=()    # N -> issue|pr|?
declare -A ISSUE_TITLE=()
declare -A ISSUE_WHY=()     # N -> why it is unknown, when it is
declare -A RULING_ON=()     # N -> first founder-ruling comment date, if any
declare -A RULING_QUERIED=()

UNKNOWN=()                  # rows whose claims could not be checked
SOURCE_DEAD=0
SOURCE_WHY=""

# Turn gh's own failure text into a named condition. Reported verbatim in the
# UNKNOWN block so "did not verify" can never be mistaken for "verified false".
classify_gh_failure() {  # $1 = gh stderr, $2 = exit status
  local err="$1" rc="$2"
  case "$err" in
    *"rate limit"*|*"secondary rate"*|*"abuse detection"*)
      echo "API rate limit / throttling refused the request (rc=$rc)" ;;
    *"Bad credentials"*|*"401"*)
      echo "credentials rejected: HTTP 401 Bad credentials (rc=$rc)" ;;
    *"gh auth login"*|*"authentication"*|*"not logged"*|*"GH_TOKEN"*)
      echo "no usable credentials available to \`gh\` (rc=$rc)" ;;
    *"403"*)
      echo "access refused: HTTP 403 (rc=$rc)" ;;
    *"404"*)
      echo "HTTP 404 — the cited artifact is not readable with this credential (rc=$rc)" ;;
    *"no such host"*|*"dial tcp"*|*"connection refused"*|*"i/o timeout"*|\
    *"timeout"*|*"network is unreachable"*|*"TLS"*|*"EOF"*|*"temporary failure"*)
      echo "network failure reaching the API (rc=$rc)" ;;
    "")
      echo "no response and no diagnostic from \`gh\` (rc=$rc)" ;;
    *)
      echo "unclassified \`gh\` failure (rc=$rc): $(head -c 160 <<<"$err" | tr '\n' ' ')" ;;
  esac
}

probe_err="$(gh api "/repos/$REPO" --jq '.full_name' 2>&1 >/dev/null)"
probe_rc=$?
if ((probe_rc != 0)); then
  # No refresh, no retry, no fallback credential. See rule 3 in the header.
  SOURCE_DEAD=1
  SOURCE_WHY="$(classify_gh_failure "$probe_err" "$probe_rc")"
  UNKNOWN+=("run-wide · EVIDENCE SOURCE UNREACHABLE · $SOURCE_LABEL — $SOURCE_WHY; \
no claim below was checked against live evidence")
fi

# NOTE: these populate globals and are called in the CURRENT shell, never in a
# `$(...)` substitution — a subshell would throw away the cache.
fetch_issue() {  # $1 = number; fills ISSUE_STATE/KIND/TITLE, or marks unknown
  local n="$1" raw err rc st
  [[ -n "${ISSUE_STATE[$n]:-}" ]] && return 0
  if ((SOURCE_DEAD)); then
    ISSUE_STATE["$n"]=unknown; ISSUE_KIND["$n"]="?"; ISSUE_TITLE["$n"]=""
    ISSUE_WHY["$n"]="$SOURCE_WHY"
    return 0
  fi
  err="$(gh api "/repos/$REPO/issues/$n" \
           --jq '[.state,(if .pull_request then "pr" else "issue" end),(.title//"")]|@tsv' \
           2>"$TMP_ERR" >"$TMP_OUT")" ; rc=$?
  raw="$(cat "$TMP_OUT")"; err="$(cat "$TMP_ERR")"
  if ((rc != 0)); then
    ISSUE_STATE["$n"]=unknown; ISSUE_KIND["$n"]="?"; ISSUE_TITLE["$n"]=""
    ISSUE_WHY["$n"]="$(classify_gh_failure "$err" "$rc")"
    return 0
  fi
  st="${raw%%$'\t'*}"
  if [[ -z "$raw" ]]; then
    ISSUE_STATE["$n"]=unknown; ISSUE_KIND["$n"]="?"; ISSUE_TITLE["$n"]=""
    ISSUE_WHY["$n"]="empty response body — malformed, not a state"
    return 0
  fi
  if [[ "$st" != open && "$st" != closed ]]; then
    ISSUE_STATE["$n"]=unknown; ISSUE_KIND["$n"]="?"; ISSUE_TITLE["$n"]=""
    ISSUE_WHY["$n"]="malformed response: no open/closed state in \"$(head -c 60 <<<"$raw")\""
    return 0
  fi
  ISSUE_STATE["$n"]="$st"
  ISSUE_KIND["$n"]="$(cut -f2 <<<"$raw")"
  ISSUE_TITLE["$n"]="$(cut -f3 <<<"$raw")"
}

fetch_ruling() {  # $1 = number; fills RULING_ON[n] with a date, or empty
  local n="$1" bodies rc err
  [[ -n "${RULING_QUERIED[$n]:-}" ]] && return 0
  RULING_QUERIED["$n"]=1
  if ((SOURCE_DEAD)); then
    RULING_ON["$n"]=""; ISSUE_WHY["ruling-$n"]="$SOURCE_WHY"; return 1
  fi
  gh api --paginate "/repos/$REPO/issues/$n/comments" \
    --jq '.[]|[.created_at,(.body|gsub("[\n\r]";" "))]|@tsv' \
    2>"$TMP_ERR" >"$TMP_OUT"; rc=$?
  bodies="$(cat "$TMP_OUT")"; err="$(cat "$TMP_ERR")"
  if ((rc != 0)); then
    RULING_ON["$n"]=""
    ISSUE_WHY["ruling-$n"]="$(classify_gh_failure "$err" "$rc")"
    return 1
  fi
  RULING_ON["$n"]="$(grep -iE 'founder ruling|ruling:' <<<"$bodies" | head -1 | cut -f1)"
  return 0
}

TMP_ERR="$(mktemp)"; TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_ERR" "$TMP_OUT"' EXIT

is_terminal() { case "$1" in COMPLETE|COMPLETED|DONE|WITHDRAWN|CANCELLED|CANCELED|SUPERSEDED) return 0;; *) return 1;; esac; }
is_complete() { case "$1" in COMPLETE|COMPLETED|DONE) return 0;; *) return 1;; esac; }
is_blocked()  { [[ "$1" == *BLOCKED* ]]; }

# split an edge cell into target tokens; em dash / hyphen / empty = no edges
edge_targets() {
  local cell="$1"
  cell="${cell//\`/}"
  [[ "$cell" == "—" || "$cell" == "-" || "$cell" == "--" || -z "$cell" ]] && return 0
  tr ',/' '  ' <<<"$cell" | tr -s ' ' '\n' | sed '/^$/d'
}

refs_in() { grep -oE '#[0-9]+' <<<"$1" | tr -d '#' | sort -un; }

# ---------------------------------------------------------------- citability ---
# A blocker is citable only when the citation (1) resolves to something this
# script can fetch and grade AND (2) is demonstrably ABOUT the row that cites it.
#
# Round 1 graded `grep -qi 'ruling'` against the status cell, so row 06's own
# wording — "no founder ruling recorded on #21 yet" — switched off the detector
# meant to police it. Round 2 made resolution structural (the artifact is
# fetched, never keyword-matched) and an independent mutation round then walked
# through the gap that was left: resolution was never BOUND. Any real-looking
# reference rescued any row — an APPLIED DECISIONS row about plan 03, the real
# ruling on the issue that governs plan 04, or a sentence about the row's own
# blocker carrying a negation word ("withdrawn") the list did not know.
#
# The negation word-list is deleted rather than extended. A blacklist of
# negation vocabulary is unbounded by construction and the next unlisted word
# reopens the hole; that is a maintenance treadmill masquerading as a check.
# What replaces it is a rule about WHO may settle a row:
#
#   * BINDING (a) — a docs/DECISIONS.md citation counts only if the cited row
#     itself names this plan (`plans/<id>`) or this row's own governing issue.
#     A ruling about another plan cannot discharge this one, however APPLIED.
#   * BINDING (b) — a cited ruling counts only if it sits on the row's OWN
#     governing artifact, derived from the row's issue column, never from the
#     prose. An issue that happens to carry a ruling settles the row it governs
#     and no other.
#   * NO SELF-CERTIFICATION (c) — a clause naming the row's own artifact can
#     never discharge that row on its own say-so. Whether the ruling exists is
#     read from the FETCHED artifact; the sentence is graded AGAINST that state,
#     never accepted as it. So a row may describe its own blocker, and a
#     description the artifact refutes is a failure — in either direction.
#
# Consequence worth stating plainly: a citation that is unbound or unbacked is
# not merely "does not count". It is reported UNVERIFIABLE, because a citation
# pointing at something it is not about reads as backing and is how a stale row
# survives a reviewer.

CITE_UNKNOWN_WHY=""
CITE_BAD=()

# The one sanctioned way for a row to state the ABSENCE of a ruling on its own
# artifact. A fixed phrase is a whitelist and therefore bounded; it never
# certifies anything — it only keeps a truthful row from being read as claiming
# a ruling exists. If the artifact does carry one, S6 below refutes it.
is_absence_form() {  # $1 = clause, $2 = own issue number
  grep -qiE "no (founder )?ruling ([a-z]+ )?(on|at|against) #$2([^0-9]|$)" <<<"$1"
}

# A `#N` is a ruling LOCUS only where the clause places a ruling AT it —
# "founder ruling on #22", "the ruling at #102". A `#N` that merely shares a
# clause with the word ("#24 closed, superseded by the ruling") is not a locus
# and is not read as a citation of anything.
ruling_loci() {  # $1 = clause -> one issue number per line
  grep -oiE 'ruling[^#;]{0,40}#[0-9]+' <<<"$1" \
    | grep -oE '#[0-9]+' | tr -d '#' | sort -un
}

clause_date() { grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' <<<"$1" | head -1; }

# "`docs/DECISIONS.md` rows 22–26" -> 22 23 24 25 26. Ranges and comma lists.
decisions_row_refs() {  # $1 = text -> one row id per line
  local t="${1//–/-}" seg part k
  t="${t//—/-}"
  while read -r seg; do
    [[ -n "$seg" ]] || continue
    seg="${seg#*[Rr][Oo][Ww]}"
    local -a parts=()
    IFS=',' read -ra parts <<<"$seg"
    for part in "${parts[@]}"; do
      part="$(tr -cd '0-9-' <<<"$part")"
      if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
        for ((k=BASH_REMATCH[1]; k<=BASH_REMATCH[2]; k++)); do echo "$k"; done
      elif [[ "$part" =~ ^[0-9]+$ ]]; then
        echo "$part"
      fi
    done
  done < <(grep -oiE 'DECISIONS(\.md)?.{0,3}rows?[[:space:]]*[0-9]+([[:space:]]*[,-][[:space:]]*[0-9]+)*' <<<"$t")
}

decisions_row_state() {  # $1 = row id -> its state cell, or empty if no such row
  awk -F'|' -v want="$1" '
    /^[[:space:]]*\|/ {
      if (NF < 6) next
      n = $2; gsub(/[[:space:]*`]/, "", n); if (n !~ /^[0-9]+$/) next
      if (n != want) next
      s = $5; gsub(/[[:space:]*`]/, "", s); print s; exit
    }' "$DECISIONS"
}

# Does DECISIONS row $1 name plan $2 or plan $2's own governing issue $3?
# Read from the ruling text and the evidence cell, the same two fields
# applied_rows_naming reads, so "binds" and "names" cannot drift apart.
decisions_row_binds() {  # $1 = decisions row, $2 = plan id, $3 = own issue or ""
  # A free `#N` mention is not a bind (issue #88 / #69 F1): "noted while
  # triaging #21" must not discharge plan 06. Own-issue binds require a
  # decision-shaped phrase (issue #N / ruling on #N / founder ruling on #N).
  # Naming plans/<id> remains the strongest bind and is unchanged.
  awk -F'|' -v want="$1" -v id="$2" -v own="$3" '
    /^[[:space:]]*\|/ {
      if (NF < 6) next
      n = $2; gsub(/[[:space:]*`]/, "", n); if (n !~ /^[0-9]+$/) next
      if (n != want) next
      body = $4 $6
      if (body ~ ("plans/" id)) { print "bound"; exit }
      if (own != "") {
        if (body ~ ("issue #" own "([^0-9]|$)")) { print "bound"; exit }
        if (body ~ ("ruling on #" own "([^0-9]|$)")) { print "bound"; exit }
        if (body ~ ("founder ruling on #" own "([^0-9]|$)")) { print "bound"; exit }
      }
      exit
    }' "$DECISIONS"
}

# NOTE: calls fetch_ruling, so it must run in the CURRENT shell — never inside
# a `$(...)`, which would throw the cache away and re-hit the API.
cites_live_ruling() {  # $1 = plan id, $2 = own issue; 0 iff a BOUND citation
  local id="$1" own="$2" status="${R_STATUS[$id]}" clause n r st ok=1 d when
  CITE_UNKNOWN_WHY=""; CITE_BAD=()

  # (a) DECISIONS citations, bound to this plan.
  while read -r r; do
    [[ -n "$r" ]] || continue
    st="$(decisions_row_state "$r")"
    [[ -n "$st" ]] || continue          # does not resolve at all — S8 reports it
    if [[ -z "$(decisions_row_binds "$r" "$id" "$own")" ]]; then
      CITE_BAD+=("cites $(basename "$DECISIONS") row $r, which names neither \
plans/$id nor this row's own #$own; a ruling about another plan cannot discharge this one")
      continue
    fi
    [[ "$st" == APPLIED ]] && ok=0
  done < <(decisions_row_refs "$status")

  # (b)/(c) ruling citations, bound to this row's own artifact and graded
  # against that artifact's fetched state.
  while read -r clause; do
    [[ -n "$clause" ]] || continue
    while read -r n; do
      [[ -n "$n" ]] || continue
      if [[ "$n" != "$own" ]]; then
        CITE_BAD+=("cites a founder ruling on #$n, which is not this row's \
governing artifact (#$own); an issue that happens to carry a ruling settles the row it governs, not this one")
        continue
      fi
      # Its own artifact. The sentence never settles the question; the fetched
      # state does, and the sentence is graded against it.
      is_absence_form "$clause" "$own" && continue
      if ! fetch_ruling "$n"; then
        CITE_UNKNOWN_WHY="${ISSUE_WHY[ruling-$n]:-unreadable}"
        continue
      fi
      when="${RULING_ON[$n]:-}"
      if [[ -z "$when" ]]; then
        CITE_BAD+=("cites a founder ruling on its own #$n and #$n carries none; \
the index is describing a ruling rather than pointing at an artifact that holds one")
        continue
      fi
      d="$(clause_date "$clause")"
      if [[ -n "$d" && "${when%%T*}" != "$d" ]]; then
        CITE_BAD+=("cites a founder ruling on #$n dated $d; the ruling #$n \
actually carries is dated ${when%%T*}")
        continue
      fi
      ok=0
    done < <(ruling_loci "$clause")
  done < <(tr ';' '\n' <<<"$status")
  return $ok
}

# ------------------------------------------------------------------- grading ---
STALE=(); UNVER=()
stale()   { STALE+=("row $1 · $2 · $3"); }
unver()   { UNVER+=("row $1 · $2 · $3"); }
unknown() { UNKNOWN+=("row $1 · $2 · NOT CHECKED — $3"); }

for id in "${IDS[@]}"; do
  cls="${R_CLASS[$id]}"; status="${R_STATUS[$id]}"

  # --- E: edge claims ------------------------------------------------------
  # Graded entirely off the table itself; no evidence source is involved, so
  # these verdicts stand even when the API is down.
  for col in blocked-by blocks; do
    cell="${R_BBY[$id]}"; [[ "$col" == blocks ]] && cell="${R_BLK[$id]}"
    while read -r tgt; do
      [[ -n "$tgt" ]] || continue
      label="\`$col: $tgt\`"
      # E1 — a finished plan neither blocks nor is blocked by anything.
      if is_terminal "$cls"; then
        stale "$id" "$label" "row $id is $cls; a finished plan cannot hold or carry a live edge"
        continue
      fi
      # E3 — target is not a row in this table: nothing to check it against.
      if [[ -z "${R_CLASS[$tgt]:-}" ]]; then
        unver "$id" "$label" "target '$tgt' is not a plan row in this table; the claim has no checkable referent"
        continue
      fi
      # E2 — the other end is discharged.
      if is_terminal "${R_CLASS[$tgt]}"; then
        stale "$id" "$label" "plan $tgt is ${R_CLASS[$tgt]} (${R_FILE[$tgt]}); this edge is discharged"
        continue
      fi
      # E4 — the reciprocal cell must agree.
      if [[ "$col" == blocks ]]; then
        edge_targets "${R_BBY[$tgt]}" | grep -qx "$id" \
          || stale "$id" "$label" "plan $tgt does not list $id in its blocked-by cell; the two halves disagree"
      else
        edge_targets "${R_BLK[$tgt]}" | grep -qx "$id" \
          || stale "$id" "$label" "plan $tgt does not list $id in its blocks cell; the two halves disagree"
      fi
    done < <(edge_targets "$cell")
  done

  # --- S1: the row's own issue must agree with the row's own status ---------
  own="$(refs_in "${R_ISSUE[$id]}" | head -1)"
  if [[ -n "$own" ]]; then
    fetch_issue "$own"; st="${ISSUE_STATE[$own]}"
    if [[ "$st" == unknown ]]; then
      unknown "$id" "status $cls" \
        "its own #$own could not be read from $SOURCE_LABEL (${ISSUE_WHY[$own]}); \
this row's status was neither confirmed nor refuted"
    else
      # COMPLETE-family only. A WITHDRAWN plan's issue may legitimately stay open
      # (it is often a parent tracker that outlives the withdrawn approach), so
      # widening this to every terminal status buys a known false positive.
      if is_complete "$cls" && [[ "$st" == open ]]; then
        stale "$id" "status $cls" "its own #$own (${ISSUE_KIND[$own]}) is still OPEN"
      fi
      if is_blocked "$cls" && [[ "$st" == closed ]]; then
        stale "$id" "status $cls" "its own #$own (${ISSUE_KIND[$own]}) is CLOSED"
      fi
    fi
  else
    is_blocked "$cls" && unver "$id" "status $cls" "the issue column names no #ref, so the row's own state cannot be checked"
  fi

  # --- S2: an obligation clause pinned to an artifact that already closed ---
  # Clause-level, not row-level: "#63 is merged" is a discharge statement,
  # "#24 must select" is an obligation. Only obligations can go stale.
  while read -r clause; do
    [[ -n "$clause" ]] || continue
    grep -qiE '\b(must|need|needs|needed|awaiting|await|pending|require|requires|until|unresolved|undecided|tbd|blocked on)\b' <<<"$clause" || continue
    while read -r n; do
      [[ -n "$n" ]] || continue
      fetch_issue "$n"
      if [[ "${ISSUE_STATE[$n]}" == unknown ]]; then
        unknown "$id" "status clause \"$(sed 's/^ *//' <<<"$clause")\"" \
          "#$n could not be read from $SOURCE_LABEL (${ISSUE_WHY[$n]}); \
the obligation it names may or may not be discharged"
      elif [[ "${ISSUE_STATE[$n]}" == closed ]]; then
        stale "$id" "status clause \"$(sed 's/^ *//' <<<"$clause")\"" \
              "#$n (${ISSUE_KIND[$n]}) is CLOSED — the obligation it names is discharged"
      fi
    done < <(refs_in "$clause")
  done < <(tr ';' '\n' <<<"$status")

  # --- S3/S6: BLOCKED rows must point at something live --------------------
  if is_blocked "$cls"; then
    live_anchor=0; unknown_anchor=0
    while read -r n; do
      [[ -n "$n" ]] || continue
      fetch_issue "$n"
      case "${ISSUE_STATE[$n]}" in
        open)    live_anchor=1 ;;
        unknown) unknown_anchor=1
                 unknown "$id" "status $cls" \
                   "cited #$n could not be read from $SOURCE_LABEL (${ISSUE_WHY[$n]}); \
whether this blocker is still live is unknown" ;;
      esac
    done < <(refs_in "$status")
    while read -r tgt; do
      [[ -n "$tgt" ]] || continue
      [[ -n "${R_CLASS[$tgt]:-}" ]] && ! is_terminal "${R_CLASS[$tgt]}" && live_anchor=1
    done < <(edge_targets "${R_BBY[$id]}")

    # UNVERIFIABLE only when the evidence actually answered. If a cited
    # artifact is UNKNOWN we do not know whether an anchor is live, and
    # calling that "prose with no checkable anchor" would blame the index for
    # the API being down. The two conditions stay separate on purpose.
    if ((live_anchor == 0 && unknown_anchor == 0)); then
      unver "$id" "status $cls" \
            "every artifact this row cites is closed and its blocked-by column names no live plan; the stated blocker is prose with no checkable anchor"
    fi

    # S6 — a FOUNDER-BLOCKED row whose own issue already carries a founder
    # ruling. The escape hatch is a STRUCTURAL and BOUND citation of that ruling
    # (see cites_live_ruling): a fetched artifact that carries one and is this
    # row's own, or an APPLIED DECISIONS row that names this plan. Mentioning
    # the word "ruling" buys nothing, and neither does citing someone else's.
    if [[ "$cls" == *FOUNDER-BLOCKED* && -n "$own" ]]; then
      cites_live_ruling "$id" "$own"; cited=$?
      # An unbound or unbacked citation is a failure in its own right, whether
      # or not some other clause in the same cell happens to resolve.
      if ((${#CITE_BAD[@]})); then
        for bad in "${CITE_BAD[@]}"; do unver "$id" "status $cls" "$bad"; done
      fi
      if ((cited == 0)); then
        : # a citation resolved to an artifact that really does carry a ruling
      elif [[ -n "$CITE_UNKNOWN_WHY" ]]; then
        unknown "$id" "status $cls" \
          "an artifact this row cites could not be read from $SOURCE_LABEL ($CITE_UNKNOWN_WHY); \
whether its citation resolves to a real ruling is unknown"
      elif fetch_ruling "$own"; then
        when="${RULING_ON[$own]:-}"
        [[ -n "$when" ]] && stale "$id" "status $cls" \
          "a founder ruling was recorded on #$own at $when and this row cites no artifact that \
carries one (the word \"ruling\" in the cell is prose, not a citation)"
      else
        unknown "$id" "status $cls" \
          "comments on #$own could not be read from $SOURCE_LABEL (${ISSUE_WHY[ruling-$own]}); \
a founder ruling may already have been handed down"
      fi
    fi
  fi

  # --- S8: a DECISIONS.md row citation must resolve to a real row ----------
  # A citation that points at nothing is worse than no citation: it reads as
  # backing. Graded off the file, so it stands even when the API is down.
  while read -r dr; do
    [[ -n "$dr" ]] || continue
    [[ -n "$(decisions_row_state "$dr")" ]] || \
      unver "$id" "cites $(basename "$DECISIONS") row $dr" \
            "there is no row $dr in $(basename "$DECISIONS"); the citation does not resolve"
  done < <(decisions_row_refs "$status")
done

# --- S4/S5: docs/DECISIONS.md rows ------------------------------------------
# An exactly-APPLIED ruling naming a plan is a discharge; anything else
# ("APPLIED through L2", "HALF-APPLIED", "OPEN") is not.
applied_rows_naming() {  # $1 = plan id
  awk -F'|' -v id="$1" '
    /^[[:space:]]*\|/ {
      if (NF < 6) next
      n = $2; gsub(/[[:space:]*`]/, "", n); if (n !~ /^[0-9]+$/) next
      state = $5; gsub(/[[:space:]*`]/, "", state)
      if (state != "APPLIED") next
      body = $4 $6
      if (body ~ ("plans/" id)) print n
    }' "$DECISIONS"
}

# S7 — the same rows, read as a CONSTRAINT rather than as backing. An APPLIED
# ruling that withdraws / supersedes / completes a named plan does not merely
# license that plan's terminal status: it REQUIRES it. The check used to run one
# way only — it noticed a stale edge aimed at a withdrawn plan, and let the
# withdrawn plan's own status cell claim anything it liked. Disposition is read
# from the ruling text alone ($4), never from the evidence column, so "supersedes
# rulings 10, 14–21" in an evidence cell cannot be misread as superseding a plan.
applied_dispositions_naming() {  # $1 = plan id -> "<row>\t<WITHDRAWN|SUPERSEDED|CANCELLED|COMPLETE>"
  awk -F'|' -v id="$1" '
    /^[[:space:]]*\|/ {
      if (NF < 6) next
      n = $2; gsub(/[[:space:]*`]/, "", n); if (n !~ /^[0-9]+$/) next
      state = $5; gsub(/[[:space:]*`]/, "", state)
      if (state != "APPLIED") next
      if (($4 $6) !~ ("plans/" id)) next
      r = toupper($4); d = ""
      if      (r ~ /WITHDRAW/)                 d = "WITHDRAWN"
      else if (r ~ /SUPERSED/)                 d = "SUPERSEDED"
      else if (r ~ /CANCELL|CANCELED|CANCEL /) d = "CANCELLED"
      else if (r ~ /COMPLETED|COMPLETE|DONE/)  d = "COMPLETE"
      if (d == "") next
      printf "%s\t%s\n", n, d
    }' "$DECISIONS"
}

# Terminal is necessary but not sufficient: a plan the founder WITHDREW is not a
# plan that COMPLETED, and the index must not launder one into the other.
term_family() { case "$1" in COMPLETE|COMPLETED|DONE) echo complete;; WITHDRAWN|CANCELLED|CANCELED|SUPERSEDED) echo retired;; *) echo "";; esac; }

for id in "${IDS[@]}"; do
  cls="${R_CLASS[$id]}"
  hits="$(applied_rows_naming "$id" | paste -sd, -)"

  wrows=""; wdisp=""
  while IFS=$'\t' read -r wr wd; do
    [[ -n "$wr" ]] || continue
    wrows="${wrows:+$wrows,}$wr"
    [[ -z "$wdisp" ]] && wdisp="$wd"
  done < <(applied_dispositions_naming "$id")
  if [[ -n "$wrows" ]]; then
    if ! is_terminal "$cls"; then
      stale "$id" "status $cls" \
        "$(basename "$DECISIONS") row(s) $wrows are APPLIED and record plans/$id as $wdisp; \
that forces a terminal status here, and this row says $cls"
    else
      want="$(term_family "$wdisp")"; got="$(term_family "$cls")"
      if [[ -n "$want" && -n "$got" && "$want" != "$got" ]]; then
        stale "$id" "status $cls" \
          "$(basename "$DECISIONS") row(s) $wrows are APPLIED and record plans/$id as $wdisp, \
which is not what $cls claims"
      fi
    fi
  fi

  case "$cls" in
    WITHDRAWN|CANCELLED|CANCELED|SUPERSEDED)
      [[ -z "$hits" ]] && unver "$id" "status $cls" \
        "no APPLIED row in $(basename "$DECISIONS") names plans/$id; the withdrawal rests on the table asserting itself"
      ;;
  esac
  if is_blocked "$cls" && [[ -n "$hits" ]]; then
    stale "$id" "status $cls" "$(basename "$DECISIONS") row(s) $hits are APPLIED and name plans/$id"
  fi
done

# ------------------------------------------------------------------ report ---
printf '%s: %s (%d plan rows) against %s\n' "$PROG" "$INDEX" "${#IDS[@]}" "$REPO"
echo

if ((${#STALE[@]})); then
  printf 'STALE — the evidence has already discharged these claims (%d):\n' "${#STALE[@]}"
  for f in "${STALE[@]}"; do printf '  ✗ %s\n' "$f"; done
  echo
fi
if ((${#UNVER[@]})); then
  printf 'UNVERIFIABLE — no evidence this checker can reach either way (%d):\n' "${#UNVER[@]}"
  printf '  (counted as failures on purpose: an unverifiable blocker is how a stale row survives)\n'
  printf '  (the anchor itself is missing — fix the index, not the network)\n'
  for f in "${UNVER[@]}"; do printf '  ? %s\n' "$f"; done
  echo
fi
if ((${#UNKNOWN[@]})); then
  printf 'UNKNOWN — EVIDENCE SOURCE UNREACHABLE, so these claims were NOT checked (%d):\n' \
    "${#UNKNOWN[@]}"
  printf '  source: %s\n' "$SOURCE_LABEL"
  printf '  THIS RUN DID NOT VERIFY THE INDEX. This is not "checked and wrong";\n'
  printf '  it is "not checked at all". Distinct from the block above: there the\n'
  printf '  anchor is missing, here the anchor is fine and the evidence was not\n'
  printf '  reachable. No credential was minted and nothing was retried — supply\n'
  printf '  a working GH_TOKEN for %s and run this again.\n' "$REPO"
  for f in "${UNKNOWN[@]}"; do printf '  ! %s\n' "$f"; done
  echo
fi

if ((${#UNKNOWN[@]})); then
  printf '%d stale, %d unverifiable, %d UNCHECKED. The evidence source was unreachable; no verdict was reached.\n' \
    "${#STALE[@]}" "${#UNVER[@]}" "${#UNKNOWN[@]}" >&2
  exit 2
fi

total=$(( ${#STALE[@]} + ${#UNVER[@]} ))
if ((total == 0)); then
  echo "OK — every blocked-by / blocks edge and every BLOCKED status is still true."
  exit 0
fi
printf '%d stale, %d unverifiable. The index asserts blockers it cannot back.\n' \
  "${#STALE[@]}" "${#UNVER[@]}" >&2
exit 1
