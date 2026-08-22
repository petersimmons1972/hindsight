#!/usr/bin/env bats
# Contract tests for bin/land.sh — the only sanctioned way to merge in this repo.
#
# require-real-ci.sh has existed since Phase 0 and gated NOTHING: it was
# exercised only by its own bats suite in CI. PLAN-TDD R7 says landing runs it,
# never a human reading of `gh pr view`. This suite pins the lander that makes
# R7 a mechanism instead of a sentence (Law 1: a rule becomes a mechanism or a
# principle, never a third thing).
#
# Every case injects a rollup with --json-file so no test touches the network.

setup() {
  LAND="$BATS_TEST_DIRNAME/../land.sh"
  FIXTURES="$BATS_TEST_DIRNAME/fixtures"
}

# ---- the gate actually gates ------------------------------------------------

@test "L1: refuses to merge when the rollup is all-queued (the FM-149 shape)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t11_many_queued_one_success.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

@test "L2: refuses when a required check has an EMPTY conclusion (renders blank, not red)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t17_queued_with_success_conclusion.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

@test "L3: refuses on a malformed rollup rather than treating unparseable as clean" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t14_malformed_truncated.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

@test "L4: refuses on a null rollup (zero checks reported is an ERROR, not a pass)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t15_null_rollup.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

# ---- and it passes the good case, or it is just a brake ---------------------

@test "L5: an all-success rollup PASSES the gate (both directions, not just refusal)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  [[ "$output" == *"GATE PASSED"* ]]
}

# ---- dry-run is the default -------------------------------------------------

@test "L6: without --merge it does NOT merge, even on a green rollup" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  [[ "$output" == *"DRY RUN"* ]]
  [[ "$output" != *"Merging"* ]]
}

@test "L7: the undo for a merge is printed BEFORE the merge, not after (Law 3)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  # Assert the actual recovery COMMANDS, not the word "UNDO". Asserting the word
  # alone let a mutant that deleted the whole journal header survive, because
  # the "=== END UNDO ===" trailer still matched.
  [[ "$output" == *"git revert"* ]]
  [[ "$output" == *"gh pr reopen"* ]]
  [[ "$output" == *"gh pr reopen 99"* ]]
  [[ "$output" == *"refs/heads/"* ]]
  # and it must precede the verdict line, not trail it
  undo_line=$(printf '%s\n' "$output" | grep -n "git revert" | head -1 | cut -d: -f1)
  verdict_line=$(printf '%s\n' "$output" | grep -n "GATE PASSED" | head -1 | cut -d: -f1)
  [ -n "$undo_line" ] && [ -n "$verdict_line" ]
  [ "$undo_line" -lt "$verdict_line" ]
}

# ---- the refusal must not be defeatable by argument order -------------------

@test "L8: --merge before the json-file still refuses on a red rollup" {
  run bash "$LAND" 99 --merge --json-file "$FIXTURES/t11_many_queued_one_success.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"REFUSING"* ]]
}

# ---- usage ------------------------------------------------------------------

@test "L9: no PR number is a usage error, not a merge" {
  run bash "$LAND"
  [ "$status" -ne 0 ]
  [[ "$output" != *"Merging"* ]]
}

# ---- F3 (round 6): mutation survivors ---------------------------------------
# Nothing below touches the network: `gh` is shadowed by a fake on PATH that
# logs its argv and serves a canned rollup. Before this block, no land test
# passed --repo in any form, and no test ever reached the merge command at all,
# so the entire "what do we actually invoke" surface was unpinned.

_fake_gh() {  # $1 = exit code the fake should return for `gh pr merge`
  local merge_rc="${1:-0}"
  FAKE_BIN="$BATS_TEST_TMPDIR/fakegh"
  GH_LOG="$BATS_TEST_TMPDIR/gh_args.log"
  mkdir -p "$FAKE_BIN"
  : > "$GH_LOG"
  cat > "$FAKE_BIN/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$2" in
  merge) echo "gh: pr merge invoked" >&2; exit $merge_rc ;;
  view)  cat "$FIXTURES/t1_all_success.json"; exit 0 ;;
esac
exit 0
EOF
  chmod +x "$FAKE_BIN/gh"
}

@test "L10 (S6): --repo is forwarded to the gate — a different repo's checks must never certify this PR" {
  _fake_gh 0
  # LAND_SKIP_PLAN_INDEX: this case stubs gh on PATH without --json-file; the
  # plan-index checker would otherwise call the stub and fail closed.
  PATH="$FAKE_BIN:$PATH" LAND_SKIP_PLAN_INDEX=1 \
    run bash "$LAND" 99 --repo other/elsewhere
  [ "$status" -eq 0 ]
  grep -q -- "--repo other/elsewhere" "$GH_LOG"
  ! grep -q -- "--repo petersimmons1972/hindsight" "$GH_LOG"
}

