#!/usr/bin/env bats
# bin/secret-scan.sh: the range it scans must include secrets that reach a PR
# through a merged side branch or an evil merge (hindsight PR #205 review).

# A key gitleaks' aws-access-token rule matches; built at runtime so this file
# does not itself carry a match.
side_secret() { printf 'aws_key = "%s%s"\n' AKIA QWERTYUIOPASDFGH; }
evil_secret() { printf 'aws_key = "%s%s"\n' AKIA ZXCVBNMLKJHGFDSA; }

setup() {
  export TMPDIR="$BATS_TEST_TMPDIR"
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  TOOL="$ROOT/bin/secret-scan.sh"
  REPO="$BATS_TEST_TMPDIR/repo"
  export SECRET_SCAN_REPO="$REPO"
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

  git init -q -b main "$REPO"
  g config user.email t@example.invalid
  g config user.name t
  commit_file r.txt root
  commit_file a.txt base
  BASE="$(g rev-parse HEAD)"
  g update-ref refs/remotes/origin/main "$BASE"

  # PR branch with a secret that arrives only through a merged side branch.
  g checkout -q -b feature
  commit_file b.txt f1
  g checkout -q -b side
  side_secret >"$REPO/side.txt"
  g add side.txt
  g commit -q -m sidesecret
  SIDE="$(g rev-parse HEAD)"
  g checkout -q feature
  g merge -q --no-ff side -m "merge side"
  commit_file c.txt f2
  SIDE_HEAD="$(g rev-parse HEAD)"

  # PR branch whose secret exists only in a merge commit's own resolution.
  g checkout -q -b evil "$BASE"
  commit_file y.txt y
  g checkout -q -b evilside
  commit_file x.txt x
  g checkout -q evil
  g merge -q --no-ff --no-commit evilside
  evil_secret >"$REPO/evil.txt"
  g add evil.txt
  g commit -q -m "evil merge"
  EVIL_HEAD="$(g rev-parse HEAD)"

  # Clean PR branch.
  g checkout -q -b clean "$BASE"
  commit_file d.txt d
  CLEAN_HEAD="$(g rev-parse HEAD)"
}

g() { git -C "$REPO" "$@"; }

commit_file() {
  echo "$2" >"$REPO/$1"
  g add "$1"
  g commit -q -m "$2"
}

# What `git log -p` (gitleaks' own input) shows for the printed options.
log_text() {
  local opts
  opts="$(bash "$TOOL" --print-log-opts "$@")"
  # shellcheck disable=SC2086 # gitleaks splits --log-opts on spaces too
  g log -p -U0 $opts
}

stub_gitleaks() {
  STUB="$BATS_TEST_TMPDIR/gitleaks-stub"
  STUB_LOG="$BATS_TEST_TMPDIR/gitleaks-args"
  cat >"$STUB" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" >"$STUB_LOG"
EOF
  chmod +x "$STUB"
  export GITLEAKS="$STUB"
}

require_gitleaks() {
  command -v gitleaks >/dev/null || skip "gitleaks not installed"
}

@test "control: gitleaks-action's first-parent range cannot see the side-branch secret" {
  run g log -p -U0 --no-merges --first-parent "$BASE^..$SIDE_HEAD"
  [ "$status" -eq 0 ]
  [[ "$output" != *QWERTYUIOPASDFGH* ]]
}

@test "pr range includes a secret introduced on a merged side branch" {
  run log_text pr "$BASE" "$SIDE_HEAD"
  [ "$status" -eq 0 ]
  [[ "$output" == *QWERTYUIOPASDFGH* ]]
}

@test "pr range includes a secret introduced only by an evil merge resolution" {
  run log_text pr "$BASE" "$EVIL_HEAD"
  [ "$status" -eq 0 ]
  [[ "$output" == *ZXCVBNMLKJHGFDSA* ]]
}

@test "pr scan hands gitleaks the full range without first-parent or no-merges" {
  stub_gitleaks
  run bash "$TOOL" pr "$BASE" "$SIDE_HEAD"
  [ "$status" -eq 0 ]
  grep -qx -- "--log-opts=--diff-merges=remerge $BASE..$SIDE_HEAD" "$STUB_LOG"
  args="$(cat "$STUB_LOG")"
  [[ "$args" != *first-parent* && "$args" != *no-merges* ]]
}

@test "unresolvable pr base exits 2 and never runs gitleaks" {
  stub_gitleaks
  run bash "$TOOL" pr 1111111111111111111111111111111111111111 "$SIDE_HEAD"
  [ "$status" -eq 2 ]
  [[ "$output" == *"is not a commit"* ]]
  [ ! -e "$STUB_LOG" ]
}

@test "missing gitleaks binary exits 2, not 0" {
  GITLEAKS="$BATS_TEST_TMPDIR/no-such-gitleaks" run bash "$TOOL" pr "$BASE" "$CLEAN_HEAD"
  [ "$status" -eq 2 ]
  [[ "$output" == *"not found"* ]]
}

