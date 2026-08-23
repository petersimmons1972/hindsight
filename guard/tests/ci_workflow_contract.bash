#!/usr/bin/env bash
set -uo pipefail

fail() {
  printf 'workflow-contract: ERROR: %s\n' "$*" >&2
  return 1
}

workflow_contract_check() {
  local workflow=${1-}
  if [[ ! -f "$workflow" ]]; then
    fail "evidence source missing: $workflow"
    return 1
  fi
  if [[ ! -s "$workflow" ]]; then
    fail "evidence source is empty: $workflow"
    return 1
  fi

  local -a declarations=()
  mapfile -t declarations < <(grep -E '^        shard: \[[^]]+\]$' "$workflow")
  if (( ${#declarations[@]} != 1 )); then
    fail "guard.yml must declare exactly one inline matrix.shard list; found ${#declarations[@]}"
    return 1
  fi

  local payload=${declarations[0]#*\[}
  payload=${payload%\]*}
  local -a raw_shards=()
  IFS=',' read -r -a raw_shards <<<"$payload"
  local -a shards=()
  local raw shard
  declare -A declared=()
  declare -A positive_gates=()
  for raw in "${raw_shards[@]}"; do
    shard=${raw#"${raw%%[![:space:]]*}"}
    shard=${shard%"${shard##*[![:space:]]}"}
    if [[ -z "$shard" ]]; then
      fail "matrix.shard must declare only non-empty values"
      return 1
    fi
    if [[ -v "declared[$shard]" ]]; then
      fail "matrix.shard contains duplicate value '$shard'"
      return 1
    fi
    declared[$shard]=1
    positive_gates[$shard]=0
    shards+=("$shard")
  done
  if (( ${#shards[@]} == 0 )); then
    fail "matrix.shard must declare at least one value"
    return 1
  fi

  local -a lines=()
  mapfile -t lines <"$workflow"
  local shard_if_re="^        if: matrix\\.shard[[:space:]]*(==|!=)[[:space:]]*'([^']+)'$"
  local step_start step_end index line label condition operation literal
  local has_test_bearing_action guarded_steps=0
  local contract_steps=0 rest_detector_steps=0 tools_detector_steps=0
  local expected_run_seen condition_lines

  for ((step_start = 0; step_start < ${#lines[@]}; step_start++)); do
    [[ ${lines[step_start]} == '      - '* ]] || continue
    label=${lines[step_start]#'      - '}
    step_end=$((step_start + 1))
    while (( step_end < ${#lines[@]} )) && [[ ${lines[step_end]} != '      - '* ]]; do
      ((step_end += 1))
    done

    local -a shard_lines=()
    local -a if_lines=()
    has_test_bearing_action=0
    expected_run_seen=0
    for ((index = step_start + 1; index < step_end; index++)); do
      line=${lines[index]}
      if [[ $line == *matrix.shard* ]]; then
        shard_lines+=("$line")
      fi
      if [[ $line == '        if: '* ]]; then
        if_lines+=("$line")
      fi
      if [[ $line == '        run: python3 -m pytest '* || \
            $line == '        run: bats '* ]]; then
        has_test_bearing_action=1
      fi
      if [[ $label == 'name: Validate workflow shard contract' && \
            $line == '        run: bash guard/tests/ci_workflow_contract.bash .github/workflows/guard.yml' ]]; then
        expected_run_seen=1
      fi
      if [[ $label == 'name: Run Python tests (remaining shard)' && \
            $line == '        run: python3 -m pytest guard/tests/ pipeline/tests/ bin/tests/ --ignore=bin/tests/test_add_failure_mode_release.py -q --durations=25' ]]; then
        expected_run_seen=1
      fi
      if [[ $label == 'name: Run bats tests' && \
            $line == '        run: bats guard/tests/*.bats' ]]; then
        expected_run_seen=1
      fi
    done

    if (( ${#shard_lines[@]} > 0 )); then
      if (( ${#shard_lines[@]} != 1 )); then
        fail "$label must have exactly one matrix.shard condition; found ${#shard_lines[@]}"
        return 1
      fi
      condition=${shard_lines[0]}
      if [[ ! $condition =~ $shard_if_re ]]; then
        fail "$label has an unsupported matrix.shard condition: '${condition#'        '}'"
        return 1
      fi
      operation=${BASH_REMATCH[1]}
      literal=${BASH_REMATCH[2]}
      if [[ ! -v "declared[$literal]" ]]; then
        fail "$label uses unknown matrix.shard literal '$literal'; declared shards are: ${shards[*]}"
        return 1
      fi
      ((guarded_steps += 1))
      if [[ $operation == '==' ]] && (( has_test_bearing_action == 1 )); then
        positive_gates[$literal]=$((positive_gates[$literal] + 1))
      fi
    fi

    if [[ $label == 'name: Validate workflow shard contract' ]]; then
      ((contract_steps += 1))
      condition_lines=${#if_lines[@]}
      if (( condition_lines != 0 )); then
        fail "Validate workflow shard contract must be unconditional; found $condition_lines if condition(s)"
        return 1
      fi
      if (( expected_run_seen != 1 )); then
        fail "Validate workflow shard contract must run the pinned contract command"
        return 1
      fi
    elif [[ $label == 'name: Run Python tests (remaining shard)' ]]; then
      ((rest_detector_steps += 1))
      if [[ ${shard_lines[0]-} != "        if: matrix.shard == 'pytest-rest'" ]]; then
        fail "Run Python tests (remaining shard) must run on 'pytest-rest'"
        return 1
      fi
      if (( expected_run_seen != 1 )); then
        fail "Run Python tests (remaining shard) must collect guard/tests/ with the pinned command"
        return 1
      fi
    elif [[ $label == 'name: Run bats tests' ]]; then
      ((tools_detector_steps += 1))
      if [[ ${shard_lines[0]-} != "        if: matrix.shard == 'tools'" ]]; then
        fail "Run bats tests must run on 'tools'"
        return 1
      fi
      if (( expected_run_seen != 1 )); then
        fail "Run bats tests must collect guard/tests/*.bats with the pinned command"
        return 1
      fi
    fi

    step_start=$((step_end - 1))
  done

  if (( guarded_steps == 0 )); then
    fail "guard.yml has no step-level matrix.shard conditions"
    return 1
  fi
  for shard in "${shards[@]}"; do
    if (( positive_gates[$shard] == 0 )); then
      fail "declared shard '$shard' has no test-bearing positive step gate"
      return 1
    fi
  done
  if (( contract_steps != 1 )); then
    fail "guard.yml must contain exactly one unconditional Validate workflow shard contract step; found $contract_steps"
    return 1
  fi
  if (( rest_detector_steps != 1 )); then
    fail "guard.yml must contain exactly one Run Python tests (remaining shard) detector step; found $rest_detector_steps"
    return 1
  fi
  if (( tools_detector_steps != 1 )); then
    fail "guard.yml must contain exactly one Run bats tests detector step; found $tools_detector_steps"
    return 1
  fi

  printf 'workflow-contract: OK (%d declared shards, %d guarded steps)\n' \
    "${#shards[@]}" "$guarded_steps"
}

workflow_contract_check "$@"
