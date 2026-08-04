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

# ------------------------------------------------------------------ parsing ---
# Driven by the table's own structure, never by the strings that happen to be
# stale today. A row is any pipe table line whose first cell is a plan id.
# Parsed BEFORE the evidence source is probed, so that a dead source can name
# the specific rows whose claims it left unchecked.

mapfile -t ROWS < <(awk -F'|' '
  /^[[:space:]]*\|/ {
    if (NF < 7) next
    id = $2; gsub(/[[:space:]*`]/, "", id)
    if (id !~ /^[0-9]+$/) next
    file = $3; issue = $4; status = $5; bby = $6; blk = $7
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", file)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", issue)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", status)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", bby)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", blk)
    printf "%s\t%s\t%s\t%s\t%s\t%s\n", id, file, issue, status, bby, blk
  }' "$INDEX")

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
    # ruling. The escape hatch is to cite the ruling in the status cell.
    if [[ "$cls" == *FOUNDER-BLOCKED* && -n "$own" ]] \
       && ! grep -qi 'ruling' <<<"$status"; then
      if fetch_ruling "$own"; then
        when="${RULING_ON[$own]:-}"
        [[ -n "$when" ]] && stale "$id" "status $cls" \
          "a founder ruling was recorded on #$own at $when and this row does not cite it"
      else
        unknown "$id" "status $cls" \
          "comments on #$own could not be read from $SOURCE_LABEL (${ISSUE_WHY[ruling-$own]}); \
a founder ruling may already have been handed down"
      fi
    fi
  fi
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

for id in "${IDS[@]}"; do
  cls="${R_CLASS[$id]}"
  hits="$(applied_rows_naming "$id" | paste -sd, -)"
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
