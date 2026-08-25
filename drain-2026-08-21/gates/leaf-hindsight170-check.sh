#!/usr/bin/env bash
# Runnable transcription of leaf-hindsight170.md (FM-440: never stage the .md).
# Exit: 0 = all five PASS; 1 = mutant not caught / control not green; 2 = mutation did not apply.
set -uo pipefail

die() { printf 'hindsight170-gate: ERROR: %s\n' "$*" >&2; exit 1; }
did_not_apply() { printf 'MUTATION-DID-NOT-APPLY: %s\n' "$*" >&2; exit 2; }

W=$(git rev-parse --show-toplevel 2>/dev/null) || die "not inside a git checkout"
git -C "$W" remote get-url origin 2>/dev/null | grep -qE '/hindsight(\.git)?$' \
  || die "origin is not hindsight (refusing to grade the wrong repo)"

WF="$W/.github/workflows/guard.yml"
VERIFY="$W/bin/verify_bats_report.py"
PIN="$W/guard/tests/test_ci_offline_replay.py"
PY=$(test -x "$W/.venv/bin/python" && echo "$W/.venv/bin/python" || echo python3)

test -f "$WF" || die "missing $WF"
test -f "$VERIFY" || die "missing $VERIFY (Design A not present)"
test -f "$PIN" || die "missing $PIN"
grep -q 'Verify bin/ tool bats tests actually ran (hindsight#170)' "$WF" \
  || die "consumer step absent — tree is not the fixed Design A shape"
grep -q 'set -o pipefail' "$WF" || die "producer missing pipefail"

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
EVIDENCE_DIR="${EVIDENCE_DIR:-$SCRIPT_DIR/../evidence}"
mkdir -p "$EVIDENCE_DIR"

live_floor() {
  "$PY" -c "
from pathlib import Path
import re
n=0
for p in sorted(Path(r'$W/bin/tests').glob('*.bats')):
    n += sum(1 for line in p.read_text().splitlines() if re.match(r'^\s*@test\s+\"', line))
print(n)
"
}

write_legit_tap() {
  # Titles must be extracted the SAME way bats actually evaluates an @test
  # "title" (a bash double-quoted string, so e.g. \$RC -> $RC) -- a
  # hand-rolled second regex here previously diverged from
  # bin/verify_bats_report.py's own extractor and copied raw \$ escapes
  # verbatim, which does not match what real bats reports in TAP (caught by
  # CI on hindsight#170: guard (tools) run 32856407100, a real title in
  # bin/tests/test_require_real_ci.bats:390 failed the cross-reference).
  # Import the verifier's own collect_source_titles instead of re-deriving
  # titles, so this fixture can never drift from the thing it's proving.
  local out=$1
  "$PY" -c "
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('verify_bats_report', r'$VERIFY')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
titles = mod.collect_source_titles(Path(r'$W/bin/tests'))
assert titles
Path(r'$out').parent.mkdir(parents=True, exist_ok=True)
lines=['1..%d'%len(titles)] + [f'ok {i} {t}' for i,t in enumerate(titles,1)]
Path(r'$out').write_text('\n'.join(lines)+'\n')
print(len(titles))
"
}

update_pin_in_copy() {
  local tree=$1
  local digest
  digest=$("$PY" -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path(r'$tree/.github/workflows/guard.yml').read_bytes()).hexdigest())")
  "$PY" -c "
from pathlib import Path
import re
p=Path(r'$tree/guard/tests/test_ci_offline_replay.py')
t=p.read_text()
digest='$digest'
t2=re.sub(r'INTENDED_WORKFLOW_SHA256 = \"[0-9a-f]{64}\"',
          'INTENDED_WORKFLOW_SHA256 = \"%s\"' % digest, t, count=1)
assert t2!=t, 'pin rewrite did not change file'
p.write_text(t2)
print(digest)
"
}

run_pin_test() {
  local tree=$1
  (cd "$tree" && "$PY" -m pytest \
    guard/tests/test_ci_offline_replay.py::test_catalog_guard_runs_only_the_committed_offline_l2_replay \
    -q --tb=no) >"$tree/pin.log" 2>&1
  echo $?
}

extract_step() {
  local tree=$1
  local name=$2
  "$PY" -c "
import re
from pathlib import Path
t=Path(r'$tree/.github/workflows/guard.yml').read_text()
m=re.search(
    r'(?m)^      - name: ' + re.escape(r'''$name''') + r'\n(?:.*\n)*?(?=^      - |\Z)',
    t,
)
print(m.group(0) if m else '')
"
}