@test "bad mode and wrong arity exit 2" {
  run bash "$TOOL" scan "$BASE" "$CLEAN_HEAD"
  [ "$status" -eq 2 ]
  run bash "$TOOL" pr "$BASE"
  [ "$status" -eq 2 ]
  run bash "$TOOL" push "$BASE" "$CLEAN_HEAD"
  [ "$status" -eq 2 ]
}

@test "push with a known before scans before..after including side-branch commits" {
  run log_text push "$BASE" "$SIDE_HEAD" feature
  [ "$status" -eq 0 ]
  [[ "$output" == *QWERTYUIOPASDFGH* ]]
}

@test "new-branch push scans commits no other remote branch holds" {
  g update-ref refs/remotes/origin/feature "$SIDE_HEAD"
  run bash "$TOOL" --print-log-opts push 0000000000000000000000000000000000000000 "$SIDE_HEAD" feature
  [ "$status" -eq 0 ]
  [ "$output" = "--diff-merges=remerge $SIDE_HEAD --not refs/remotes/origin/main" ]
  run log_text push 0000000000000000000000000000000000000000 "$SIDE_HEAD" feature
  [[ "$output" == *QWERTYUIOPASDFGH* ]]
  [[ "$output" != *"+base"* ]]
}

@test "force push with an unfetched before falls back instead of failing open" {
  run log_text push 2222222222222222222222222222222222222222 "$SIDE_HEAD" feature
  [ "$status" -eq 0 ]
  [[ "$output" == *QWERTYUIOPASDFGH* ]]
}

@test "deleted-branch push exits 0 without scanning" {
  stub_gitleaks
  run bash "$TOOL" push "$BASE" 0000000000000000000000000000000000000000 feature
  [ "$status" -eq 0 ]
  [[ "$output" == *"deleted"* ]]
  [ ! -e "$STUB_LOG" ]
}

@test "pushed branch name is only compared, never spliced into the scan range" {
  g update-ref "refs/remotes/origin/a" "$BASE"
  run bash "$TOOL" --print-log-opts push 0000000000000000000000000000000000000000 "$SIDE_HEAD" "x y"
  [ "$status" -eq 0 ]
  [ "$output" = "--diff-merges=remerge $SIDE_HEAD --not refs/remotes/origin/a refs/remotes/origin/main" ]
}

@test "real gitleaks: side-branch secret fails the scan" {
  require_gitleaks
  run bash "$TOOL" pr "$BASE" "$SIDE_HEAD"
  [ "$status" -eq 1 ]
  [[ "$output" == *"leaks found"* ]]
}

@test "real gitleaks: evil-merge secret fails the scan" {
  require_gitleaks
  run bash "$TOOL" pr "$BASE" "$EVIL_HEAD"
  [ "$status" -eq 1 ]
}

@test "real gitleaks: clean range passes" {
  require_gitleaks
  run bash "$TOOL" pr "$BASE" "$CLEAN_HEAD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"no leaks"* ]]
}

@test "real gitleaks: .gitleaksignore at the scanned repo root suppresses only its fingerprint" {
  require_gitleaks
  printf '%s:side.txt:aws-access-token:1\n' "$SIDE" >"$REPO/.gitleaksignore"
  cd "$BATS_TEST_TMPDIR"
  run bash "$TOOL" pr "$BASE" "$SIDE_HEAD"
  [ "$status" -eq 0 ]
  run bash "$TOOL" pr "$BASE" "$EVIL_HEAD"
  [ "$status" -eq 1 ]
}

@test "committed .gitleaksignore entries each suppress a real finding" {
  require_gitleaks
  ignore="$ROOT/.gitleaksignore"
  [ -s "$ignore" ]
  # A shared clone without the allowlist, so gitleaks cannot pick it up from
  # the scanned source directory.
  bare="$BATS_TEST_TMPDIR/bare.git"
  git clone -q --bare --shared "$ROOT" "$bare"
  mapfile -t entries < <(grep -v -e '^#' -e '^$' "$ignore")
  [ "${#entries[@]}" -gt 0 ]
  checked=0
  for fp in "${entries[@]}"; do
    commit="${fp%%:*}"
    git -C "$ROOT" cat-file -e "$commit^{commit}" 2>/dev/null || continue
    git -C "$bare" fetch -q "$ROOT" "$commit"
    report="$BATS_TEST_TMPDIR/report.json"
    # Without the allowlist the fingerprint is a live finding...
    cd "$BATS_TEST_TMPDIR"
    run gitleaks git --no-banner --log-opts="-1 $commit" \
      --report-format json --report-path "$report" "$bare"
    [ "$status" -eq 1 ]
    grep -qF "\"Fingerprint\": \"$fp\"" "$report"
    # ...and the committed allowlist suppresses all of that commit's findings.
    run gitleaks git --no-banner --log-opts="-1 $commit" \
      --gitleaks-ignore-path "$ignore" "$bare"
    [ "$status" -eq 0 ]
    checked=$((checked + 1))
  done
  [ "$checked" -gt 0 ] || skip "no allowlisted commit present in this checkout"
}
