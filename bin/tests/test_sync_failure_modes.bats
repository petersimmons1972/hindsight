#!/usr/bin/env bats
# Contract tests for the failure-mode distributor.  Every consumer below is a
# disposable git repository; the sync tool is never applied to a real project.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORK="$(mktemp -d)"
  STAGE="$WORK/stage"
  CONSUMERS="$WORK/consumers.conf"
  OWNERSHIP_MARKER='<!-- hindsight: vendored failure-mode catalog -->'
  mkdir -p "$STAGE/bin" "$STAGE/catalog"
  # Exercise a fresh copy of the checked-out tool.  This keeps the red run from
  # letting the old, unsafe implementation consult its real consumer config.
  cp "$ROOT/bin/sync-failure-modes.sh" "$STAGE/bin/sync-failure-modes.sh"
  cp "$ROOT/bin/_sync_write.py" "$STAGE/bin/_sync_write.py" 2>/dev/null || true
  cp "$ROOT/bin/checkin-lint-core.sh" "$STAGE/bin/checkin-lint-core.sh"
  cp "$ROOT/catalog/failure-modes.md" "$STAGE/catalog/failure-modes.md"
  ln -s "$CONSUMERS" "$STAGE/bin/failure-modes-projects.conf"
  TOOL="$STAGE/bin/sync-failure-modes.sh"
  SOURCE="$STAGE/catalog/failure-modes.md"
}

make_owned_target() {
  local repo="$1" target
  target="$(target_for "$repo")"
  mkdir -p "$(dirname "$target")"
  write_owned_copy "$target"
  printf '%s' "$target"
}

teardown() {
  rm -rf "$WORK"
}

make_repo() {
  local name="$1"
  local repo="$WORK/$name"
  mkdir -p "$repo"
  git -C "$repo" init -q
  git -C "$repo" config user.email sync-test@example.invalid
  git -C "$repo" config user.name sync-test
  printf '%s\n' "$repo" >>"$CONSUMERS"
  printf '%s' "$repo"
}

target_for() {
  printf '%s/docs/vendor/hindsight/failure-modes.md' "$1"
}

file_hash() {
  sha256sum "$1" | awk '{print $1}'
}

write_owned_copy() {
  printf '%s\n' '<!-- hindsight: vendored failure-mode catalog -->' >"$1"
  cat "$SOURCE" >>"$1"
}

@test "T1: one unmakeable target records a failure and still attempts all 12 consumers" {
  local repo i
  for i in $(seq 1 12); do
    repo="$(make_repo "repo-$i")"
    if [ "$i" -eq 3 ]; then
      mkdir -p "$repo/docs"
      : >"$repo/docs/vendor"
    fi
  done

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"attempted=12"* ]]
  [[ "$output" == *"succeeded=11"* ]]
  [[ "$output" == *"failed=1"* ]]
}

@test "T2: an empty consumer list fails loudly with a zero-attempt summary" {
  : >"$CONSUMERS"

  run bash "$TOOL" --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"attempted=0"* ]]
  [[ "$output" == *"succeeded=0"* ]]
  [[ "$output" == *"failed=0"* ]]
}

@test "T3: an existing foreign target is refused without a write" {
  local repo target before
  repo="$(make_repo foreign)"
  target="$(target_for "$repo")"
  mkdir -p "$(dirname "$target")"
  printf '%s\n' 'foreign ownership marker' >"$target"
  before="$(file_hash "$target")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"refusing foreign target"* ]]
  [ "$(file_hash "$target")" = "$before" ]
}

@test "T4: a consumer target is namespaced beneath docs/vendor/hindsight" {
  local repo target
  repo="$(make_repo namespaced)"
  target="$(target_for "$repo")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -eq 0 ]
  [ -f "$target" ]
  [ ! -e "$repo/docs/failure-modes.md" ]
}

