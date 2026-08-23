#!/usr/bin/env bash
# check-reset-soft-commit.sh -- mechanizes FM-266.
#
# THE FAILURE (FM-266, CRITICAL): `git reset --soft <remote-ref>` used to
# reconcile ONE diverged file moves HEAD but leaves the index and worktree at
# the OLD, stale local tip. A subsequent narrow `git add <file> && git commit`
# therefore commits the ENTIRE stale-index-vs-new-HEAD diff -- in the real
# incident, the deletion of a 935-line test file plus ~5 other files, which was
# force-pushed and found only by auditing the pushed commit afterwards.
#
# WHAT THIS DOES: given a commit C, it reconstructs from the HEAD reflog whether
# C was created immediately after a reset onto a DIVERGED ref, and if so reports
# every path whose state in C simply carries over the pre-reset tip's content --
# i.e. paths the author never touched and did not intend to commit.
#
# ============================ SCOPE HONESTY ============================
# This is NOT a boundary. It is an accident-stopper, and it is narrow.
#
#   * `git push --no-verify` bypasses it completely. So does `--no-verify` on
#     any hook. It cannot stop a determined or scripted push.
#   * It is inert in a fresh clone. It runs only because this repo's LOCAL
#     `core.hooksPath` is set to `.githooks`, which is git CONFIG, not committed
#     content. Until an operator runs `bin/install-hooks.sh`, nothing here
#     fires. Do NOT "fix" that by writing to the machine-wide
#     ~/.config/git/hooks -- that directory is shared by every repo on this box
#     and an installer already clobbered it once (FM-408).
#   * It reads the HEAD reflog of the repo it runs in. A push made from a
#     DIFFERENT clone, a different worktree, or after `git reflog expire`, has
#     no reflog evidence to read and is NOT checked.
#   * It requires the `reset:` and `commit:` reflog entries to be ADJACENT.
#     This is deliberate: it is what separates FM-266's exact shape from
#     rebase / pull --rebase / cherry-pick, which also write `reset: moving to`
#     entries onto non-ancestor targets and would otherwise fire constantly.
#     CONSEQUENCE, stated plainly: a reset --soft with any intervening HEAD
#     movement (a checkout, a second reset) before the commit is NOT caught.
#     The broader version is not safe to ship -- it cannot tell that shape from
#     a normal rebase, and a guard that cries wolf gets --no-verify'd forever.
#   * RESIDUAL FALSE POSITIVE, information-theoretic and unfixable here: git's
#     reflog message is identical for --soft, --mixed and --hard. When the
#     pre-reset tip and the reset target differ ONLY in the paths at issue, a
#     `reset --hard X && git rm <path> && commit` produces a byte-identical
#     commit and a byte-identical reflog to the FM-266 shape. Nothing can tell
#     them apart after the fact, so this guard reports -- erring toward the
#     loud side, with a named escape hatch. Any wider divergence between the
#     tip and the target makes a hard reset detectable and the guard silent.
#   * It says nothing about whether the intended change is correct. It only
#     reports content the author demonstrably did not author in this window.
# =======================================================================
#
# Exit codes: 0 = clean or not applicable, 1 = usage error, 2 = guard fired.
# Escape hatch (deliberate, loud, auditable): HINDSIGHT_ALLOW_STALE_RESET=1

set -euo pipefail

MAX_REFLOG_ENTRIES=200

usage() {
  cat >&2 <<'EOF'
usage: check-reset-soft-commit.sh [--push-tip <sha>]...

With no --push-tip, checks HEAD. With one or more --push-tip shas (as a
pre-push hook supplies), checks only reset-then-commit events whose commit is
reachable from one of those tips.

exit 0 = clean / not applicable   exit 1 = usage   exit 2 = unintended files
EOF
}

