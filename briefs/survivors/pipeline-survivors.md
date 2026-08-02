SURVIVORS: 13 of 38 mutants

Baseline (verified before mutating): `python3 -m pytest pipeline/tests/ -q` → **34 passed, 2 skipped**, `python3 pipeline/reconcile_l1.py` exit 0 (`PARTIAL ... (1/5 sources resolved)`), `python3 pipeline/validate_l1.py` exit 0 (`TOTAL: 480 records across 14 files`). All 38 mutants were fresh (none replayed from the earlier list). Clone: `/home/psimmons/.claude/jobs/2c17b6f5/tmp/re2`. `/home/psimmons/projects/hindsight` was never touched. **Final `git status --porcelain` is EMPTY** (0 lines) and the suite is green again.

Killed: 25 of 38. Survivors below. Every survivor line labelled "suite" is the pytest tail under the mutation; "CLI" is the real `python3 pipeline/reconcile_l1.py` / `validate_l1.py` output with its exit code read directly.

---

## S1 — `R01` PARTIAL never fires: 4 unresolved sources report COMPLETE, exit 0 — SEVERITY: CRITICAL

```diff
--- a/pipeline/reconcile_l1.py
+++ b/pipeline/reconcile_l1.py
@@ main()
-        elif n_unresolved:
+        elif False:
             verdict = "PARTIAL"
```
suite: `34 passed, 2 skipped` (exit 0)
CLI (real repo, 4 sibling repos absent): `COMPLETE: 0 enumerable entries unaccounted for (1/5 sources resolved)`, **exit 0** — and the "4 source(s) were not on disk and were NOT checked" block disappears.
Synthetic probe (1 resolved + 1 absent source): baseline `PARTIAL: 0 ... (1/2 sources resolved)` → mutant `COMPLETE: 0 ... (1/2 sources resolved)`.

This is the *exact* fail-open the commit `30ab147`/`43683ba` work was written to close, one degree softer: not "nothing resolved" (which `test_all_sources_unresolved_is_fatal_not_complete` does catch) but "most things didn't resolve". The whole PARTIAL branch — the headline new behaviour — has **zero test coverage**: the string `PARTIAL` does not appear anywhere in `pipeline/tests/`. On a CI runner this is the live configuration, so the mutant would ship green.

Killing test: assert on the verdict line for a mixed corpus.
```python
def test_some_sources_unresolved_is_partial_not_complete(tmp_path, monkeypatch, capsys):
    l1 = tmp_path / "L1"; l1.mkdir()
    (l1 / "real.jsonl").write_text('{"id": "OPS-1"}\n', encoding="utf-8")
    md = tmp_path / "real.md"; md.write_text("## OPS-1\n", encoding="utf-8")
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(reconcile_l1, "ENUMERABLE", {
        "real": ([md], HEADING_RX), "gone": ([tmp_path / "nope.md"], HEADING_RX)})
    run_main(monkeypatch)
    out = capsys.readouterr().out
    verdict = [ln for ln in out.splitlines() if "unaccounted for" in ln]
    assert verdict == ["PARTIAL: 0 enumerable entries unaccounted for (1/2 sources resolved)"]
    assert "were NOT checked" in out
```

## S2 — `R02` the resolved-source count always prints "all resolved" — SEVERITY: HIGH

```diff
-              f" ({n_resolved}/{len(ENUMERABLE)} sources resolved)")
+              f" ({len(ENUMERABLE)}/{len(ENUMERABLE)} sources resolved)")
```
suite: `34 passed, 2 skipped` (exit 0)
CLI: `PARTIAL: 0 enumerable entries unaccounted for (5/5 sources resolved)` — the report now claims all five sources were compared while four were never on disk.

This is the "comparison flipped where both sides are usually equal" case. The only test that asserts the counter exactly (`test_shortfall_prints_short_and_exits_1` → `"(2/2 sources resolved)"`) uses a corpus where `n_resolved == len(ENUMERABLE)`, so the numerator is unconstrained. The counter is the single number a reader uses to judge how much the run actually covered.

Killing test: the same mixed-corpus assertion as S1 (`(1/2 sources resolved)`) pins the numerator against a denominator that differs.

## S3 — `R12` PARTIAL outranks SHORT: a real shortfall is renamed — SEVERITY: HIGH