@test "T5: the pre-write undo journal records prior states and restores them exactly" {
  local absent untracked tracked target_untracked target_tracked journal tracked_before untracked_before
  absent="$(make_repo absent)"
  untracked="$(make_repo untracked)"
  tracked="$(make_repo tracked)"
  target_untracked="$(target_for "$untracked")"
  target_tracked="$(target_for "$tracked")"
  mkdir -p "$(dirname "$target_untracked")" "$(dirname "$target_tracked")"
  printf '%s\n%s\n' "$OWNERSHIP_MARKER" 'untracked prior content' >"$target_untracked"
  printf '%s\n%s\n' "$OWNERSHIP_MARKER" 'tracked prior content' >"$target_tracked"
  git -C "$tracked" add docs/vendor/hindsight/failure-modes.md
  git -C "$tracked" commit -qm seed
  tracked_before="$(file_hash "$target_tracked")"
  untracked_before="$(file_hash "$target_untracked")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -eq 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  [ -n "$journal" ]
  [ -f "$journal" ]
  journal_line="$(awk '/^UNDO JOURNAL:/ { print NR; exit }' <<<"$output")"
  first_write_line="$(awk '/^UPDATED:/ { print NR; exit }' <<<"$output")"
  [ "$journal_line" -lt "$first_write_line" ]
  grep -Fq "$absent" "$journal"
  grep -Fq 'absent' "$journal"
  grep -Fq 'untracked' "$journal"
  grep -Fq 'tracked+hash' "$journal"

  run bash "$TOOL" --undo "$journal"

  [ "$status" -eq 0 ]
  [ ! -e "$(target_for "$absent")" ]
  [ "$(file_hash "$target_untracked")" = "$untracked_before" ]
  [ "$(file_hash "$target_tracked")" = "$tracked_before" ]
}

@test "T6: an unknown argument aborts without falling back to any consumer file" {
  local repo target
  repo="$(make_repo no-fallback)"
  target="$(target_for "$repo")"

  run bash "$TOOL" --bogus-flag

  [ "$status" -ne 0 ]
  [[ "$output" == *"unknown option: --bogus-flag"* ]]
  [ ! -e "$target" ]
}

@test "T7: dry-run is the default and --apply requires a non-empty consumers path" {
  local repo target
  repo="$(make_repo dry-run)"
  target="$(target_for "$repo")"

  run bash "$TOOL" --consumers "$CONSUMERS"

  [ "$status" -eq 0 ]
  [[ "$output" == *"DRY RUN"* ]]
  [ ! -e "$target" ]

  run bash "$TOOL" --apply

  [ "$status" -ne 0 ]
  [[ "$output" == *"--consumers"* ]]
}

@test "D8: an unchanged target is attempted and counted separately from failures" {
  local repo target
  repo="$(make_repo current)"
  target="$(target_for "$repo")"
  mkdir -p "$(dirname "$target")"
  write_owned_copy "$target"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -eq 0 ]
  [[ "$output" == *"attempted=1"* ]]
  [[ "$output" == *"succeeded=0"* ]]
  [[ "$output" == *"unchanged=1"* ]]
  [[ "$output" == *"failed=0"* ]]
}

@test "symlinked target outside its consumer is refused without changing the link destination" {
  local repo target outside before
  repo="$(make_repo symlink-outside)"
  target="$(target_for "$repo")"
  outside="$WORK/outside-catalog.md"
  printf '%s\n%s\n' "$OWNERSHIP_MARKER" 'outside prior content' >"$outside"
  before="$(file_hash "$outside")"
  mkdir -p "$(dirname "$target")"
  ln -s "$outside" "$target"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"symlinked target: $target -> $outside"* ]]
  [ "$(file_hash "$outside")" = "$before" ]
  [ -L "$target" ]
}

@test "dangling target symlink records its resolved path and undo refuses it outside the consumer root" {
  local repo target destination journal
  repo="$(make_repo dangling-symlink)"
  target="$(target_for "$repo")"
  destination="$WORK/missing-outside-catalog.md"
  mkdir -p "$(dirname "$target")"
  ln -s "$destination" "$target"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  [ -f "$journal" ]
  grep -Fq "$destination" "$journal"
  ! grep -Fq "$target"$'\tabsent\t' "$journal"

  run bash "$TOOL" --undo "$journal"

  [ "$status" -ne 0 ]
  [ -L "$target" ]
  [ "$(readlink "$target")" = "$destination" ]
}

