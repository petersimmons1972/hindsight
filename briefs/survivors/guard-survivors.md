SURVIVORS: 13 of 30 mutants

Baseline verified green before any mutation: `67 passed` (pytest, rc=0) and `1..2 / ok 1 / ok 2` (bats, rc=0). Every mutant was applied one at a time to `/home/psimmons/.claude/jobs/2c17b6f5/tmp/re1/guard/failure_mode_catalog_guard.py`, both suites run, file restored. Final `git status --porcelain` is **EMPTY** and `git diff --stat HEAD` is empty — the clone is pristine, and both suites are green on the restored file.

Every survivor below was additionally proven **non-equivalent**: I wrote 15 killer tests at `/home/psimmons/.claude/jobs/2c17b6f5/tmp/killers/test_killers.py` (kept outside the clone). All 15 pass on the unmutated guard, and each mutant fails **exactly and only its own** killer. So these are real holes, not untestable no-ops.

Suite output was identical for all 13 survivors — `67 passed in ~0.40s` (pytest rc=0) and `ok 1 / ok 2` (bats rc=0) — so I give it once here rather than repeating it 13 times.

---

### S1 — M01 · ledger match ignores the claimed path · **SEVERITY: HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 674, main())
-        unlisted = [phantom for phantom in report.phantoms if phantom.key() not in known]
+        known_2 = {(k[0], k[1]) for k in known}
+        unlisted = [phantom for phantom in report.phantoms
+                    if (phantom.source, phantom.entry_id) not in known_2]
```
`PhantomEntry.key()` is a 3-tuple *including* `enforcement_file`, but nothing tests that the third element is load-bearing. With the mutant, an entry that already has a documented phantom can have its `enforcement.file` rewritten to a **brand-new** fabricated path and the run still exits 0 — "new phantoms cannot land silently" is defeated by editing one field. Tests only ever check documented-matches-exactly vs nothing-documented; the near-miss is untested.
**Killer:** `test_M01_ledger_entry_for_a_different_claimed_path_does_not_excuse_this_phantom` — phantom at `bin/NEW-phantom.sh`, ledger documents `bin/OLD-phantom.sh`; assert rc==1 and `"undocumented"` in stderr.

### S2 — M04/M05 · malformed `source-roots.conf` line silently skipped · **SEVERITY: HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (lines 119-120, load_source_roots)
         if ":" not in line:
-            raise ValueError(f"malformed source-roots line {path}:{line_number}: {raw_line!r}")
+            continue
```
```diff
--- a/guard/failure_mode_catalog_guard.py   (lines 124-125, load_source_roots)
         if not source or not relpath:
-            raise ValueError(f"malformed source-roots line {path}:{line_number}: {raw_line!r}")
+            continue
```
Two independent survivors. The docstring explicitly promises "Fails loud, never *no map, so all fine*", and tests cover **missing**, **empty**, and **comment-only** map files — but never a *malformed line inside a valid map*. A dropped mapping does not fail; it demotes that whole source to UNVERIFIABLE, which is a non-fatal admission. So a one-character typo in `source-roots.conf` makes every phantom in that source disappear from the fatal path while the run still exits 0. This is the highest-leverage hole: it is the cheapest way to make the verifier stop seeing real debt.
**Killer:** `test_M04_M05_malformed_source_roots_line_is_fatal_not_skipped`, parametrized over `this-line-has-no-colon`, `:repo2`, `other:`; assert rc==1 and `"malformed source-roots line"` in stderr.

### S3 — M30 · a regular file counts as a resolved source root · **SEVERITY: HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (lines 374-375, _resolve_source_root)
-    if not candidate.is_dir():
+    if candidate.is_dir() is False and not candidate.exists():
         return None, f"root not present on this machine: {candidate}"
```
Tests cover *absent* roots but never a path that **exists and is not a directory** (stale file, broken checkout, dangling symlink target). With the mutant, such a path counts toward `roots_resolved`, which dodges the `resolved_count == 0` hard ERROR and drops the run into the `useful_count == 0` **"SKIPPED" branch that returns 0**. A structurally broken environment reports success. This is precisely the vacuous-pass the module's own docstring says it refuses to do.
**Killer:** `test_M30_a_file_where_a_checkout_should_be_is_not_a_resolved_root` — write a regular file at `~projects/repo`, map `s:repo`; assert rc==1 and `"0 of 1 mapped source roots"` in stderr.

### S4 — M07 · judgment entries can satisfy the enforcement floor · **SEVERITY: HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 212, total_enforcement_bearing)
-    return sum(totals.machine - totals.unbacked for totals in report.sources.values())
+    return sum(totals.machine - totals.unbacked + totals.judgment
+               for totals in report.sources.values())
```
`test_total_enforcement_bearing_excludes_entries_that_enforce_nothing` pins the *unbacked* exclusion only. Nothing pins that `judgment` entries are excluded. This defeats the stated fleet#152 defense end-to-end: delete enforcement-bearing machine entries, add judgment entries (which require no enforcement at all), and the floor is still met.
**Killer:** `test_debt_floor_counts_every_enforcement_bearing_row_and_reports_old_total` — replaced `test_M07_judgment_entries_cannot_prop_up_the_enforcement_floor` in issue #31, which widened the counted population. The S4 invariant is still pinned: the `+ totals.judgment` mutant is killed by the exact-count assertion.

