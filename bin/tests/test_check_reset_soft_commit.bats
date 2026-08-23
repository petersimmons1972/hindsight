#!/usr/bin/env bats
# Tests for bin/check-reset-soft-commit.sh (FM-266, hindsight#111).
#
# Contract: exit 2 ONLY when the HEAD reflog shows a commit created directly on
# top of a reset onto a ref that had DIVERGED from the pre-reset tip, AND that
# commit carries paths the author never touched. Exit 0 otherwise.
#
# Every test builds a real throwaway git repo under BATS_TEST_TMPDIR and pins
# the relative core.hooksPath inside that repo, so no test can reach machine-wide
# ~/.config/git/hooks (which is this box's global core.hooksPath -- see FM-408).
#
# Each firing case is paired with a NEGATIVE CONTROL: the same file damage
# reached by the CORRECT procedure, which must stay silent. Without the pair, a
# test that fires unconditionally would still pass.

setup() {
  SCRIPT="$BATS_TEST_DIRNAME/../check-reset-soft-commit.sh"
  HOOK="$BATS_TEST_DIRNAME/../../.githooks/pre-push"
  REPO="$BATS_TEST_TMPDIR/repo"
  new_repo "$REPO"
  # The guard reads the reflog of the repo it is RUN IN. Without this cd it
  # would inspect the hindsight checkout instead of the fixture -- which is how
  # the first draft of these tests passed for the wrong reason.
  cd "$REPO" || return 1
}

new_repo() {
  local d="$1"
  git init -q -b main "$d"
  # Pin hooks INSIDE the throwaway worktree. Non-negotiable.
  mkdir -p "$d/.githooks"
  git -C "$d" config core.hooksPath .githooks
  git -C "$d" config user.name  "bats"
  git -C "$d" config user.email "bats@local"
  git -C "$d" config commit.gpgsign false
}

g() { git -C "$REPO" "$@"; }

# base commit shared by most scenarios
seed_base() {
  mkdir -p "$REPO/notes"
  echo "backlog v1" > "$REPO/notes/backlog.md"
  echo "readme v1"  > "$REPO/README.md"
  g add -A && g commit -qm base
}

# upstream branch gains a big test file (+ optionally a script)
seed_upstream() {
  g checkout -q -b upstream
  mkdir -p "$REPO/tests"
  seq 1 935 | sed 's/^/line /' > "$REPO/tests/test_big.py"
  if [ "${1:-}" = "with_script" ]; then
    mkdir -p "$REPO/scripts"; echo "run.sh UPSTREAM" > "$REPO/scripts/run.sh"
  fi
  g add -A && g commit -qm "upstream: real test file"
  g checkout -q main
}

# ---- T1: the actual FM-266 incident -------------------------------------

@test "T1: FM-266 shape (reset --soft onto diverged ref + narrow add) fires and names the deleted test file" {
  seed_base
  seed_upstream with_script
  echo "readme v1 + local edit" > "$REPO/README.md"
  g commit -qam "local-only divergent work"

  echo "backlog v2 -- the ONE intended change" > "$REPO/notes/backlog.md"
  g reset --soft upstream
  g add notes/backlog.md
  g commit -qm "notes: update backlog"

  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  # The headline symptom of the real incident: a silently deleted test file.
  [[ "$output" == *"tests/test_big.py"* ]]
  [[ "$output" == *"scripts/run.sh"* ]]
  [[ "$output" == *"README.md"* ]]
  # Discrimination, not just noise: the file the author DID stage is not blamed.
  [[ "$output" != *"notes/backlog.md"* ]]
}

@test "T1-NEG (negative control for T1): same divergence reconciled with reset --hard stays silent" {
  # Proves T1 can fail: identical repo shape and identical intended edit, but
  # the CORRECT procedure. If the guard fired on reflog shape alone rather than
  # on stale content, this would fire too.
  seed_base
  seed_upstream with_script
  echo "readme v1 + local edit" > "$REPO/README.md"
  g commit -qam "local-only divergent work"

  g reset --hard -q upstream
  echo "backlog v2 -- the ONE intended change" > "$REPO/notes/backlog.md"
  g add notes/backlog.md
  g commit -qm "notes: update backlog"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" != *"tests/test_big.py"* ]]
}