TIPS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --push-tip)
      [ $# -ge 2 ] || { usage; exit 1; }
      TIPS+=("$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "check-reset-soft-commit: unknown argument '$1'" >&2; usage; exit 1 ;;
  esac
done

git rev-parse --git-dir >/dev/null 2>&1 || {
  echo "check-reset-soft-commit: not inside a git repository" >&2; exit 1; }

if [ "${HINDSIGHT_ALLOW_STALE_RESET:-0}" = "1" ]; then
  echo "check-reset-soft-commit: BYPASSED via HINDSIGHT_ALLOW_STALE_RESET=1" >&2
  exit 0
fi

if [ ${#TIPS[@]} -eq 0 ]; then
  TIPS=("$(git rev-parse HEAD)")
fi

# Read the HEAD reflog newest-first as "<sha>\t<message>". --no-abbrev is
# required: the default format abbreviates, and an abbreviated sha is not a
# safe key for the ancestry tests below.
#
# A failed git read is a loud refusal. An empty successful read is "nothing
# found" and is not an error -- those two must not collapse into each other.
# `<(cmd || true)` plus mapfile is that collapse: any reflog failure looks
# like zero findings and the commit is permitted. Process substitution also
# hides cmd's status from `set -e`, so the rc is captured explicitly.
reflog_rc=0
reflog_out=$(git reflog show HEAD --no-abbrev --format='%H%x09%gs' \
  -n "$MAX_REFLOG_ENTRIES") || reflog_rc=$?
if [ "$reflog_rc" -ne 0 ]; then
  echo "check-reset-soft-commit: git reflog failed (exit ${reflog_rc}); refusing to treat an unread reflog as clean" >&2
  exit 1
fi
REFLOG=()
if [ -n "$reflog_out" ]; then
  mapfile -t REFLOG < <(printf '%s\n' "$reflog_out")
fi

n=${#REFLOG[@]}
FINDINGS=0

# Is $1 reachable from any tip being pushed?
in_push_range() {
  local commit="$1" tip
  for tip in "${TIPS[@]}"; do
    # Skip the all-zero sha a branch deletion supplies.
    case "$tip" in *[!0]*) ;; *) continue ;; esac
    git rev-parse --verify --quiet "${tip}^{commit}" >/dev/null 2>&1 || continue
    if git merge-base --is-ancestor "$commit" "$tip" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

# Fill array named $1 with NUL-delimited paths from `git diff -z --name-only $2 $3`.
# Command substitution cannot store NUL, so this reads a temp file, never $(...).
# A failed git read is a loud refusal, never an empty name set.
git_diff_names() {
  local dest_name="$1" rev_a="$2" rev_b="$3"
  local tmp rc=0
  tmp=$(mktemp "${TMPDIR:-/tmp}/hindsight-rssc.XXXXXX") || {
    echo "check-reset-soft-commit: mktemp failed; refusing" >&2
    exit 1
  }
  git diff -z --name-only "$rev_a" "$rev_b" >"$tmp" || rc=$?
  if [ "$rc" -ne 0 ]; then
    rm -f "$tmp"
    echo "check-reset-soft-commit: git diff failed (exit ${rc}) for ${rev_a}..${rev_b}; refusing" >&2
    exit 1
  fi
  local -a _buf=()
  if [ -s "$tmp" ]; then
    while IFS= read -r -d '' p; do
      _buf+=("$p")
    done < "$tmp"
  fi
  rm -f "$tmp"
  eval "${dest_name}=()"
  if [ ${#_buf[@]} -gt 0 ]; then
    eval "${dest_name}=(\"\${_buf[@]}\")"
  fi
}

# Fill array named $3 with names in array $1 that are not in array $2.
names_only_in() {
  local -n _left=$1
  local -n _right=$2
  local -n _dest=$3
  local -A _r=()
  local p
  _dest=()
  if [ ${#_right[@]} -gt 0 ]; then
    for p in "${_right[@]}"; do
      _r["$p"]=1
    done
  fi
  if [ ${#_left[@]} -gt 0 ]; then
    for p in "${_left[@]}"; do
      if [ -z "${_r[$p]+x}" ]; then
        _dest+=("$p")
      fi
    done
  fi
}

i=0
while [ "$i" -lt "$n" ]; do
  msg_c="${REFLOG[$i]#*$'\t'}"
  case "$msg_c" in
    commit:*|"commit (amend):"*|"commit (initial):"*) ;;
    *) i=$((i + 1)); continue ;;
  esac

  # Need the reset entry directly beneath it, and the pre-reset tip beneath that.
  j=$((i + 1)); k=$((i + 2))
  [ "$k" -lt "$n" ] || { i=$((i + 1)); continue; }

  msg_r="${REFLOG[$j]#*$'\t'}"
  case "$msg_r" in
    "reset: moving to "*) ;;
    *) i=$((i + 1)); continue ;;
  esac

  commit_sha="${REFLOG[$i]%%$'\t'*}"     # C  -- the commit that was created
  reset_to="${REFLOG[$j]%%$'\t'*}"       # P' -- where the reset landed HEAD
  pre_reset="${REFLOG[$k]%%$'\t'*}"      # O  -- the stale tip before the reset

  # C must sit directly on the reset position; otherwise this is not the shape.
  parent="$(git rev-parse --verify --quiet "${commit_sha}^" 2>/dev/null || true)"
  [ -n "$parent" ] || { i=$((i + 1)); continue; }
  [ "$parent" = "$reset_to" ] || { i=$((i + 1)); continue; }

  # THE DISCRIMINATOR. If the reset target is an ancestor of the pre-reset tip,
  # this is an ordinary `reset --soft HEAD~n` squash and the whole old tree is
  # supposed to be in the new commit. FM-266 is the other case: the target had
  # DIVERGED from the stale tip, so the old tree carries content that silently
  # reverts upstream work.
  if git merge-base --is-ancestor "$reset_to" "$pre_reset" 2>/dev/null; then
    i=$((i + 1)); continue
  fi

  in_push_range "$commit_sha" || { i=$((i + 1)); continue; }

  # Paths changed vs the new parent, MINUS paths the author actually touched
  # relative to the stale tip. What remains is content carried over verbatim
  # from the pre-reset tip -- unintended. Name-set difference rather than blob
  # comparison, because the headline FM-266 symptom is a DELETION: a file
  # present in the parent and absent from both O and C has no blob to compare.
  #
  # -z: a newline inside a path is a legal git name; --name-only without -z
  # makes those names ambiguous. Read NUL-delimited, never through $(...).
  git_diff_names changed_vs_parent "$reset_to" "$commit_sha"
  git_diff_names touched_by_author "$pre_reset" "$commit_sha"
  names_only_in changed_vs_parent touched_by_author unintended

  [ ${#unintended[@]} -gt 0 ] || { i=$((i + 1)); continue; }

  # SECOND DISCRIMINATOR -- suppress `reset --hard` / `--mixed`.
  # The reflog message is identical for all three reset modes, so mode is not
  # directly readable. But --hard/--mixed refresh the index/worktree to the
  # target, and the tell survives in the commit: a path where the pre-reset tip
  # and the target disagree, and the commit follows the TARGET. A stale index
  # can never produce that -- it holds the old tip's content by definition.
  # Absent this, an honest `reset --hard <diverged> && git rm <file> && commit`
  # is reported as unintended (observed: it was a real false positive here).
  names_only_in touched_by_author changed_vs_parent followed_parent
  [ ${#followed_parent[@]} -eq 0 ] || { i=$((i + 1)); continue; }

  FINDINGS=$((FINDINGS + 1))
  {
    echo "=============================================================="
    echo "FM-266 GUARD: commit contains files you did not intend."
    echo "=============================================================="
    echo "  commit         ${commit_sha}"
    echo "  reset onto     ${reset_to}   (its parent)"
    echo "  stale tip      ${pre_reset}  (HEAD before the reset)"
    echo
    echo "  The reset target had DIVERGED from the pre-reset tip, so --soft"
    echo "  left the index holding the old tree. These paths changed against"
    echo "  the new parent but were never touched by you in this window --"
    echo "  they are the stale index reverting upstream work:"
    echo
    _unint_sorted=()
    mapfile -d '' -t _unint_sorted < <(printf '%s\0' "${unintended[@]}" | LC_ALL=C sort -z)
    if [ ${#_unint_sorted[@]} -gt 0 ] && [ -z "${_unint_sorted[-1]}" ]; then
      unset '_unint_sorted[-1]'
    fi
    for p in "${_unint_sorted[@]}"; do
      printf '      %s\n' "$p"
    done
    echo
    echo "  Inspect before pushing:"
    echo "      git diff --stat ${reset_to} ${commit_sha}"
    echo "      git diff ${reset_to} ${commit_sha} -- <path>"
    echo
    echo "  Recover the way FM-266 was recovered: re-checkout cleanly"
    echo "  (git switch -C <branch> ${reset_to}), reapply ONLY the intended"
    echo "  change, and confirm 'git status --short' lists exactly it."
    echo
    echo "  Genuinely intended? Re-run with HINDSIGHT_ALLOW_STALE_RESET=1."
    echo "=============================================================="
  } >&2

  i=$((i + 1))
done

[ "$FINDINGS" -eq 0 ] || exit 2
exit 0