```diff
-        elif short:
-            verdict = "SHORT"
-        elif n_unresolved:
-            verdict = "PARTIAL"
+        elif n_unresolved:
+            verdict = "PARTIAL"
+        elif short:
+            verdict = "SHORT"
```
suite: `34 passed, 2 skipped` (exit 0)
Probe (one absent source + one resolved source missing `OPS-2`): baseline `SHORT: 1 enumerable entries unaccounted for (1/2 sources resolved)` → mutant `PARTIAL: 1 enumerable entries unaccounted for (1/2 sources resolved)`, plus the reassuring "This run certifies only the resolved sources" prose. Exit stays 1, so CI still reds — the damage is to the human-read verdict word, which now names a benign cause for a lost entry.

Every SHORT test uses a fully-resolved corpus, so the precedence between the two new branches is untested. Killing test: same fixture as the probe, asserting `verdict[0].startswith("SHORT")` when `missing` is non-empty *and* a source is unresolved.

## S4 — `R03` an unresolved source scores 0.0% instead of `None` — SEVERITY: MEDIUM

```diff
         if not resolved:
-            cov = None
+            cov = 0.0
```
suite: `34 passed, 2 skipped` (exit 0). CLI still prints `PARTIAL ... (1/5)` but the table shows `0.0%` where it should show `n/a`.

`test_unresolved_source_is_not_reported_as_100_percent` only asserts `!= 100.0`, which is a one-sided bound: it pins the old bug's value and nothing else. `None` ("no measurement") vs `0.0` ("measured, found nothing") is the exact distinction this module exists to make, and downstream aggregation (any `mean(coverage_pct)`) silently changes meaning.

Killing test: `assert row["coverage_pct"] is None` in `test_unresolved_source_is_not_reported_as_100_percent`, and assert `"   n/a"` appears in the text row.

## S5 — `R10` `covered` counts extracted IDs, so coverage can exceed ground truth — SEVERITY: MEDIUM

```diff
-        report.append({..., "covered": len(truth) - len(missing), ...})
+        report.append({..., "covered": len(found), ...})
```
suite: `34 passed, 2 skipped` (exit 0)
Probe (truth `{OPS-1}`, extraction contains `OPS-1, OPS-2, OPS-3`): baseline row `{'ground_truth': 1, 'covered': 1}` → mutant `{'ground_truth': 1, 'covered': 3}` — a JSON consumer reads 300% coverage.

The only assertion on `covered` is `== 0` in the missing-file test, where `len(found)` is also 0 — both sides equal, so the field is effectively untested. Killing test: in `test_json_report_covers_every_configured_source`, add a source whose extraction contains extra IDs and assert `0 <= row["covered"] <= row["ground_truth"]` for every row.

## S6 — `R11` the extraction blob narrows back to the `id` field only — SEVERITY: MEDIUM

```diff
-        blob = " ".join(str(d.get(k, "")) for k in
-                        ("id", "source_anchor", "instance", "check"))
+        blob = " ".join(str(d.get(k, "")) for k in
+                        ("id",))
```
suite: `34 passed, 2 skipped` (exit 0)
Probe (record `{"id": "row-1", "source_anchor": "OPS-1"}` against truth `{OPS-1}`): baseline `COMPLETE ... covered 1` → mutant `SHORT: 1 ... 'missing': ['OPS-1'], coverage_pct 0.0`.

This reinstates the precise defect the code comment says was already fixed once ("reported a false 0% on fleet-dispatch — a validator that fails ground truth is worse than no validator"). Fail-closed, so it cries wolf rather than passing a lie — but a validator that reds on a good corpus gets muted, and the two tests that would catch it (`test_every_configured_source_has_a_non_empty_extraction`, `test_every_configured_ground_truth_source_resolves`) are **skipped** on any host without the sibling repos, i.e. on CI. Killing test: a synthetic corpus where the ground-truth ID lives in `source_anchor`/`instance`/`check`, not `id`, asserting full coverage — one record per field.

## S7 — `R18` the ID-suffix boundary: `FM-12a` satisfies a demand for `FM-12` — SEVERITY: MEDIUM