# ---- T2: deletion-only stale set (no blob exists to compare) -------------

@test "T2: deletion-only stale set fires (a name-set guard sees what a blob compare cannot)" {
  # Local main is simply behind upstream. The stale index deletes the upstream
  # file outright: it exists in the parent and in NEITHER the pre-reset tip nor
  # the new commit, so there is no pair of blobs to diff. This is the case a
  # blob-comparison implementation silently drops.
  seed_base
  seed_upstream

  echo "backlog v2" > "$REPO/notes/backlog.md"
  g reset --soft upstream
  g add notes/backlog.md
  g commit -qm "notes: update backlog"

  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [[ "$output" == *"tests/test_big.py"* ]]
  [[ "$output" != *"notes/backlog.md"* ]]
}

@test "T2-NEG (negative control for T2): the identical deletion, authored deliberately, stays silent" {
  # Proves T2 can fail: the commit ends up deleting exactly the same file, but
  # reached by the correct procedure (hard reset onto upstream, then an explicit
  # rm), so the deletion appears in diff(pre-reset-tip, commit) as authored work
  # and must NOT be reported. If the guard keyed on "file vanished" rather than
  # on "content carried over from the stale tip", this would fire.
  seed_base
  g checkout -q -b upstream
  mkdir -p "$REPO/tests"
  seq 1 935 | sed 's/^/line /' > "$REPO/tests/test_big.py"
  echo "readme UPSTREAM" > "$REPO/README.md"
  g add -A && g commit -qm "upstream: test file + readme"
  g checkout -q main
  echo "readme LOCAL" > "$REPO/README.md"
  g commit -qam "divergent local readme"

  g reset --hard -q upstream
  g rm -q -r tests
  echo "backlog v2" > "$REPO/notes/backlog.md"
  g add -A
  g commit -qm "drop the test file deliberately"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" != *"tests/test_big.py"* ]]
}

@test "T2-TIE (documented residual): --hard is indistinguishable when tip and target differ only in the disputed path" {
  # Pins the ONE false positive the header admits, so it is a known, tested
  # property rather than a surprise. Identical commit and identical reflog to
  # the FM-266 shape; nothing can separate them post hoc, so the guard reports.
  seed_base
  seed_upstream

  g reset --hard -q upstream
  g rm -q -r tests
  echo "backlog v2" > "$REPO/notes/backlog.md"
  g add -A
  g commit -qm "drop the test file deliberately"

  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [[ "$output" == *"tests/test_big.py"* ]]
}

# ---- T3: the legitimate reset --soft (squash) ----------------------------

@test "T3: legitimate 'reset --soft HEAD~2' squash does NOT fire (ancestor discriminator)" {
  seed_base
  echo a > "$REPO/a.txt"; g add -A; g commit -qm a
  echo b > "$REPO/b.txt"; g add -A; g commit -qm b

  g reset --soft HEAD~2
  g commit -qm "squashed a+b"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "T3-NEG (negative control for T3): the same reset --soft onto a DIVERGED ref does fire" {
  # Proves T3's silence comes from the ancestry test, not from the guard being
  # inert after any reset --soft.
  seed_base
  seed_upstream
  echo "readme local" > "$REPO/README.md"; g commit -qam "divergent"

  g reset --soft upstream
  echo x > "$REPO/x.txt"; g add x.txt
  g commit -qm "add x"

  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [[ "$output" == *"tests/test_big.py"* ]]
}

# ---- T4: normal work must never be blocked ------------------------------

@test "T4: a legitimate 40-file commit with no reset in the reflog stays silent" {
  seed_base
  for i in $(seq 1 40); do echo "content $i" > "$REPO/f$i.txt"; done
  g add -A
  g commit -qm "big but entirely intended commit"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "T5: a rebase (reset entries not adjacent to the commit) stays silent" {
  # rebase / pull --rebase write 'reset: moving to' entries onto non-ancestor
  # targets. The adjacency requirement is what keeps them quiet.
  seed_base
  g checkout -q -b feature
  echo f > "$REPO/f.txt"; g add -A; g commit -qm "feature work"
  g checkout -q main
  echo m > "$REPO/m.txt"; g add -A; g commit -qm "main work"
  g checkout -q feature
  g rebase -q main

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
}

# ---- T6: scoping and escape hatch ---------------------------------------

@test "T6: a commit outside the pushed range is not checked, the same commit inside it is" {
  seed_base
  seed_upstream
  echo "backlog v2" > "$REPO/notes/backlog.md"
  g reset --soft upstream
  g add notes/backlog.md
  g commit -qm "notes: update backlog"
  bad=$(g rev-parse HEAD)
  g branch -q other "$(g rev-parse upstream)"

  run bash "$SCRIPT" --push-tip "$(g rev-parse other)"
  [ "$status" -eq 0 ]

  run bash "$SCRIPT" --push-tip "$bad"
  [ "$status" -eq 2 ]
  [[ "$output" == *"tests/test_big.py"* ]]
}

@test "T7: HINDSIGHT_ALLOW_STALE_RESET=1 bypasses, and its absence does not" {
  seed_base
  seed_upstream
  echo "backlog v2" > "$REPO/notes/backlog.md"
  g reset --soft upstream
  g add notes/backlog.md
  g commit -qm "notes: update backlog"

  # NEGATIVE CONTROL is the second half: the identical repo without the escape
  # hatch must still fire, so a passing bypass test cannot be a dead guard.
  run env HINDSIGHT_ALLOW_STALE_RESET=1 bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"BYPASSED"* ]]

  run env -u HINDSIGHT_ALLOW_STALE_RESET bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [[ "$output" == *"tests/test_big.py"* ]]
}

