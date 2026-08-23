#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORK="$BATS_TEST_TMPDIR/hooks-path"
  PRIMARY="$WORK/primary"
  LINKED="$WORK/linked"
  STALE="$WORK/stale"
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
  printf 'before hooks\n' >"$PRIMARY/README"
  git -C "$PRIMARY" add README
  git -C "$PRIMARY" commit -q --no-verify -m 'before hooks'
  PRE_HOOK_TIP="$(git -C "$PRIMARY" rev-parse HEAD)"

  mkdir -p "$PRIMARY/.githooks" "$PRIMARY/bin"
  write_marker_hook "$PRIMARY/.githooks/pre-commit" primary-v1
  write_marker_hook "$PRIMARY/.githooks/pre-push" primary-push-v1
  printf '#!/usr/bin/env bash\nexit 0\n' >"$PRIMARY/bin/verify-hook-worktree.sh"
  chmod +x "$PRIMARY/bin/verify-hook-worktree.sh"
  git -C "$PRIMARY" add .githooks/pre-commit .githooks/pre-push \
    bin/verify-hook-worktree.sh
  git -C "$PRIMARY" commit -q --no-verify -m baseline
  git -C "$PRIMARY" worktree add -q -b hook-fix "$LINKED"
  git -C "$PRIMARY" config --local core.hooksPath "$PRIMARY/.githooks"

  write_marker_hook "$LINKED/.githooks/pre-commit" linked-v2
  git -C "$LINKED" add .githooks/pre-commit
  git -C "$LINKED" commit -q --no-verify -m 'fix hook'
}

config_hash() {
  git hash-object "$PRIMARY/.git/config"
}

write_kill_at_config_handoff_git() {
  local fake_git="$1"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'case " $* " in' \
    '  *" config --local --replace-all core.hooksPath .githooks "*)' \
    '    printf "reached\n" >"$HANDOFF_MARKER"' \
    '    kill -KILL $$' \
    '    ;;' \
    'esac' \
    'exec "$REAL_GIT" "$@"' >"$fake_git"
  chmod +x "$fake_git"
}

write_bad_resolver_git() {
  local fake_git="$1"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'case " $* " in' \
    '  *" rev-parse --path-format=absolute --git-path hooks/pre-commit "*)' \
    '    printf "%s\n" "$BAD_RESOLUTION"' \
    '    exit 0' \
    '    ;;' \
    'esac' \
    'exec "$REAL_GIT" "$@"' >"$fake_git"
  chmod +x "$fake_git"
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

@test "installer rejects a worktree override before changing shared config" {
  make_linked_fixture
  git -C "$PRIMARY" config extensions.worktreeConfig true
  git -C "$LINKED" config --worktree core.hooksPath "$WORK/override-hooks"
  before="$(config_hash)"
  original="$(git -C "$LINKED" config --local --get core.hooksPath)"

  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"higher-priority"* ]]
  [ "$(git -C "$LINKED" config --local --get core.hooksPath)" = "$original" ]
  [ "$(config_hash)" = "$before" ]
}

@test "installer rejects a false relative resolution before changing shared config" {
  make_linked_fixture
  fake_bin="$WORK/fake-bin"
  mkdir -p "$fake_bin"
  real_git="$(command -v git)"
  write_bad_resolver_git "$fake_bin/git"
  before="$(config_hash)"
  original="$(git -C "$LINKED" config --local --get core.hooksPath)"

  run env PATH="$fake_bin:$PATH" REAL_GIT="$real_git" \
    BAD_RESOLUTION="$WORK/not-the-active-hook" \
    bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"resolves pre-commit"* ]]
  [ "$(git -C "$LINKED" config --local --get core.hooksPath)" = "$original" ]
  [ "$(config_hash)" = "$before" ]
}

@test "installer validates resolution even when local hooksPath is already relative" {
  make_linked_fixture
  git -C "$PRIMARY" config --local core.hooksPath .githooks
  fake_bin="$WORK/fake-bin"
  mkdir -p "$fake_bin"
  real_git="$(command -v git)"
  write_bad_resolver_git "$fake_bin/git"
  before="$(config_hash)"

  run env PATH="$fake_bin:$PATH" REAL_GIT="$real_git" \
    BAD_RESOLUTION="$WORK/not-the-active-hook" \
    bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"resolves pre-commit"* ]]
  [ "$(config_hash)" = "$before" ]
}