@test "regular owned target still syncs and undoes cleanly" {
  local repo target before journal
  repo="$(make_repo regular-control)"
  target="$(target_for "$repo")"
  mkdir -p "$(dirname "$target")"
  printf '%s\n%s\n' "$OWNERSHIP_MARKER" 'regular prior content' >"$target"
  before="$(file_hash "$target")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -eq 0 ]
  [ -f "$target" ]
  [ ! -L "$target" ]
  [ "$(file_hash "$target")" != "$before" ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"

  run bash "$TOOL" --undo "$journal"

  [ "$status" -eq 0 ]
  [ -f "$target" ]
  [ ! -L "$target" ]
  [ "$(file_hash "$target")" = "$before" ]
}

@test "symlinked ancestors are refused in apply and dry-run without changing outside files" {
  local repo outside form depth target before relative_target
  for form in absolute relative; do
    for depth in vendor hindsight; do
      repo="$(make_repo "ancestor-$form-$depth")"
      outside="$WORK/outside-$form-$depth"
      mkdir -p "$outside"
      if [ "$depth" = vendor ]; then
        mkdir -p "$repo/docs"
        mkdir -p "$outside/hindsight"
        target="$outside/hindsight/failure-modes.md"
        if [ "$form" = absolute ]; then
          ln -s "$outside" "$repo/docs/vendor"
        else
          relative_target="$(realpath --relative-to="$repo/docs" "$outside")"
          ln -s "$relative_target" "$repo/docs/vendor"
        fi
      else
        mkdir -p "$repo/docs/vendor"
        target="$outside/failure-modes.md"
        if [ "$form" = absolute ]; then
          ln -s "$outside" "$repo/docs/vendor/hindsight"
        else
          relative_target="$(realpath --relative-to="$repo/docs/vendor" "$outside")"
          ln -s "$relative_target" "$repo/docs/vendor/hindsight"
        fi
      fi
      printf '%s\n' "outside-$form-$depth" >"$target"
      before="$(file_hash "$target")"

      run bash "$TOOL" --consumers "$CONSUMERS"
      [ "$status" -ne 0 ]
      [[ "$output" == *"intended="* ]]
      [[ "$output" == *"resolved="* ]]
      [ "$(file_hash "$target")" = "$before" ]

      run bash "$TOOL" --apply --consumers "$CONSUMERS"
      [ "$status" -ne 0 ]
      [[ "$output" == *"intended="* ]]
      [[ "$output" == *"resolved="* ]]
      [ "$(file_hash "$target")" = "$before" ]
    done
  done
}

@test "a git-tracked symlinked ancestor is refused without changing its outside file" {
  local repo outside target before
  repo="$(make_repo tracked-ancestor)"
  outside="$WORK/tracked-outside"
  mkdir -p "$repo/docs" "$outside/hindsight"
  printf '%s\n' outside >"$outside/hindsight/failure-modes.md"
  before="$(file_hash "$outside/hindsight/failure-modes.md")"
  ln -s "$outside" "$repo/docs/vendor"
  git -C "$repo" add docs/vendor
  git -C "$repo" commit -qm tracked-link

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"intended="* ]]
  [ "$(file_hash "$outside/hindsight/failure-modes.md")" = "$before" ]
}

@test "a hardlinked owned target is refused without changing its outside inode" {
  local repo target outside before
  repo="$(make_repo hardlink)"
  target="$(target_for "$repo")"
  outside="$WORK/outside-hardlink.md"
  mkdir -p "$(dirname "$target")"
  printf '%s\n%s\n' "$OWNERSHIP_MARKER" outside >"$outside"
  ln "$outside" "$target"
  before="$(file_hash "$outside")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"hardlinked target"* ]]
  [ "$(file_hash "$outside")" = "$before" ]
}

