SURVIVORS: 13 of 23 mutants

Baseline: `bats bin/tests/*.bats` → `1..79`, 79 ok, 0 not ok, exit 0 (read directly from the process, not through a pipe). All runs used a stubbed `gh` on PATH (`/home/psimmons/.claude/jobs/2c17b6f5/tmp/stub/gh`, exits 1) so no mutant could reach the network — two mutants (L2, L3) do drive `land.sh` into its real merge call, and without that stub they would have attempted a live merge. Baseline under the stub is identically 79/79/exit 0.

Every survivor below produced `rc=0 ok=79 notok=0` — the suite was fully green on the mutated code. Per-mutant transcripts: `/home/psimmons/.claude/jobs/2c17b6f5/tmp/out/<ID>.txt`. Driver: `/home/psimmons/.claude/jobs/2c17b6f5/tmp/mutate.py`.

The headline: **the suite has no test that pins how a required check NAME is matched.** Three separate mutations of that one comparison each turn a red PR green, and all three pass 79/79.

---

## CRITICAL — mutant reports a wrong result as a right one (exit 0 on a PR that is not green)

### R1 — required-name match becomes case-insensitive
```diff
--- a/bin/require-real-ci.sh
+++ b/bin/require-real-ci.sh
-    matches = [e for e in rollup if isinstance(e, dict) and entry_key(e) == req]
+    matches = [e for e in rollup if isinstance(e, dict) and str(entry_key(e)).lower() == req.lower()]
```
Suite: `### R1 rc=0 ok=79 notok=0` … `ok 79 S11 pin: --max-wait-minutes abc is rejected …`

Exploit (rollup contains only `Guard`; the required `guard` never ran at all):
```
ORIGINAL rc=2 stdout="FAIL: required check 'guard' is absent from the rollup entirely"
MUTANT   rc=0 stdout="PASS: all required checks (guard) are COMPLETED/SUCCESS"
```
Severity: **critical**. GitHub check names are case-sensitive; a renamed/re-cased job silently substitutes for the required gate, and `land.sh` merges. This is the FM-149 failure class exactly — a gate that never ran, reported green.

Killing test: required `guard`, rollup `[{"name":"Guard","status":"COMPLETED","conclusion":"SUCCESS"}]` → expect exit 2 and `required check 'guard' is absent from the rollup entirely`.

### R2 — required-name match tolerates surrounding whitespace
```diff
-    matches = [e for e in rollup if isinstance(e, dict) and entry_key(e) == req]
+    matches = [e for e in rollup if isinstance(e, dict) and str(entry_key(e)).strip() == req]
```
Suite: `### R2 rc=0 ok=79 notok=0`
```
ORIGINAL rc=2 stdout="FAIL: required check 'guard' is absent from the rollup entirely"
MUTANT   rc=0 stdout="PASS: all required checks (guard) are COMPLETED/SUCCESS"
```
Severity: **critical**, same mechanism as R1. Note the script deliberately trims the *required* names (`TRIMMED_REQUIRED`) but must not trim the *rollup* names — nothing tests that asymmetry.

Killing test: rollup entry named `" guard "` SUCCESS, no exact `guard` → expect exit 2 / "absent".

### R11 — legacy StatusContext state compared case-insensitively
```diff
-        if state != "SUCCESS":
+        if str(state).upper() != "SUCCESS":
```
Suite: `### R11 rc=0 ok=79 notok=0`
```
ORIGINAL rc=2 stdout="FAIL: required check 'guard' (legacy status context) is not SUCCESS (state='success')"
MUTANT   rc=0 stdout="PASS: all required checks (guard) are COMPLETED/SUCCESS"
```
Severity: **critical**. The suite has M27/M28 pinning exact-case on `status` and `conclusion` (the CheckRun branch) but nothing equivalent on the legacy branch — the hardening was applied to one of two shapes. The REST API genuinely emits lowercase `state`, so this is not hypothetical.

Killing test: fixture `{"__typename":"StatusContext","context":"guard","state":"success"}` → expect exit 2. (Mirror of the existing t30/t31 pair, for the legacy branch.)

---

## HIGH

### R6 — a second positional silently REPLACES the PR number
```diff
     *)
-      if [ -n "$PR" ]; then
-        die_usage "unexpected extra argument: $1"
-      fi
-      PR="$1"
+      PR="$1"
       shift
```
Suite: `### R6 rc=0 ok=79 notok=0`

Exploit on the network path, `require-real-ci.sh 123 456`:
```
ORIGINAL rc=1 err="require-real-ci.sh: unexpected extra argument: 456"
MUTANT   rc=1 err="…gh pr view 456 --repo petersimmons1972/hindsight --json statusCheckRollup"
```
Severity: **high**. The gate certifies **PR 456** while the caller and every log line say PR 123 — a green verdict harvested from the wrong pull request. `land.sh` has this pin (L14/S9); `require-real-ci.sh`, the thing that actually decides, does not.

Killing test: `run "$SCRIPT" 123 456 --json-file "$FIXTURES/t1_all_success.json"` → expect exit 1 and `unexpected extra argument: 456`.

---

## MEDIUM

