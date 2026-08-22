#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORKFLOW="$REPO_ROOT/.github/workflows/guard.yml"
  CONTRACT="$REPO_ROOT/guard/tests/ci_workflow_contract.bash"
  TMPDIR="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR"
}

@test "tools independently enforces the workflow shard contract" {
  run bash "$CONTRACT" "$WORKFLOW"
  [ "$status" -eq 0 ]
  [[ "$output" == *"workflow-contract: OK"* ]]
}

@test "tools rejects an undeclared pytest-rest gate" {
  sed "s/if: matrix.shard == 'pytest-rest'/if: matrix.shard == 'nope'/" \
    "$WORKFLOW" >"$TMPDIR/guard.yml"

  run bash "$CONTRACT" "$TMPDIR/guard.yml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Run Python tests (remaining shard)"* ]]
  [[ "$output" == *"unknown matrix.shard literal 'nope'"* ]]
}

@test "tools rejects an undeclared pytest-release gate" {
  sed "s/if: matrix.shard == 'pytest-release'/if: matrix.shard == 'nope'/" \
    "$WORKFLOW" >"$TMPDIR/guard.yml"

  run bash "$CONTRACT" "$TMPDIR/guard.yml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Run Python tests (release shard)"* ]]
  [[ "$output" == *"unknown matrix.shard literal 'nope'"* ]]
}

@test "tools rejects an undeclared tools gate" {
  sed "/- name: Run bats tests/{n;s/if: matrix.shard == 'tools'/if: matrix.shard == 'nope'/;}" \
    "$WORKFLOW" >"$TMPDIR/guard.yml"

  run bash "$CONTRACT" "$TMPDIR/guard.yml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Run bats tests"* ]]
  [[ "$output" == *"unknown matrix.shard literal 'nope'"* ]]
}

@test "tools rejects a declared shard with no positive step gate" {
  sed "s/shard: \[pytest-release, pytest-rest, tools\]/shard: [pytest-release, pytest-rest, tools, ghost]/" \
    "$WORKFLOW" >"$TMPDIR/guard.yml"

  run bash "$CONTRACT" "$TMPDIR/guard.yml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"declared shard 'ghost' has no substantive positive step gate"* ]]
}

@test "a no-op gate cannot hide a remapped pytest-rest detector" {
  sed "s/if: matrix.shard == 'pytest-rest'/if: matrix.shard == 'tools'/" \
    "$WORKFLOW" >"$TMPDIR/guard.yml"
  sed -i "/- name: Run Python tests (remaining shard)/i\      - name: Dummy pytest-rest coverage\n        if: matrix.shard == 'pytest-rest'\n        run: true" \
    "$TMPDIR/guard.yml"

  run bash "$CONTRACT" "$TMPDIR/guard.yml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Run Python tests (remaining shard) must run on 'pytest-rest'"* ]]
}

@test "a no-op gate cannot hide a remapped tools detector" {
  sed "/- name: Run bats tests/{n;s/if: matrix.shard == 'tools'/if: matrix.shard == 'pytest-rest'/;}" \
    "$WORKFLOW" >"$TMPDIR/guard.yml"
  sed -i "/- name: Run bats tests/i\      - name: Dummy tools coverage\n        if: matrix.shard == 'tools'\n        run: true" \
    "$TMPDIR/guard.yml"

  run bash "$CONTRACT" "$TMPDIR/guard.yml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Run bats tests must run on 'tools'"* ]]
}
