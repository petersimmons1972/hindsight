#!/usr/bin/env bash
# Scan the commits a push or pull request introduces for secrets with gitleaks.
#
# Usage:
#   bin/secret-scan.sh [--print-log-opts] pr   <base-sha>   <head-sha>
#   bin/secret-scan.sh [--print-log-opts] push <before-sha> <after-sha> <branch>
#
# Why not gitleaks/gitleaks-action: it scans with
# `--no-merges --first-parent base^..head`, so a secret committed on a side
# branch and merged into the PR branch is never read (hindsight PR #205
# review). This script scans every commit in the range instead, and uses
# `--diff-merges=remerge` so a merge commit contributes exactly what its
# resolution changed (an "evil merge" secret) without re-reporting the
# already-scanned contents of the branches it joins.
#
# gitleaks exits 0 when `git log` fails underneath it, so every git input is
# validated here first and any failure exits 2. Exit 1 means leaks were found.
# Reviewed false positives belong in .gitleaksignore at the repo root.
#
# Env: GITLEAKS (binary, default "gitleaks"); SECRET_SCAN_REPO (default ".").
set -euo pipefail

die() {
  echo "secret-scan: ERROR: $*" >&2
  exit 2
}

print_only=0
if [[ "${1:-}" == "--print-log-opts" ]]; then
  print_only=1
  shift
fi

repo="${SECRET_SCAN_REPO:-.}"
zero_sha="0000000000000000000000000000000000000000"

is_commit() {
  [[ -n "$1" ]] && git -C "$repo" cat-file -e "$1^{commit}" 2>/dev/null
}

mode="${1:-}"
case "$mode" in
  pr)
    [[ $# -eq 3 ]] || die "usage: $0 [--print-log-opts] pr <base-sha> <head-sha>"
    base="$2"
    head="$3"
    is_commit "$head" || die "PR head '$head' is not a commit in $repo (checkout needs fetch-depth: 0)"
    is_commit "$base" || die "PR base '$base' is not a commit in $repo (checkout needs fetch-depth: 0)"
    range=("$base..$head")
    ;;
  push)
    [[ $# -eq 4 ]] || die "usage: $0 [--print-log-opts] push <before-sha> <after-sha> <branch>"
    before="$2"
    head="$3"
    branch="$4"
    if [[ "$head" == "$zero_sha" ]]; then
      echo "secret-scan: branch '$branch' was deleted; nothing to scan"
      exit 0
    fi
    is_commit "$head" || die "pushed commit '$head' is not a commit in $repo (checkout needs fetch-depth: 0)"
    if [[ "$before" != "$zero_sha" ]] && is_commit "$before"; then
      range=("$before..$head")
    else
      # New branch, or a force push whose old tip was not fetched: scan what no
      # other remote branch already holds. Those commits are scanned when they
      # are pushed to their own branch.
      range=("$head")
      others=()
      while IFS= read -r ref; do
        [[ "$ref" == "refs/remotes/origin/$branch" || "$ref" == "refs/remotes/origin/HEAD" ]] && continue
        others+=("$ref")
      done < <(git -C "$repo" for-each-ref --format='%(refname)' refs/remotes/origin)
      if [[ ${#others[@]} -gt 0 ]]; then
        range+=(--not "${others[@]}")
      fi
    fi
    ;;
  *)
    die "usage: $0 [--print-log-opts] pr <base-sha> <head-sha> | push <before-sha> <after-sha> <branch>"
    ;;
esac

log_opts=(--diff-merges=remerge "${range[@]}")
# gitleaks splits --log-opts on single spaces; refuse anything that would split
# wrongly instead of scanning a silently different range.
for arg in "${log_opts[@]}"; do
  [[ "$arg" =~ [[:space:]] ]] && die "log option '$arg' contains whitespace"
done

# Same arguments gitleaks will hand to `git log -p`; this proves the range and
# --diff-merges=remerge (git >= 2.36) are accepted before gitleaks can mask a
# git failure as a clean scan.
git -C "$repo" log -p -U0 "${log_opts[@]}" >/dev/null \
  || die "git log rejected the scan range: ${log_opts[*]}"

if [[ $print_only -eq 1 ]]; then
  printf '%s\n' "${log_opts[*]}"
  exit 0
fi

gitleaks_bin="${GITLEAKS:-gitleaks}"
command -v "$gitleaks_bin" >/dev/null || die "gitleaks binary '$gitleaks_bin' not found"

commits="$(git -C "$repo" rev-list --count "${range[@]}")"
echo "secret-scan: scanning $commits commit(s): ${log_opts[*]}"

set +e
"$gitleaks_bin" git --no-banner --redact --exit-code 1 \
  --log-opts="${log_opts[*]}" "$repo"
rc=$?
set -e
case "$rc" in
  0) echo "secret-scan: no leaks in $commits commit(s)" ;;
  1) echo "secret-scan: leaks found (see above); allowlist only reviewed false positives in .gitleaksignore" >&2 ;;
  *) echo "secret-scan: ERROR: gitleaks exited $rc" >&2 ;;
esac
exit "$rc"