### R8 — contract-failure exit changes from 2 to 1 inside the evaluator
```diff
 if reasons:
     print("FAIL: " + "; ".join(reasons))
-    sys.exit(2)
+    sys.exit(1)
```
Suite: `### R8 rc=0 ok=79 notok=0`
```
ORIGINAL rc=2 stdout="FAIL: required check 'guard' is not complete (status='QUEUED')" stderr=""
MUTANT   rc=2 stdout=""  stderr="require-real-ci.sh: python3 evaluator exited with undocumented code 1 (expected 0 or 2)\nFAIL: required check 'guard' is not complete (status='QUEUED')"
```
Severity: **medium** — fail-closed (still exit 2), but the FAIL verdict moves off **stdout** entirely and is relabelled as an internal evaluator crash. Every assertion in the suite reads bats' merged `$output`, so no test can distinguish the verdict channel. Any consumer parsing stdout for `PASS:`/`FAIL:` now sees an empty stdout on a red PR, and the real reason is buried under a misleading "undocumented code" banner.

Killing test: assert the FAIL line is on **stdout** specifically, e.g. `run bash -c '"$SCRIPT" 999 --json-file … 2>/dev/null'` → `[[ "$output" == *"FAIL: required check 'guard'"* ]]`, plus `[[ "$output" != *"undocumented code"* ]]`.

---

## LOW (survived; fail-closed or diagnostic-only)

| ID | Diff | Effect | Killing test |
|---|---|---|---|
| R3 | `elif mins < max_wait_minutes:` → `<=` | Off-by-one at the exact boundary: at `mins == max_wait_minutes` the message says "within … still starting up" instead of "exceeded … likely stuck". Exit code unchanged. T14/T15 test well-inside and well-outside, never the boundary. | Fixture with `startedAt` exactly `--max-wait-minutes` old → assert `exceeded`. |
| R4 | `parse_time(entry.get("startedAt") or entry.get("createdAt"))` → `parse_time(entry.get("startedAt"))` | The `createdAt` fallback is dead as far as the suite is concerned; an entry carrying only `createdAt` loses its elapsed/stuck diagnostic silently. | Fixture with `createdAt` only, no `startedAt` → assert the `m elapsed, exceeded --max-wait-minutes=` note renders. |
| R5 | `''\|*[!0-9]*)` → `*[!0-9]*)` | `--max-wait-minutes ''` accepted, reaching `int('')` in python; exits 2 via the undocumented-code path instead of the documented usage error 1. S11 covers `abc` only. | `run "$SCRIPT" 999 --json-file … --max-wait-minutes ''` → exit 1. |
| R7 | `[ -n "$RAW_JSON" ] \|\| die_usage "no JSON produced…"` → `:` | Empty `--json-file` still exits 1 but via "input is not valid JSON" — the empty-payload guard is untested and removable. | Empty file → exit 1 and `no JSON produced`. |
| R10 | drop `isinstance(e, dict) and` from the `matches` comprehension | A rollup containing a null/non-dict entry goes from clean PASS to an uncaught traceback (exit 2, fail-closed but unhandled). | Fixture `[null, {guard SUCCESS}]` → exit 0 with no traceback in output. |
| R15 | `if len(matches) > 1:` → `> 2` | With exactly 2 duplicate entries the "N of M entries named 'guard' failed the contract" summary is replaced by the bare single-entry reason. Duplicate handling is the core contract, and the count line reporting it is unpinned. | T9/T26 → assert `1 of 2 entries named 'guard' failed the contract`. |
| L4 | `gh pr reopen $PR` → `gh pr reopen 0` (UNDO block) | Law-3 undo instructions name the wrong PR. L7 pins only the *ordering* of the UNDO block, never its content. | L7 → additionally assert `[[ "$output" == *"gh pr reopen 99"* ]]`. |
| L5 | `exit "$merge_status"; }` → `exit 1; }` | A failed `gh pr merge` exit code is flattened to 1 rather than relayed. L12 asserts only `-ne 0`. Mirrors L17, which does pin verbatim relay for the gate. | Stub `gh` exiting 7 on merge → `[ "$status" -eq 7 ]`. |

---

## Killed: 10 of 23

`R9` (drop `len(rollup)==0`), `R12` (`or`→`and` in CheckRun shape detection), `R13` (drop `conclusion == ""`), `R14` (absent required check passes vacuously — 3 failures), `R16` (PASS line drops the check names), `R17` (leak undocumented evaluator exit verbatim), `R18` (disable JSON pre-validation), `L1` (CI-17: `gate_status=$?` read after `cat` — 6 failures), `L2` (only gate-exit-2 refuses, so exit 1 merges), `L3` (dry-run default defeated — 6 failures).

The duplicate-name contract, the empty-conclusion contract, the exit-code relay, and land.sh's gating are all genuinely well defended — L1 and L3, the two mutants that would actually merge on a red gate, each took down six tests.

---

## Tree state

`git status --porcelain` on `/home/psimmons/.claude/jobs/2c17b6f5/tmp/re3` is **EMPTY**. `git diff --stat` empty, no stashes; both targets restored byte-identical (verified by md5 and by an in-driver assertion after every single mutant). `/home/psimmons/projects/hindsight` was never touched — all work was confined to the assigned clone plus scratch files under `/home/psimmons/.claude/jobs/2c17b6f5/tmp/`.

Not reached (well under the 70-call cap, but out of scope for one pass): mutations of the `--repo` forwarding on the live `gh pr view` path, `similar-causes.py` and the other `bin/` scripts, and multi-mutation (higher-order) combinations.