# ---- T8: the hook itself, end to end ------------------------------------

@test "T8: the pre-push hook blocks the push, and no-ops in a repo without the guard" {
  seed_base
  seed_upstream
  echo "backlog v2" > "$REPO/notes/backlog.md"
  g reset --soft upstream
  g add notes/backlog.md
  g commit -qm "notes: update backlog"

  mkdir -p "$REPO/bin"
  cp "$SCRIPT" "$REPO/bin/check-reset-soft-commit.sh"
  cp "$BATS_TEST_DIRNAME/../verify-hook-worktree.sh" \
    "$REPO/bin/verify-hook-worktree.sh"
  chmod +x "$REPO/bin/check-reset-soft-commit.sh"
  chmod +x "$REPO/bin/verify-hook-worktree.sh"
  cp "$HOOK" "$REPO/.githooks/pre-push"
  chmod +x "$REPO/.githooks/pre-push"

  git init -q --bare "$BATS_TEST_TMPDIR/origin.git"
  g remote add origin "$BATS_TEST_TMPDIR/origin.git"

  run git -C "$REPO" push --force origin main
  [ "$status" -ne 0 ]
  [[ "$output" == *"tests/test_big.py"* ]]
  [[ "$output" == *"BLOCKED by the FM-266 guard"* ]]
  # The push really did not land.
  run git -C "$BATS_TEST_TMPDIR/origin.git" rev-parse --verify --quiet main
  [ "$status" -ne 0 ]

  # NEGATIVE CONTROL: same hook, guard script absent -> silent no-op, push OK.
  # This is the "degrades in repos it does not own" property.
  rm -f "$REPO/bin/check-reset-soft-commit.sh"
  run git -C "$REPO" push --force origin main
  [ "$status" -eq 0 ]
}

# ---- T9: a failed git read is not "nothing found" --------------------------

@test "T9: a failed reflog read is a loud refusal, not a silent pass" {
  # Pins the fail-open: `git reflog ... 2>/dev/null || true` plus mapfile
  # treated ANY reflog failure as zero findings and permitted the commit.
  seed_base
  wrap="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$wrap"
  real_git="$(command -v git)"
  cat >"$wrap/git" <<EOF
#!/usr/bin/env bash
if [ "\${1:-}" = "reflog" ]; then
  echo "injected: git reflog failing with 77" >&2
  exit 77
fi
exec "$real_git" "\$@"
EOF
  chmod +x "$wrap/git"

  run env PATH="$wrap:$PATH" bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"git reflog failed"* ]]
  [[ "$output" == *"77"* ]]
  [[ "$output" == *"unread reflog"* ]]
}