```diff
-        found.update(re.findall(r"(?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?", blob))
+        found.update(re.findall(r"(?:OPS|CI|ORC|MDL|FM)-\d+", blob))
```
suite: `34 passed, 2 skipped` (exit 0)
Probe (truth `{FM-12}`, extraction contains only `FM-12a`, a *different* entry): baseline `SHORT: 1 ... missing ['FM-12']` → mutant `COMPLETE: 0 enumerable entries unaccounted for (1/1 sources resolved)`, exit 0. A genuinely absent entry is certified as present by its lettered sibling.

The `[a-z]?` suffix appears in both the ground-truth regexes and the extraction regex, and no test uses a suffixed ID at all. Killing test: assert `extracted()` on `{"id": "FM-12a"}` returns `{"FM-12a"}` and *not* `{"FM-12"}`, plus an end-to-end case where truth `FM-12` + extraction `FM-12a` yields `SHORT`.

## S8 — `R17` the JSON `resolved` flag is derived from the extraction file — SEVERITY: MEDIUM

```diff
-                       "resolved": resolved, "missing": missing})
+                       "resolved": bool(n_lines), "missing": missing})
```
suite: `34 passed, 2 skipped` (exit 0)
Probe (source file absent, but `L1/gone.jsonl` has one record): baseline row `'resolved': False` → mutant `'resolved': True` while the verdict line still says `UNVERIFIED ... (0/1 sources resolved)` — the machine-readable report and the human verdict now contradict each other, and any consumer filtering on `resolved` treats an uncompared source as compared.

`test_unresolved_source_is_not_reported_as_100_percent` asserts `resolved is False` but writes an **empty** `ghost.jsonl`, so `bool(n_lines)` is also False — the two possible sources of the flag are indistinguishable in the fixture. Killing test: same fixture with a non-empty ghost extraction file, still asserting `row["resolved"] is False`.

## S9 — `V11` an empty JSON object passes every required-key check — SEVERITY: HIGH

```diff
--- a/pipeline/validate_l1.py
+++ b/pipeline/validate_l1.py
     for key in REQUIRED_KEYS:
-        if key not in record:
+        if record and key not in record:
             errors.append(f"{location}: missing required key '{key}'")
```
suite: `34 passed, 2 skipped` (exit 0)
Probe with a single record `{}`: baseline `4` errors (`missing required key 'id' / 'source_path' / 'instance' / 'auto'`) → mutant `0` errors, file counted as 1 valid record.

The canonical vacuous gate: the emptiest possible input is the one input that satisfies every rule. Every required-key test deletes exactly one key from a full record, so the empty-record boundary is never reached. Killing test:
```python
def test_rejects_empty_record_object(tmp_path):
    report = validate(tmp_path, {})
    assert report.error_count == 4
```

## S10 — `V06` a non-string `instance` is accepted — SEVERITY: MEDIUM

```diff
-    if "instance" in record and (
-        not isinstance(instance, str)
-        or not instance.strip()
+    if "instance" in record and isinstance(instance, str) and (
+        False
+        or not instance.strip()
         or instance.strip().lower() in PLACEHOLDER_INSTANCES
     ):
```
suite: `34 passed, 2 skipped` (exit 0)
Probe with `{"instance": 12345}`: baseline `1` error → mutant `0` errors.

The type check on `id` has a dedicated test (`test_rejects_non_string_id`); the identical check on `instance` has none, so the suite treats the two fields inconsistently. `instance` is the field carrying the evidence a record exists to record — `instance: 0`, `instance: []`, `instance: {}` all pass. Killing test: `validate(tmp_path, VALID_RECORD | {"instance": 12345})` expecting one `instance must be non-empty and not a placeholder` error (and a `[]` / `None` variant).

## S11 — `V10` `enforcement.kind: null` passes the vocabulary check — SEVERITY: MEDIUM

```diff
-    if "kind" in value and kind not in ENFORCEMENT_KINDS:
+    if kind and kind not in ENFORCEMENT_KINDS:
```
suite: `34 passed, 2 skipped` (exit 0)
Probe with `{"enforcement": {"file": "t.py", "kind": None}}`: baseline `1` error (`enforcement.kind must be one of ci, hook, lint, schema, test`) → mutant `0` errors.

Exactly the null-vs-absent distinction the suite gets right for `auto` (`test_rejects_null_auto`: "A present-but-null `auto` is a stated value, and it is not a permitted one") and wrong for `enforcement.kind`. A record claiming a named enforcement file with a null kind reads as covered while enforcing nothing — the failure `test_rejects_empty_enforcement_object` was written to prevent, entered through the other door. Killing test: `VALID_RECORD | {"enforcement": {"file": "t.py", "kind": None}}` expecting the `must be one of` error (add `"kind": ""` as a second case).