# Simulate tools-shard producer+consumer. mode: normal|skip_producer|forge|pipe_red
simulate_tools() {
  local tree=$1 mode=${2:-normal}
  local report="$tree/.bats-report/report.tap"
  rm -rf "$tree/.bats-report"

  local producer_block consumer_block
  producer_block=$(extract_step "$tree" 'Run bin/ tool bats tests (require-real-ci, land)')
  consumer_block=$(extract_step "$tree" 'Verify bin/ tool bats tests actually ran (hindsight#170)')

  local producer_runs=1 consumer_runs=1 consumer_coe=0
  printf '%s\n' "$producer_block" | grep -q '^        if: false$' && producer_runs=0
  if [[ -z "$consumer_block" ]]; then
    consumer_runs=0
  else
    printf '%s\n' "$consumer_block" | grep -q '^        if: false$' && consumer_runs=0
    printf '%s\n' "$consumer_block" | grep -q 'continue-on-error:' && consumer_coe=1
  fi

  local producer_rc=0
  if (( producer_runs )); then
    case "$mode" in
      forge)
        mkdir -p "$tree/.bats-report"
        local floor
        floor=$(live_floor)
        "$PY" -c "
from pathlib import Path
n=int('$floor')
Path(r'$report').write_text('1..%d\n'%n + ''.join(f'ok {i} fake test {i}\n' for i in range(1,n+1)))
"
        producer_rc=0
        ;;
      pipe_red)
        mkdir -p "$tree/.bats-report"
        write_legit_tap "$report" >/dev/null
        "$PY" -c "
from pathlib import Path
p=Path(r'$report')
lines=p.read_text().splitlines()
for i,l in enumerate(lines):
    if l.startswith('ok '):
        lines[i]='not '+l
        break
p.write_text('\n'.join(lines)+'\n')
"
        producer_rc=0
        if printf '%s\n' "$producer_block" | grep -q 'set -o pipefail'; then
          producer_rc=1
        fi
        ;;
      skip_producer)
        producer_rc=0
        ;;
      *)
        write_legit_tap "$report" >/dev/null
        producer_rc=0
        ;;
    esac
  fi

  if (( producer_runs && producer_rc != 0 )); then
    echo "simulate: producer_rc=$producer_rc (job red before consumer)"
    return 1
  fi

  local consumer_rc=0
  if (( consumer_runs )); then
    (cd "$tree" && "$PY" bin/verify_bats_report.py .bats-report/report.tap bin/tests) \
      >"$tree/consumer.log" 2>&1
    consumer_rc=$?
    if (( consumer_coe && consumer_rc != 0 )); then
      echo "simulate: consumer failed but continue-on-error swallows it"
      consumer_rc=0
    fi
  else
    echo "simulate: consumer skipped" >"$tree/consumer.log"
  fi

  echo "simulate: producer_runs=$producer_runs producer_rc=$producer_rc consumer_runs=$consumer_runs consumer_coe=$consumer_coe consumer_rc=$consumer_rc"
  if (( consumer_runs == 0 )); then
    return 0
  fi
  return "$consumer_rc"
}

echo "=== CONTROL (fixed tree) ==="
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
rsync -a --exclude .git --exclude .venv "$W/" "$T/c/"
write_legit_tap "$T/c/.bats-report/report.tap" >/dev/null
(cd "$T/c" && "$PY" bin/verify_bats_report.py .bats-report/report.tap bin/tests) \
  >"$T/c/consumer.log" 2>&1 \
  || die "CONTROL consumer failed: $(cat "$T/c/consumer.log")"
pin_rc=$(run_pin_test "$T/c")
[[ "$pin_rc" -eq 0 ]] || die "CONTROL pin test failed: $(tail -20 "$T/c/pin.log")"
echo "CONTROL PASS"

run_mutant() {
  local letter=$1
  echo "=== Mutation $letter ==="
  local M="$T/m$letter"
  rm -rf "$M"
  cp -a "$T/c" "$M"
  rm -rf "$M/.bats-report"

  case "$letter" in
  A)
    "$PY" -c "
from pathlib import Path
import re
p=Path(r'$M/.github/workflows/guard.yml')
t=p.read_text()
def repl(m):
    return re.sub(r'(?m)^        if: .*\$', '        if: false', m.group(0), count=1)
t2,n=re.subn(
    r'(?m)^      - name: Run bin/ tool bats tests \(require-real-ci, land\)\n(?:.*\n)*?(?=^      - |\Z)',
    repl, t, count=1)
assert n==1 and t2!=t
p.write_text(t2)
"
    cmp -s "$T/c/.github/workflows/guard.yml" "$M/.github/workflows/guard.yml" \
      && did_not_apply "A workflow unchanged"
    if simulate_tools "$M" skip_producer; then
      echo "mutA simulate unexpectedly green"; return 1
    fi
    echo "mutA caught by consumer (missing TAP)"
    ;;
  B)
    "$PY" -c "
from pathlib import Path
import re
p=Path(r'$M/.github/workflows/guard.yml')
t=p.read_text()
def repl(m):
    return re.sub(r'(?m)^        if: .*\$', '        if: false', m.group(0), count=1)