@test "L11 (S16): --repo consumes its VALUE (two words), which is not mistaken for a second PR number" {
  run bash "$LAND" 99 --repo other/elsewhere --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  [[ "$output" != *"unexpected argument"* ]]
  [[ "$output" == *"GATE PASSED"* ]]
}

@test "L12 (S7): a FAILED gh pr merge is reported as a failure, never as a successful land" {
  _fake_gh 1
  PATH="$FAKE_BIN:$PATH" run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json" --merge
  [ "$status" -ne 0 ]
  [[ "$output" != *"merged PR"* ]]
  [[ "$output" == *"merge failed (exit 1)"* ]]
}

@test "L5 pin: a failed gh pr merge relays its original exit code" {
  _fake_gh 7
  PATH="$FAKE_BIN:$PATH" run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json" --merge
  [ "$status" -eq 7 ]
  [[ "$output" == *"merge failed (exit 7)"* ]]
  [[ "$output" != *"merged PR"* ]]
}

@test "L13 (S8): the merge command is exactly 'pr merge <PR> --squash --delete-branch' — no --admin, no bypass of GitHub's own required-check enforcement" {
  _fake_gh 0
  PATH="$FAKE_BIN:$PATH" run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json" --merge
  [ "$status" -eq 0 ]
  [[ "$output" == *"merged PR #99"* ]]
  merge_line="$(grep '^pr merge' "$GH_LOG")"
  [ "$merge_line" = "pr merge 99 --squash --delete-branch" ]
}

@test "L13b (S8): with --repo, the merge targets that repo and still carries no --admin" {
  _fake_gh 0
  PATH="$FAKE_BIN:$PATH" run bash "$LAND" 99 --repo other/elsewhere --json-file "$FIXTURES/t1_all_success.json" --merge
  [ "$status" -eq 0 ]
  merge_line="$(grep '^pr merge' "$GH_LOG")"
  [ "$merge_line" = "pr merge 99 --repo other/elsewhere --squash --delete-branch" ]
}

@test "L14 (S9): a stray second positional is rejected, never silently replacing the PR number" {
  run bash "$LAND" 99 7 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"unexpected argument: 7"* ]]
  [[ "$output" != *"GATE PASSED"* ]]
  [[ "$output" != *"PR #7"* ]]
}

@test "L15 (S12): an unknown option is rejected — a mistyped --json-file must not silently fall back to the network" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json" --mrege
  [ "$status" -eq 2 ]
  [[ "$output" == *"unknown option: --mrege"* ]]
  [[ "$output" != *"GATE PASSED"* ]]
}

@test "L16 (S13): no PR number prints USAGE — a usage error must never render as a CI refusal" {
  run bash "$LAND"
  [ "$status" -eq 2 ]
  [[ "$output" == *"usage:"* ]]
  [[ "$output" != *"REFUSING"* ]]
}

@test "L17 (S14): the gate's exit code is relayed verbatim — a contract failure is 2, never flattened to 1 (which means usage error)" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t5_required_failure.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"REFUSING"* ]]
}

@test "L18 (S15): the gate's own FAIL verdict — naming WHICH check was red — is printed, not swallowed" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t5_required_failure.json"
  [[ "$output" == *"FAIL: required check 'guard (pytest-release)' concluded 'FAILURE', not SUCCESS"* ]]
}

@test "L19 (S15): on the green path the gate's PASS line is printed too — that line IS the evidence" {
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS: all required checks (guard (pytest-release), guard (pytest-rest), guard (tools)) are COMPLETED/SUCCESS"* ]]
}

# ---- F4: the invocation banner must actually record the invocation ----------

@test "L20: the gate banner names the ARGUMENTS the gate was run with, not an empty list" {
  # Pre-existing bug found by the mutation sweep: the banner printed "$*" AFTER
  # the parse loop's shifts had already consumed it, so the line that claims to
  # record how the gate was invoked recorded nothing. An audit line that is
  # always blank is worse than none -- it reads as evidence of a check while
  # carrying no information about what was checked.
  run bash "$LAND" 99 --json-file "$FIXTURES/t1_all_success.json"
  [ "$status" -eq 0 ]
  banner="$(printf '%s\n' "$output" | grep '=== gate:' | head -1)"
  [[ "$banner" == *"99"* ]]
  [[ "$banner" == *"--json-file"* ]]
}