## S12 — `V19` a falsy non-string `enforcement.file` is accepted — SEVERITY: LOW/MEDIUM

```diff
-    if "file" in value and not isinstance(value["file"], str):
+    if value.get("file") and not isinstance(value["file"], str):
```
suite: `34 passed, 2 skipped` (exit 0)
Probe with `{"enforcement": {"file": 0, "kind": "test"}}`: baseline `1` error (`enforcement.file must be a string`) → mutant `0` errors. Same for `file: null`, `file: []`, `file: {}`.

`test_rejects_non_string_enforcement_file` uses `123` — truthy — so truthiness and presence are indistinguishable in the fixture. Related live gap found while probing: `{"file": "", "kind": "test"}` produces **no error even unmutated**, so an enforcement record can name an empty path today. Killing test: parametrise the non-string case over `0`, `None`, `[]`, `""` — the last one requires a small production change (a non-empty check), which is the gap worth closing.

## S13 — `V20` empty corpus files vanish from the printed file count — SEVERITY: LOW

```diff
-    print(f"TOTAL: {report.total_count} records across {len(report.file_counts)} files")
+    print(f"TOTAL: {report.total_count} records across "
+          f"{len([c for c in report.file_counts.values() if c])} files")
```
suite: `34 passed, 2 skipped` (exit 0)
CLI on a synthetic corpus of one populated + one empty `.jsonl`: baseline `TOTAL: 1 records across 2 files` (exit 0) → mutant `TOTAL: 1 records across 1 files` (exit 0). A file that contributed nothing stops being reported as read, so a truncated-to-zero corpus file becomes invisible in the only line CI prints.

`test_main_reads_the_whole_checked_in_corpus` derives its expectation from the same glob it is checking and every real file is non-empty, so the count is self-confirming. Killing test: build a CLI corpus containing a deliberately empty `.jsonl` and assert `across 2 files`.

---

### Killed: 25 of 38
`R04` count-every-source-as-resolved · `R05` UNVERIFIED never fires · `R06` UNVERIFIED exits 0 · `R07` `resolved` defaults True · `R08` off-by-one `len(missing) > 1` · `R09` `missing = found - truth` flipped · `R13` only first source iterated · `R14` heading depth `#{2,4}`→`#{2,3}` · `R15` self-catalog regex drops 2-digit FM ids · `R16` JSON hides unresolved rows · `V01` record count never increments · `V02` unreadable file silent · `V03` line numbers `start=0` · `V04` `.strip()` dropped from placeholder check · `V05` whitespace-only instance · `V07` null `auto` accepted · `V08` duplicate ids only within one file · `V09` `{}` enforcement vacuous · `V12` date round-trip check dropped · `V13` `"lint"` removed from `ENFORCEMENT_KINDS` · `V14` `auto` not required · `V15` CLI glob matches nothing · `V16` CLI exits 0 on errors · `V17` `total_count` uses `max` · `V18` non-dict record passthrough.

Worth noting: `V13` also turned the real `validate_l1.py` CLI red (exit 1), i.e. the checked-in corpus genuinely exercises the `lint` kind — that vocabulary is anchored to real data, not just to a test.

### Reading of the result
The claim "56 survivors were killed" is not contradicted — the old holes I probed for (null `auto`, padded placeholders, `{}` enforcement, date round-trip, unreadable files, CLI exit codes, cross-file duplicate ids, the all-unresolved fail-open) are all now closed, and 25 of 38 fresh mutants died. But the tests were written *to that list*. The new `reconcile_l1.py` verdict logic is tested only at its extremes: all-resolved (COMPLETE) and none-resolved (UNVERIFIED). The middle state — PARTIAL — is the one that actually occurs on CI and on this very clone, and it has no test at all: S1, S2 and S3 all live there, and S1 restores a COMPLETE/exit-0 verdict over four sources that were never compared. Three fixture habits produced most of the rest: assertions on corpora where the two candidate values coincide (S2, S5, S8), one-sided bounds that pin only the old bug's value (S4), and full-record-minus-one-key fixtures that never reach the empty-input boundary (S9).