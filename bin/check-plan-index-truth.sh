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
# Two rules that make this a gate rather than decoration:
#
#   1. A claim this script cannot verify is reported UNVERIFIABLE and counted
#      as a failure. It is never silently assumed true. (An unverifiable
#      blocker is exactly how a stale row survives a reviewer.)
#   2. If the evidence source is unreachable — no `gh`, no network, bad
#      credentials — this script exits 2. It never goes green on absent
#      evidence. That is the c-001 family (a terminal signal treated as
#      success) this repo exists to kill.
#
# Usage:
#   check-plan-index-truth.sh [index-path] [decisions-path]
#
# Env:
#   PLAN_INDEX_REPO   owner/repo to query (default petersimmons1972/hindsight)
#
# Exit codes:
#   0  every claim in the table is verified live
#   1  one or more claims are STALE or UNVERIFIABLE (each is printed)
#   2  the evidence source is unreachable, or the index could not be parsed

set -uo pipefail

PROG="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INDEX="${1:-$REPO_ROOT/plans/00-INDEX.md}"
DECISIONS="${2:-$REPO_ROOT/docs/DECISIONS.md}"
REPO="${PLAN_INDEX_REPO:-petersimmons1972/hindsight}"

die2() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 2; }

[[ -f "$INDEX" ]] || die2 "index not found: $INDEX"
[[ -f "$DECISIONS" ]] || die2 "decisions file not found: $DECISIONS"

# ---------------------------------------------------------------- evidence ---
# The evidence source must be proven reachable BEFORE any claim is graded.
# A checker that grades claims against a dead API is a checker that passes.

command -v gh >/dev/null 2>&1 || die2 \
  "EVIDENCE SOURCE UNREACHABLE: \`gh\` is not installed. Refusing to grade
  claims with no way to check them. This is a hard failure, not a skip."

gh_probe() { gh api "/repos/$REPO" --jq '.full_name' >/dev/null 2>&1; }

if ! gh_probe; then
  # Ambient App installation tokens expire in long-lived sessions; refresh once
  # (same treatment as bin/dispatch-wave.sh) before declaring the source dead.
  if command -v gh-app-token >/dev/null 2>&1; then
    GH_TOKEN="$(gh-app-token claude 2>/dev/null | tr -d '[:space:]')" && export GH_TOKEN
  fi
  gh_probe || die2 \
    "EVIDENCE SOURCE UNREACHABLE: cannot query $REPO via \`gh\` (offline, or
  credentials rejected). Every blocker claim in $INDEX is therefore
  UNCHECKED. Refusing to exit 0 on absent evidence."
fi

declare -A ISSUE_STATE=()   # N -> open|closed
declare -A ISSUE_KIND=()    # N -> issue|pr
declare -A ISSUE_TITLE=()
declare -A RULING_ON=()     # N -> first founder-ruling comment date, if any
declare -A RULING_QUERIED=()

# NOTE: these populate globals and are called in the CURRENT shell, never in a
# `$(...)` substitution. Two reasons, both load-bearing: a subshell would throw
# away the cache, and — far worse — a `die2` raised inside one would kill only
# the subshell, turning an unreachable evidence source into a silent skip.
fetch_issue() {  # $1 = number; fills ISSUE_STATE/KIND/TITLE or exits 2
  local n="$1" raw
  [[ -n "${ISSUE_STATE[$n]:-}" ]] && return 0
  raw="$(gh api "/repos/$REPO/issues/$n" \
           --jq '[.state,(if .pull_request then "pr" else "issue" end),(.title//"")]|@tsv' 2>/dev/null)" \
    || die2 "EVIDENCE SOURCE UNREACHABLE: could not fetch #$n from $REPO"
  [[ -n "$raw" ]] || die2 "EVIDENCE SOURCE UNREACHABLE: empty response for #$n"
  ISSUE_STATE["$n"]="${raw%%$'\t'*}"
  ISSUE_KIND["$n"]="$(cut -f2 <<<"$raw")"
  ISSUE_TITLE["$n"]="$(cut -f3 <<<"$raw")"
}