@test "installer refuses a stale registered worktree before retargeting the clone" {
  make_linked_fixture
  git -C "$PRIMARY" worktree add -q -b stale "$STALE"
  chmod -x "$STALE/.githooks/pre-push"
  before="$(config_hash)"
  original="$(git -C "$LINKED" config --local --get core.hooksPath)"

  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"registered worktree is not armed"* ]]
  [[ "$output" == *"$STALE/.githooks/pre-push"* ]]
  [ "$(git -C "$LINKED" config --local --get core.hooksPath)" = "$original" ]
  [ "$(config_hash)" = "$before" ]
}

@test "successful persisted install resolves every registered worktree locally" {
  make_linked_fixture
  git -C "$PRIMARY" worktree add -q -b third "$STALE"

  run_installer_from_linked

  [ "$(git -C "$PRIMARY" config --get core.hooksPath)" = .githooks ]
  [ "$(git -C "$LINKED" config --get core.hooksPath)" = .githooks ]
  [ "$(git -C "$STALE" config --get core.hooksPath)" = .githooks ]
  [ "$(git -C "$PRIMARY" rev-parse --path-format=absolute --git-path hooks/pre-commit)" = \
    "$PRIMARY/.githooks/pre-commit" ]
  [ "$(git -C "$LINKED" rev-parse --path-format=absolute --git-path hooks/pre-commit)" = \
    "$LINKED/.githooks/pre-commit" ]
  [ "$(git -C "$STALE" rev-parse --path-format=absolute --git-path hooks/pre-commit)" = \
    "$STALE/.githooks/pre-commit" ]
  [[ "$(git -C "$LINKED" config --show-origin --show-scope --get core.hooksPath)" == \
    $'local\tfile:'"$PRIMARY/.git/config"$'\t.githooks' ]]
  ! git -C "$LINKED" config --worktree --get core.hooksPath
}

@test "installer reaches terminal config handoff before a forced kill and changes nothing" {
  make_linked_fixture
  fake_bin="$WORK/fake-bin"
  mkdir -p "$fake_bin"
  real_git="$(command -v git)"
  handoff_marker="$WORK/handoff-reached"
  write_kill_at_config_handoff_git "$fake_bin/git"
  before_config="$(config_hash)"
  before_hooks="$(git hash-object "$LINKED/.githooks/pre-commit" "$LINKED/.githooks/pre-push")"
  before_modes="$(stat -c '%a %n' "$LINKED/.githooks/pre-commit" "$LINKED/.githooks/pre-push")"

  run env PATH="$fake_bin:$PATH" REAL_GIT="$real_git" \
    HANDOFF_MARKER="$handoff_marker" \
    bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -eq 137 ]
  [ "$(<"$handoff_marker")" = reached ]
  [ "$(config_hash)" = "$before_config" ]
  [ "$(git hash-object "$LINKED/.githooks/pre-commit" "$LINKED/.githooks/pre-push")" = "$before_hooks" ]
  [ "$(stat -c '%a %n' "$LINKED/.githooks/pre-commit" "$LINKED/.githooks/pre-push")" = "$before_modes" ]
  [ ! -e "$PRIMARY/.git/config.lock" ]
}

@test "real git config lock failure leaves the original config byte-for-byte unchanged" {
  make_linked_fixture
  before="$(config_hash)"
  : >"$PRIMARY/.git/config.lock"

  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"could not lock config file"* ]]
  [ "$(config_hash)" = "$before" ]
  [ -e "$PRIMARY/.git/config.lock" ]
  rm "$PRIMARY/.git/config.lock"
}