t2,n=re.subn(
    r'(?m)^      - name: Run bin/ tool bats tests \(require-real-ci, land\)\n(?:.*\n)*?(?=^      - |\Z)',
    repl, t, count=1)
assert n==1 and t2!=t
p.write_text(t2)
"
    # Brief variant B updates INTENDED_WORKFLOW_SHA256 only. The offline-replay
    # test also exact-pins the producer/consumer step blocks, so sha256 rewrite
    # alone still leaves that test red — a second catch beyond Design A's
    # consumer. Design A's load-bearing catch for B is the consumer.
    update_pin_in_copy "$M" >/dev/null
    pin_rc=$(run_pin_test "$M")
    echo "mutB pin_rc=$pin_rc (nonzero expected: exact step-block pin still red)"
    if simulate_tools "$M" skip_producer; then
      echo "mutB simulate unexpectedly green"; return 1
    fi
    echo "mutB consumer caught missing TAP (sha256-only rewrite insufficient)"
    ;;
  C)
    if simulate_tools "$M" forge; then
      echo "mutC forge unexpectedly green"; return 1
    fi
    grep -q 'not present as @test' "$M/consumer.log" \
      || die "C: expected title cross-ref error, got: $(cat "$M/consumer.log")"
    echo "mutC caught by title cross-ref"
    ;;
  D)
    "$PY" -c "
from pathlib import Path
import re
p=Path(r'$M/.github/workflows/guard.yml')
t=p.read_text()
def repl(m):
    return re.sub(r'(?m)^        if: .*\$', '        if: false', m.group(0), count=1)
t2,n=re.subn(
    r'(?m)^      - name: Verify bin/ tool bats tests actually ran \(hindsight#170\)\n(?:.*\n)*?(?=^      - |\Z)',
    repl, t, count=1)
assert n==1 and t2!=t
p.write_text(t2)
"
    cmp -s "$T/c/.github/workflows/guard.yml" "$M/.github/workflows/guard.yml" \
      && did_not_apply "D1 workflow unchanged"
    pin_rc=$(run_pin_test "$M")
    [[ "$pin_rc" -ne 0 ]] || { echo "mutD1 pin unexpectedly green"; return 1; }
    simulate_tools "$M" normal || true
    echo "mutD1 caught by workflow pin / exact step block"

    local M2="$T/mD2"
    rm -rf "$M2"; cp -a "$T/c" "$M2"; rm -rf "$M2/.bats-report"
    "$PY" -c "
from pathlib import Path
import re
p=Path(r'$M2/.github/workflows/guard.yml')
t=p.read_text()
old = \"        if: matrix.shard == 'tools'\\n\"
new = old + \"        continue-on-error: true\\n\"
def repl(m):
    b=m.group(0)
    assert old in b
    return b.replace(old, new, 1)
t2,n=re.subn(
    r'(?m)^      - name: Verify bin/ tool bats tests actually ran \(hindsight#170\)\n(?:.*\n)*?(?=^      - |\Z)',
    repl, t, count=1)
assert n==1 and 'continue-on-error: true' in t2
p.write_text(t2)
"
    pin_rc=$(run_pin_test "$M2")
    [[ "$pin_rc" -ne 0 ]] || { echo "mutD2 pin unexpectedly green"; return 1; }
    echo "mutD2 continue-on-error caught by workflow pin"
    ;;
  E)
    if simulate_tools "$M" pipe_red; then
      echo "mutE pipe_red unexpectedly green"; return 1
    fi
    echo "mutE caught (pipefail and/or not-ok consumer)"
    ;;
  *) die "unknown mutant $letter" ;;
  esac
  return 0
}

for k in A B C D E; do
  out="$EVIDENCE_DIR/h170-mut${k}.out"
  if run_mutant "$k" >"$out" 2>&1; then
    echo "CHECK $k PASS"
    cat "$out"
  else
    rc=$?
    echo "CHECK $k FAIL (exit $rc)"
    cat "$out"
    exit "$rc"
  fi
done

# Extra pin-range proof (brief item 5): mutate ONLY the consumer; pin must move/fail
echo "=== Pin-range proof (consumer-only revert) ==="
M="$T/mPIN"
rm -rf "$M"; cp -a "$T/c" "$M"
"$PY" -c "
from pathlib import Path
import re
p=Path(r'$M/.github/workflows/guard.yml')
t=p.read_text()
t2=t.replace(
    'Verify bin/ tool bats tests actually ran (hindsight#170)',
    'Verify bin/ tool bats tests actually ran (REMOVED)',
    1,
)
assert t2!=t
p.write_text(t2)
"
pin_rc=$(run_pin_test "$M")
[[ "$pin_rc" -ne 0 ]] || die "consumer-only edit left pin green"
echo "PIN-RANGE PASS (consumer-only edit fails pin)"

echo "hindsight#170 gate: all five checks PASS"
exit 0