@test "a directory target fails cleanly and leaves a usable journal for other consumers" {
  local healthy directory healthy_target before journal
  healthy="$(make_repo healthy-before-directory)"
  directory="$(make_repo directory-target)"
  healthy_target="$(target_for "$healthy")"
  mkdir -p "$(dirname "$healthy_target")" "$(target_for "$directory")"
  printf '%s\n%s\n' "$OWNERSHIP_MARKER" old >"$healthy_target"
  before="$(file_hash "$healthy_target")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"directory target"* ]]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  [ -f "$journal" ]
  run bash "$TOOL" --undo "$journal"
  [ "$status" -eq 0 ]
  [ "$(file_hash "$healthy_target")" = "$before" ]
}

@test "a tracked symlink target is journaled as tracked+link but undo refuses its resolved outside path" {
  local repo target destination journal
  repo="$(make_repo tracked-leaf-link)"
  target="$(target_for "$repo")"
  destination="$WORK/tracked-link-destination"
  mkdir -p "$(dirname "$target")"
  ln -s "$destination" "$target"
  git -C "$repo" add docs/vendor/hindsight/failure-modes.md
  git -C "$repo" commit -qm tracked-link

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  grep -Fq $'tracked+link\t' "$journal"
  run bash "$TOOL" --undo "$journal"
  [ "$status" -ne 0 ]
  [ -L "$target" ]
  [ "$(readlink "$target")" = "$destination" ]
}

@test "a first sync creates a previously absent target" {
  local repo target
  repo="$(make_repo first-sync)"
  target="$(target_for "$repo")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -eq 0 ]
  [ -f "$target" ]
  grep -Fqx "$OWNERSHIP_MARKER" "$target"
}