### S5 — M02 · debt ledger no longer requires evidence/disposition · **SEVERITY: MEDIUM-HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 161, load_known_phantoms)
-        for field in ("source", "id", "claimed_path", "evidence", "disposition"):
+        for field in ("source", "id", "claimed_path"):
```
### S6 — M03 · debt ledger accepts empty-string evidence/disposition · **SEVERITY: MEDIUM-HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 162, load_known_phantoms)
-        if not isinstance(record.get(field), str) or not record[field]:
+        if not isinstance(record.get(field), str):
```
Two independent survivors. The tests exercise the ledger's *presence* (missing file, empty file, documented vs undocumented) but never its **schema**. `evidence` and `disposition` are the only things separating a debt ledger from "a silent allowlist" — the exact phrase the code prints on every run. With either mutant, `{"source":..,"id":..,"claimed_path":..}` (or the same with `"evidence":""`) silences a phantom with zero justification recorded.
**Killer:** `test_M02_M03_phantom_ledger_demands_nonempty_evidence_and_disposition`, parametrized over a record missing `evidence`/`disposition` and one with both empty; assert rc==1.

### S7 — M13 · `enforcement: {}` relabelled "unbacked" instead of raising · **SEVERITY: MEDIUM-HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (lines 442-443, verify_enforcement)
-            if enforcement is None:
+            if not enforcement:
                 totals.unbacked += 1
```
`test_malformed_enforcement_file_raises_and_is_not_relabelled_unbacked` and `test_empty_enforcement_file_string_also_raises` both use a **populated** dict with a bad `file` value. Nobody tests the falsy-but-not-None container itself (`{}`, and by the same edit `""`/`0`/`false`). The mutant converts a hard `invalid enforcement.file` error into a benign WARNING line — a malformed record is reported as an honest "no enforcement claimed".
**Killer:** `test_M13_empty_enforcement_object_is_malformed_not_relabelled_unbacked` — record with `"enforcement": {}`; assert rc==1 and `"invalid enforcement.file"` in stderr.

### S8 — M16 · legacy row-ID detection depends on markdown cell padding · **SEVERITY: MEDIUM-HIGH**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 24)
-HISTORICAL_SCHEME_RE = re.compile(r"^\| *FM-(RC|REC)-\d+ *\|")
+HISTORICAL_SCHEME_RE = re.compile(r"^\| FM-(RC|REC)-\d+ \|")
```
The suite has a positive test (`| FM-RC-01 |`, one space), a single-digit test, and a negative test for provenance annotations — all using exactly-one-space padding. The `*` quantifiers are therefore completely unpinned. With the mutant, `|FM-RC-01| ... |` (no padding) and `|  FM-REC-07  | ... |` (double padding) both sail through. Hand-edited or tool-generated markdown produces unpadded pipes routinely, so this reintroduces the exact scheme whose enforcement "nearly lost FM-REC-01..11".
**Killer:** `test_M16_legacy_row_id_is_rejected_whatever_the_cell_padding`, parametrized over `|FM-RC-01|...|` and `|  FM-REC-07  |...|`; assert rc==1 and `"historical alias scheme"` in stderr.

### S9 — M23 · multi-value floor file silently takes the first value · **SEVERITY: MEDIUM**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 195, load_enforcement_floor)
-    if len(lines) != 1:
+    if len(lines) < 1:
```
Tests cover the file being *missing* and *non-integer*, never *ambiguous*. A botched edit or a half-resolved merge that leaves `33` and `40` on separate lines silently adopts whichever comes first — and "first" is not necessarily the higher floor, so the gate quietly weakens with no diagnostic.
**Killer:** `test_M23_multi_value_floor_file_is_fatal_not_first_wins` — floor file `"0\n99"`; assert rc==1 and `"exactly one value"` in stderr.

### S10 — M24 · non-object line in the debt ledger silently dropped · **SEVERITY: MEDIUM-LOW**
```diff
--- a/guard/failure_mode_catalog_guard.py   (lines 159-160, load_known_phantoms)
         if not isinstance(record, dict):