@test "installer rejects command-scope hooksPath injection before writing local config" {
  make_linked_fixture
  before="$(config_hash)"
  original="$(git -C "$LINKED" config --local --get core.hooksPath)"

  run env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath \
    GIT_CONFIG_VALUE_0="$WORK/command-hooks" \
    bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"command-scope Git configuration"* ]]
  [ "$(git -C "$LINKED" config --local --get core.hooksPath)" = "$original" ]
  [ "$(config_hash)" = "$before" ]
}

@test "installer rejects duplicate or included local hooksPath definitions" {
  make_linked_fixture
  git -C "$PRIMARY" config --local --add core.hooksPath "$WORK/second-hooks"
  before="$(config_hash)"

  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"exactly one direct local core.hooksPath"* ]]
  [ "$(config_hash)" = "$before" ]
}

@test "installer rejects a hooksPath supplied by a local include file" {
  make_linked_fixture
  git -C "$PRIMARY" config --local --unset-all core.hooksPath
  printf '[core]\n\thooksPath = %s\n' "$WORK/included-hooks" >"$WORK/included.gitconfig"
  git -C "$PRIMARY" config --local include.path "$WORK/included.gitconfig"
  before="$(config_hash)"

  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"direct local core.hooksPath"* ]]
  [ "$(config_hash)" = "$before" ]
}

@test "installer refuses repository-routing environment overrides" {
  make_linked_fixture
  before="$(config_hash)"

  run env GIT_DIR="$PRIMARY/.git" \
    bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"repository-routing Git environment"* ]]
  [ "$(config_hash)" = "$before" ]
}

@test "installer rejects symlinked required hooks without changing config" {
  make_linked_fixture
  mv "$LINKED/.githooks/pre-push" "$LINKED/.githooks/pre-push.real"
  ln -s pre-push.real "$LINKED/.githooks/pre-push"
  before="$(config_hash)"

  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"

  [ "$status" -ne 0 ]
  [[ "$output" == *"regular non-symlink executable"* ]]
  [ "$(config_hash)" = "$before" ]
}

@test "fresh clone install writes one local value and rerun preserves the whole config" {
  make_linked_fixture
  git -C "$PRIMARY" config --local --unset-all core.hooksPath

  run_installer_from_linked

  [ "$(git -C "$PRIMARY" config --local --get-all core.hooksPath)" = .githooks ]
  [ "$(git -C "$PRIMARY" config --local --get-all core.hooksPath | wc -l)" -eq 1 ]
  after_first="$(config_hash)"
  run_installer_from_linked
  [ "$(config_hash)" = "$after_first" ]
}

@test "real config directory permission failure preserves config and creates no lock" {
  make_linked_fixture
  before="$(config_hash)"
  chmod 0555 "$PRIMARY/.git"

  run bash -c 'cd "$1" && bash "$2/bin/install-hooks.sh"' \
    _ "$LINKED" "$REPO_ROOT"
  chmod 0755 "$PRIMARY/.git"

  [ "$status" -ne 0 ]
  [[ "$output" == *"could not lock config file"* ]]
  [ "$(config_hash)" = "$before" ]
  [ ! -e "$PRIMARY/.git/config.lock" ]
}

@test "concurrent installers cannot corrupt or duplicate shared config" {
  make_linked_fixture
  log_one="$WORK/install-one.log"
  log_two="$WORK/install-two.log"

  run bash -c '
    cd "$1"
    bash "$2/bin/install-hooks.sh" >"$3" 2>&1 & first=$!
    bash "$2/bin/install-hooks.sh" >"$4" 2>&1 & second=$!
    first_status=0
    second_status=0
    wait "$first" || first_status=$?
    wait "$second" || second_status=$?
    printf "%s %s\n" "$first_status" "$second_status"
  ' _ "$LINKED" "$REPO_ROOT" "$log_one" "$log_two"

  [ "$status" -eq 0 ]
  [[ "$output" == "0 0" || "$output" == "0 "* || "$output" == *" 0" ]]
  [ "$(git -C "$PRIMARY" config --local --get-all core.hooksPath)" = .githooks ]
  [ "$(git -C "$PRIMARY" config --local --get-all core.hooksPath | wc -l)" -eq 1 ]
  [ ! -e "$PRIMARY/.git/config.lock" ]
}