@test "a failed undo copy leaves the current target intact" {
  local repo target before current journal
  repo="$(make_repo undo-copy-failure)"
  target="$(target_for "$repo")"
  mkdir -p "$(dirname "$target")" "$WORK/fakebin"
  printf '%s\n%s\n' "$OWNERSHIP_MARKER" old >"$target"
  before="$(file_hash "$target")"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"
  [ "$status" -eq 0 ]
  current="$(file_hash "$target")"
  [ "$current" != "$before" ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  printf '%s\n' '#!/usr/bin/env bash' 'exit 1' >"$STAGE/bin/_sync_write.py"
  chmod +x "$STAGE/bin/_sync_write.py"

  run bash "$TOOL" --undo "$journal"

  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot restore undo backup"* ]]
  [ "$(file_hash "$target")" = "$current" ]
}

@test "B2: undo refuses a journal target whose parent now escapes its recorded consumer root" {
  local repo target journal outside before
  repo="$(make_repo undo-escape)"
  target="$(make_owned_target "$repo")"
  run bash "$TOOL" --apply --consumers "$CONSUMERS"
  [ "$status" -eq 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  outside="$WORK/outside-undo"
  mkdir -p "$outside"
  printf '%s\n' outside >"$outside/failure-modes.md"
  before="$(file_hash "$outside/failure-modes.md")"
  rm -f -- "$target"
  rmdir "$repo/docs/vendor/hindsight"
  ln -s "$outside" "$repo/docs/vendor/hindsight"

  run bash "$TOOL" --undo "$journal"

  [ "$status" -ne 0 ]
  [[ "$output" == *"refuses undo target outside recorded consumer root"* ]]
  [ "$(file_hash "$outside/failure-modes.md")" = "$before" ]
}

@test "B1: dirfd write remains inside a consumer during a fault-injected path flip" {
  local repo target outside tool_copy pid
  repo="$(make_repo write-race)"
  target="$(target_for "$repo")"
  outside="$WORK/outside-write"
  mkdir -p "$(dirname "$target")" "$outside"
  tool_copy="$STAGE/bin/sync-failure-modes-race.sh"
  cp "$TOOL" "$tool_copy"
  if grep -Fq '# DIRFD_WRITE_HOOK' "$tool_copy"; then
    sed -i '/# DIRFD_WRITE_HOOK/a sleep 0.3' "$tool_copy"
  else
    # The vulnerable predecessor re-walks temp_target immediately after this
    # point; this deterministic pause makes that old path-by-name window red.
    sed -i '/if ! temp_target=.*mktemp/i sleep 0.3' "$tool_copy"
  fi
  bash "$tool_copy" --apply --consumers "$CONSUMERS" >"$WORK/race.out" 2>&1 &
  pid=$!
  sleep 0.1
  rmdir "$repo/docs/vendor/hindsight" 2>/dev/null || true
  ln -s "$outside" "$repo/docs/vendor/hindsight" 2>/dev/null || true
  [ -L "$repo/docs/vendor/hindsight" ]
  [ "$(readlink "$repo/docs/vendor/hindsight")" = "$outside" ]
  wait "$pid" || true

  [ ! -e "$outside/failure-modes.md" ]
  [ -z "$(ls -A "$outside")" ]
}

@test "B3: unreadable middle target records a complete journal and later consumers still sync" {
  local first middle last first_target middle_target last_target journal
  first="$(make_repo readable-first)"
  middle="$(make_repo unreadable-middle)"
  last="$(make_repo readable-last)"
  first_target="$(target_for "$first")"
  middle_target="$(make_owned_target "$middle")"
  last_target="$(target_for "$last")"
  git -C "$middle" add docs/vendor/hindsight/failure-modes.md
  git -C "$middle" commit -qm unreadable-seed
  chmod 000 "$middle_target"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  chmod 644 "$middle_target"
  [ "$status" -ne 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  [ -f "$journal" ]
  [ "$(($(wc -l <"$journal") - 1))" -eq 3 ]
  [ -f "$first_target" ]
  [ -f "$last_target" ]
}

@test "B3: a journal backup-copy failure is recorded and later consumers still sync" {
  local first middle last first_target middle_target last_target journal
  first="$(make_repo copy-first)"
  middle="$(make_repo copy-middle)"
  last="$(make_repo copy-last)"
  first_target="$(target_for "$first")"
  middle_target="$(make_owned_target "$middle")"
  last_target="$(target_for "$last")"
  mkdir -p "$WORK/fakebin"
  printf '%s\n' '#!/usr/bin/env bash' 'exit 1' >"$WORK/fakebin/cp"
  chmod +x "$WORK/fakebin/cp"

  run env PATH="$WORK/fakebin:$PATH" bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  [ -f "$journal" ]
  [ "$(($(wc -l <"$journal") - 1))" -eq 3 ]
  [ -f "$first_target" ]
  [ -f "$last_target" ]
}

@test "M1: a FIFO target is refused promptly and does not stop the batch" {
  local fifo healthy fifo_target healthy_target
  fifo="$(make_repo fifo-target)"
  healthy="$(make_repo fifo-healthy)"
  fifo_target="$(target_for "$fifo")"
  healthy_target="$(target_for "$healthy")"
  mkdir -p "$(dirname "$fifo_target")"
  mkfifo "$fifo_target"

  run timeout 3 bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"non-regular target"* ]]
  [ -p "$fifo_target" ]
  [ -f "$healthy_target" ]
}

@test "M2: apply and undo preserve an owned target mode" {
  local repo target journal
  repo="$(make_repo mode-preservation)"
  target="$(make_owned_target "$repo")"
  chmod 644 "$target"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -eq 0 ]
  [ "$(stat -c %a "$target")" = 644 ]
  journal="$(printf '%s\n' "$output" | sed -n 's/^UNDO JOURNAL: //p' | head -n 1)"
  run bash "$TOOL" --undo "$journal"
  [ "$status" -eq 0 ]
  [ "$(stat -c %a "$target")" = 644 ]
}

@test "M3: a journal-phase containment failure exits non-zero" {
  local repo outside
  repo="$(make_repo invalid-journal-row)"
  outside="$WORK/outside-invalid"
  mkdir -p "$repo/docs" "$outside"
  ln -s "$outside" "$repo/docs/vendor"

  run bash "$TOOL" --apply --consumers "$CONSUMERS"

  [ "$status" -ne 0 ]
  [[ "$output" == *"strict target identity check failed"* ]]
  [[ "$output" == *"failed=1"* ]]
}
