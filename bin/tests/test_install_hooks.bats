#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORK="$BATS_TEST_TMPDIR/hooks-path"
  PRIMARY="$WORK/primary"
  LINKED="$WORK/linked"
  TRACE="$WORK/hook-trace"
  export TRACE
  GLOBAL_CONFIG="$WORK/global.gitconfig"

  mkdir -p "$WORK/global-hooks"
  printf '[core]\n\thooksPath = %s\n' "$WORK/global-hooks" >"$GLOBAL_CONFIG"
  export GIT_CONFIG_SYSTEM=/dev/null
  export GIT_CONFIG_GLOBAL="$GLOBAL_CONFIG"
}

write_marker_hook() {
  local path="$1"
  local marker="$2"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "%s" >>"$TRACE"\n' \
    "$marker" >"$path"
  chmod +x "$path"
}

make_linked_fixture() {
  git init -q "$PRIMARY"
  git -C "$PRIMARY" config user.name fixture
  git -C "$PRIMARY" config user.email fixture@example.invalid
  mkdir -p "$PRIMARY/.githooks"
  write_marker_hook "$PRIMARY/.githooks/pre-commit" primary-v1
  write_marker_hook "$PRIMARY/.githooks/pre-push" primary-push-v1
  git -C "$PRIMARY" add .githooks/pre-commit .githooks/pre-push
  git -C "$PRIMARY" commit -q --no-verify -m baseline
  git -C "$PRIMARY" worktree add -q -b hook-fix "$LINKED"
  git -C "$PRIMARY" config --local core.hooksPath "$PRIMARY/.githooks"

  write_marker_hook "$LINKED/.githooks/pre-commit" linked-v2
  git -C "$LINKED" add .githooks/pre-commit
  git -C "$LINKED" commit -q --no-verify -m 'fix hook'
}

run_installer_from_linked() {
  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"
  [ "$status" -eq 0 ]
}

@test "installer stores a shared relative hooksPath without changing global config and is idempotent" {
  make_linked_fixture
  global_before="$(git config --global --get core.hooksPath)"

  run_installer_from_linked

  [ "$(git -C "$LINKED" config --local --get core.hooksPath)" = .githooks ]
  [ "$(git -C "$PRIMARY" config --local --get core.hooksPath)" = .githooks ]
  [ "$(git config --global --get core.hooksPath)" = "$global_before" ]
  config_hash="$(git hash-object "$PRIMARY/.git/config")"

  run_installer_from_linked

  [ "$(git hash-object "$PRIMARY/.git/config")" = "$config_hash" ]
  [ "$(git config --global --get core.hooksPath)" = "$global_before" ]
}

@test "real commits select the stale primary hook before install and the linked hook afterward" {
  make_linked_fixture
  : >"$TRACE"

  git -C "$LINKED" commit -q --allow-empty -m before
  [ "$(<"$TRACE")" = primary-v1 ]

  run_installer_from_linked
  : >"$TRACE"
  git -C "$LINKED" commit -q --allow-empty -m after

  [ "$(<"$TRACE")" = linked-v2 ]
}

@test "a hook fix at origin main runs in a linked worktree while the primary checkout stays stale" {
  make_linked_fixture
  run_installer_from_linked
  fixed_tip="$(git -C "$LINKED" rev-parse HEAD)"
  git -C "$LINKED" update-ref refs/remotes/origin/main "$fixed_tip"

  grep -Fq primary-v1 "$PRIMARY/.githooks/pre-commit"
  origin_hook="$(git -C "$LINKED" show origin/main:.githooks/pre-commit)"
  [[ "$origin_hook" == *linked-v2* ]]
  : >"$TRACE"
  git -C "$LINKED" commit -q --allow-empty -m 'post-merge proof'

  [ "$(<"$TRACE")" = linked-v2 ]
  grep -Fq primary-v1 "$PRIMARY/.githooks/pre-commit"
}

@test "one relative shared setting resolves hooks inside each existing worktree" {
  make_linked_fixture
  run_installer_from_linked

  [ "$(git -C "$PRIMARY" rev-parse --path-format=absolute --git-path hooks/pre-commit)" = \
    "$PRIMARY/.githooks/pre-commit" ]
  [ "$(git -C "$LINKED" rev-parse --path-format=absolute --git-path hooks/pre-commit)" = \
    "$LINKED/.githooks/pre-commit" ]
}

@test "hook-path verifier accepts direct invocation from the active worktree" {
  make_linked_fixture

  run bash -c 'cd "$1" && bash "$2/bin/verify-hook-worktree.sh" "$1/.githooks/pre-commit"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "pre-commit fails loudly when Git selects a sibling checkout hook" {
  make_linked_fixture
  mkdir -p "$LINKED/bin"
  cp "$REPO_ROOT/bin/verify-hook-worktree.sh" "$LINKED/bin/verify-hook-worktree.sh"
  cp "$REPO_ROOT/.githooks/pre-commit" "$PRIMARY/.githooks/pre-commit"

  run bash -c 'cd "$1" && bash "$2"' \
    _ "$LINKED" "$PRIMARY/.githooks/pre-commit"

  [ "$status" -ne 0 ]
  [[ "$output" == *"selected a hook from another worktree"* ]]
  [[ "$output" == *"bin/install-hooks.sh"* ]]
}

@test "pre-push fails loudly when Git selects a sibling checkout hook" {
  make_linked_fixture
  mkdir -p "$LINKED/bin"
  cp "$REPO_ROOT/bin/verify-hook-worktree.sh" "$LINKED/bin/verify-hook-worktree.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$LINKED/bin/check-reset-soft-commit.sh"
  chmod +x "$LINKED/bin/check-reset-soft-commit.sh"
  cp "$REPO_ROOT/.githooks/pre-push" "$PRIMARY/.githooks/pre-push"

  run bash -c 'cd "$1" && bash "$2" </dev/null' \
    _ "$LINKED" "$PRIMARY/.githooks/pre-push"

  [ "$status" -ne 0 ]
  [[ "$output" == *"selected a hook from another worktree"* ]]
  [[ "$output" == *"bin/install-hooks.sh"* ]]
}