-            raise ValueError(f"known-phantoms line {path}:{line_number} is not an object")
+            continue
```
The `isinstance(record, dict)` check has no test at all. Dropping a line understates the printed DEBT count and removes ledger-file validation. Fail-*closed* for the phantom that line described (it becomes undocumented → fatal), which is why severity is not higher — but the "how many debts do we owe" number the code says "should shame us" becomes silently wrong.
**Killer:** `test_M24_non_object_known_phantoms_line_is_fatal_not_skipped` — ledger line `["s","e1","bin/nope.sh"]`; assert rc==1 and `"not an object"` in stderr.

### S11 — M15 · canonical row-ID grammar has no pinned lower bound · **SEVERITY: MEDIUM-LOW**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 20)
-ROW_RE = re.compile(r"^\| (FM-(\d{2,3})) \|")
+ROW_RE = re.compile(r"^\| (FM-(\d{1,3})) \|")
```
`test_single_digit_legacy_row_id_is_rejected` pins the single-digit bound for the *legacy* `FM-RC-n` scheme only. The canonical scheme's `{2,3}` is untested at both ends. Widening it silently changes which rows count as canonical, which shifts `next_id`, duplicate detection scope, and the append-only present-set. (Worth flagging separately: the *unmutated* code silently **ignores** a `| FM-1 |` row rather than rejecting it — that row is neither canonical nor a historical alias. That is arguably a hole in the original, not just in the tests.)
**Killer:** `test_M15_single_digit_row_id_is_not_a_canonical_row` — catalog containing only `| FM-1 |` and `| FM-2 |`; assert rc==1 and `"no canonical FM rows found"` in stderr.

### S12 — M14 · id-ledger regex end-anchor is untested · **SEVERITY: LOW**
```diff
--- a/guard/failure_mode_catalog_guard.py   (line 238)
-ID_LEDGER_RE = re.compile(r"^FM-\d+$")
+ID_LEDGER_RE = re.compile(r"^FM-\d+")
```
`test_loader_rejects_a_malformed_line` uses input that fails the *start* anchor, so the `$` is unpinned. With the mutant, `FM-02 retired-2026-08-01` is accepted as an ID, and the downstream sort key `int(i.split("-")[1])` then raises an **uncaught ValueError traceback** instead of the intended `malformed ledger entry` message. Exit status stays non-zero (hence LOW, not a fail-open), but a clean, actionable diagnostic degrades into a crash.
**Killer:** `test_M14_trailing_garbage_on_a_ledger_line_is_rejected_cleanly` — ledger lines `FM-01`, `FM-02 retired-2026-08-01`; assert rc==1 **and** `"malformed ledger entry"` in stderr.

---

## Killed (17 of 30)
M06 (debt-floor off-by-one), M08 (`checked > 0` → `>= 0`), M09 (zero-roots ERROR neutered into a SKIP), M10 (`--require-roots` off-by-one), M11 (`--accept-phantom` defaults on), M12 (root-escape check dropped), M17 (duplicate-ID off-by-one — the only mutant bats caught independently), M18 (append-only off-by-one: delete exactly one ID), M19 (append-only fires only on a count drop), M20 (`next_id` from row count), M21 (unverifiable booked as checked), M22 (blank L1 record skipped), M25 (existence weakened to `parent.exists()`), M26 (`checked` only counted on pass — all-phantom source → SKIP), M27 (ROOTS denominator becomes the resolved count), M28 (missing catalog exits 0), M29 (malformed ledger line skipped).

The new tests are genuinely strong on the axes they were written for: every off-by-one I tried on the *numeric* gates died, and both root-floor vacuity paths (`resolved_count == 0` vs the `SKIPPED` branch) are properly pinned in both directions.

## Where the coverage actually stops
The surviving 13 cluster into one shape the new tests do not reach: **the gates are well tested, the gates' own input files are not.** `source-roots.conf`, `known-phantoms.conf`, `enforcement-floor.conf` and `id-ledger.txt` are each tested for *missing* and *empty* — the coarse states — and for none of them is a *structurally malformed but present* file tested. Since three of those four loaders degrade a parse failure into a non-fatal state (UNVERIFIABLE, a smaller ledger, a smaller floor) rather than into an error, a single malformed line is the cheapest available way to make the verifier stop seeing debt while still exiting 0.

## Not reached (17 tool calls of 70 used)
- Mutations to `print_enforcement_report`'s textual contract (the SCOPE/UNVERIFIABLE disclaimers) — several are asserted, but I did not sweep them systematically.
- The bats layer is only 2 tests and caught exactly one mutant (M17) that pytest also caught; I did not design bats-specific mutants (e.g. against `.githooks/pre-commit` itself).
- Nothing outside `guard/` — the L1 corpus producers (`reconcile_l1.py` and friends) were out of scope per the target.