fetch_ruling() {  # $1 = number; fills RULING_ON[n] with a date, or empty
  local n="$1" bodies
  [[ -n "${RULING_QUERIED[$n]:-}" ]] && return 0
  RULING_QUERIED["$n"]=1
  bodies="$(gh api --paginate "/repos/$REPO/issues/$n/comments" \
              --jq '.[]|[.created_at,(.body|gsub("[\n\r]";" "))]|@tsv' 2>/dev/null)" \
    || die2 "EVIDENCE SOURCE UNREACHABLE: could not fetch comments for #$n"
  RULING_ON["$n"]="$(grep -iE 'founder ruling|ruling:' <<<"$bodies" | head -1 | cut -f1)"
}

# ------------------------------------------------------------------ parsing ---
# Driven by the table's own structure, never by the strings that happen to be
# stale today. A row is any pipe table line whose first cell is a plan id.

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
stale() { STALE+=("row $1 · $2 · $3"); }
unver() { UNVER+=("row $1 · $2 · $3"); }

for id in "${IDS[@]}"; do
  cls="${R_CLASS[$id]}"; status="${R_STATUS[$id]}"

  # --- E: edge claims ------------------------------------------------------
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
    # COMPLETE-family only. A WITHDRAWN plan's issue may legitimately stay open
    # (it is often a parent tracker that outlives the withdrawn approach), so
    # widening this to every terminal status buys a known false positive.
    if is_complete "$cls" && [[ "$st" == open ]]; then
      stale "$id" "status $cls" "its own #$own (${ISSUE_KIND[$own]}) is still OPEN"
    fi
    if is_blocked "$cls" && [[ "$st" == closed ]]; then
      stale "$id" "status $cls" "its own #$own (${ISSUE_KIND[$own]}) is CLOSED"
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
      if [[ "${ISSUE_STATE[$n]}" == closed ]]; then
        stale "$id" "status clause \"$(sed 's/^ *//' <<<"$clause")\"" \
              "#$n (${ISSUE_KIND[$n]}) is CLOSED — the obligation it names is discharged"
      fi
    done < <(refs_in "$clause")
  done < <(tr ';' '\n' <<<"$status")

  # --- S3/S6: BLOCKED rows must point at something live --------------------
  if is_blocked "$cls"; then
    live_anchor=0
    while read -r n; do
      [[ -n "$n" ]] || continue
      fetch_issue "$n"
      [[ "${ISSUE_STATE[$n]}" == open ]] && live_anchor=1
    done < <(refs_in "$status")
    while read -r tgt; do
      [[ -n "$tgt" ]] || continue
      [[ -n "${R_CLASS[$tgt]:-}" ]] && ! is_terminal "${R_CLASS[$tgt]}" && live_anchor=1
    done < <(edge_targets "${R_BBY[$id]}")

    if ((live_anchor == 0)); then
      unver "$id" "status $cls" \
            "every artifact this row cites is closed and its blocked-by column names no live plan; the stated blocker is prose with no checkable anchor"
    fi

    # S6 — a FOUNDER-BLOCKED row whose own issue already carries a founder
    # ruling. The escape hatch is to cite the ruling in the status cell.
    if [[ "$cls" == *FOUNDER-BLOCKED* && -n "$own" ]] \
       && ! grep -qi 'ruling' <<<"$status"; then
      fetch_ruling "$own"; when="${RULING_ON[$own]:-}"
      [[ -n "$when" ]] && stale "$id" "status $cls" \
        "a founder ruling was recorded on #$own at $when and this row does not cite it"
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
  for f in "${UNVER[@]}"; do printf '  ? %s\n' "$f"; done
  echo
fi

total=$(( ${#STALE[@]} + ${#UNVER[@]} ))
if ((total == 0)); then
  echo "OK — every blocked-by / blocks edge and every BLOCKED status is still true."
  exit 0
fi
printf '%d stale, %d unverifiable. The index asserts blockers it cannot back.\n' \
  "${#STALE[@]}" "${#UNVER[@]}" >&2
exit 1