@test "installer handles linked worktree paths containing spaces" {
  WORK="$BATS_TEST_TMPDIR/hooks path"
  PRIMARY="$WORK/primary clone"
  LINKED="$WORK/linked tree"
  STALE="$WORK/stale tree"
  TRACE="$WORK/hook trace"
  export TRACE
  make_linked_fixture

  run_installer_from_linked

  [ "$(git -C "$LINKED" rev-parse --path-format=absolute --git-path hooks/pre-commit)" = \
    "$LINKED/.githooks/pre-commit" ]
}

@test "pre-commit reports actionable version skew through a real git commit" {
  make_linked_fixture
  cp "$REPO_ROOT/.githooks/pre-commit" "$PRIMARY/.githooks/pre-commit"
  rm "$LINKED/bin/verify-hook-worktree.sh"

  run git -C "$LINKED" commit -q --allow-empty -m 'version skew'

  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot verify the active worktree"* ]]
  [[ "$output" == *"bin/install-hooks.sh"* ]]
  [[ "$output" != *"No such file or directory"* ]]
}

@test "pre-push reports actionable version skew through a real git push" {
  make_linked_fixture
  cp "$REPO_ROOT/.githooks/pre-push" "$PRIMARY/.githooks/pre-push"
  cp "$REPO_ROOT/bin/check-reset-soft-commit.sh" "$LINKED/bin/check-reset-soft-commit.sh"
  chmod +x "$LINKED/bin/check-reset-soft-commit.sh"
  rm "$LINKED/bin/verify-hook-worktree.sh"
  bare="$WORK/origin.git"
  git init -q --bare "$bare"
  git -C "$LINKED" remote add origin "$bare"
  git -C "$LINKED" push -q --no-verify origin HEAD:refs/heads/hook-fix
  git -C "$LINKED" commit -q --allow-empty --no-verify -m 'version skew'

  run git -C "$LINKED" push -q origin HEAD:refs/heads/hook-fix

  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot verify the active worktree"* ]]
  [[ "$output" == *"bin/install-hooks.sh"* ]]
  [[ "$output" != *"No such file or directory"* ]]
}

@test "deleting a branch pre-push bypasses relative hooks while the old absolute hook still runs" {
  make_linked_fixture
  printf '#!/usr/bin/env bash\necho GUARD-RAN >&2\nexit 1\n' >"$PRIMARY/.githooks/pre-push"
  chmod +x "$PRIMARY/.githooks/pre-push"
  run_installer_from_linked
  bare="$WORK/origin.git"
  git init -q --bare "$bare"
  git -C "$LINKED" remote add origin "$bare"
  git -C "$LINKED" push -q --no-verify origin HEAD:refs/heads/hook-fix
  rm "$LINKED/.githooks/pre-push"
  git -C "$LINKED" commit -q --allow-empty --no-verify -m relative

  run git -C "$LINKED" push -q origin HEAD:refs/heads/hook-fix
  [ "$status" -eq 0 ]
  [[ "$output" != *"GUARD-RAN"* ]]

  git -C "$LINKED" commit -q --allow-empty --no-verify -m absolute
  git -C "$PRIMARY" config --local core.hooksPath "$PRIMARY/.githooks"
  run git -C "$LINKED" push -q origin HEAD:refs/heads/hook-fix
  [ "$status" -ne 0 ]
  [[ "$output" == *"GUARD-RAN"* ]]
}

@test "a newly added stale worktree remains an explicitly measured relative-hook bypass" {
  make_linked_fixture
  run_installer_from_linked
  git -C "$PRIMARY" worktree add -q -b pre-hooks "$STALE" "$PRE_HOOK_TIP"
  [ ! -e "$STALE/.githooks/pre-commit" ]

  run git -C "$STALE" commit -q --allow-empty -m 'no branch hook exists'

  [ "$status" -eq 0 ]
}

@test "README calls branch-controlled hooks an accident tripwire and names lifecycle bypasses" {
  run grep -F 'active branch controls the hook bytes' "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]
  run grep -F 'accident tripwire, not a security or merge gate' "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]
  run grep -F 'new worktree created from an older revision' "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]
}
