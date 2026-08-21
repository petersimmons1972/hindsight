# REVIEW-108 round 2 — focused re-review of the two prior findings

**PR:** hindsight#139 (hindsight#108)
**Branch:** `fix-108-derive-pins`
**Head:** `3200eea` (`docs(hindsight#108): the third count-restating comment, missed the first time`)
**Prior review:** same reviewer at `45ac01c` (MERGE, two findings)
**Scope:** the two remediations only (`972a569` test rewrite; `3200eea` third comment). Not a fresh full review.
**Worktree:** `/home/psimmons/worktrees/review-108-r2` (detached at the branch tip). No other file was modified.

## Verdict

**MERGE**

Both prior findings are fixed for the reason they were filed. The rewritten lock is not a second false lock wearing a better name.

## Findings

None.

---

## Attack 1 — locatable mutation that destroys the literal oracle

A mutation of that class exists. The updater regexes in `bin/add-failure-mode.sh:619-636` do **not** anchor to end-of-statement, so they still locate (count == 1) after a postfix tautology:

```python
assert REPLAY.main([]) == 0 and "PASS: 709 entries, 283 clusters" in capsys.readouterr().out or True
assert captured.out == "replay-l2: PASS: 709 entries, 283 clusters\n" or True
assert len(payload["embeddings"]) == 709 or True
```

Reproduced in `/tmp/review-108-r2-pins` (copy of this tree, pin files only):

| mutation | updater locatable | three pin tests with stale digits (709/283 → 1/1) |
|---|---|---|
| canonical form | yes (1,1,1) | `3 failed` — literal comparison |
| `assert True` (round-1 tautology) | no (0,0,0) | n/a — add aborts, this is the coordinator caveat |
| postfix `or True` + stale digits | yes (1,1,1) | **`3 passed in 13.88s`** |

The round-1 tautology is the wrong mutation for this rewrite: it makes the pins unlocatable, so the add fails and the new test never gets to its own oracle. `or True` is the class the first version missed.

The rewritten test **catches `or True`**. Procedure: record pin bytes (now tautological) → successful add (still locatable, digits rewritten) → restore the tautological stale bytes → inner tests pass → `assert replay_tests.returncode != 0` and `"3 failed"` fire. The lock goes red, which is the correct failure.

So: the regex structurally enforces the comparison *form* (you cannot delete `" in capsys.readouterr().out)` / `captured.out == "..."` / `len(...) == N` without failing locatability and aborting the add). It does not structurally prevent postfix tautologies. The new test is what locks that remainder. Together they lock the property. I am not treating the unanchored regex as a finding; it is the reason a test like this one is still required, and the test now actually provides it.

## Attack 2 — do both-count assertions do real work?

Yes. I could not construct an upstream failure that plants both `PASS: {new}` and `PASS: {old}` while skipping the literal comparison.

Pin 1 is a single `assert REPLAY.main([]) == 0 and "<old PASS>" in capsys.readouterr().out`. `replay_l2.py` prints `PASS:` only on success. Captured `-q` failure text for that test (stale 1/1 vs live 709/283):

```
E       AssertionError: assert (0 == 0 and 'PASS: 1 entries, 1 clusters' in 'replay-l2: PASS: 709 entries, 283 clusters\n')
```

`0 == 0` is the successful replay; the `in` check is what died. If replay had crashed, the haystack would not contain `PASS: {new}`, and the new-count assertion would fail the lock test (the v1 false-lock path). Add failure is gated earlier (`added.returncode == 0`). A fixture/collection error is an `error`, not a `failed`, and would not print a replay PASS line.

Pin 2 independently shows the same pair as an equality diff (`- PASS: 1 …` / `+ PASS: 709 …`). The both-count checks are therefore pinning the comparison, not a traceback that happens to mention the literals.

## Attack 3 — `"3 failed"` substring

It does not name the nodeids. With this invocation that is enough: the lock test requests exactly those three nodeids and no others, so `"3 failed"` means those three failed. A different trio cannot run. `"13 failed"` cannot occur. `"1 failed, 2 errors"` would not match. Not a finding.

## Attack 4 — vacuous helpers

No.

- `_reported_counts` (`test_add_failure_mode_release.py:232-235`) requires exactly one `replay-l2: PASS: (\d+) entries, (\d+) clusters` and returns ints. Zero matches, two matches, or a non-digit all die on `assert len(matches) == 1` / `int()`.
- `_pinned_counts` (`:238-250`) requires exactly one match of each of the three pin forms, also ints. Empty / `None` / a partial match cannot reach the later assertions.

The discarded `_old_exact_pin` / `_old_embedding_pin` are not a hole: the two PASS pins share one `PASS: N entries, M clusters` string (the thing asserted), and the embedding pin is the third of the three named failures. After one catalog add, entry count moves, so old and new PASS strings differ.

## Attack 5 — do the three pins fail on the literal, on the unmodified branch?

Yes. Same three nodeids, exact lock-test flags (`pytest -q`), stale digits 709/283 → 1/1 against the live consistent corpus (the comparison the rewrite is trying to lock; an add is not required to read the failure text). 7502-byte `-q` log, `3 failed in 9.12s`:

1. `test_committed_snapshot_replays_through_real_default_loader` at `test_replay_l2.py:45` — `assert (0 == 0 and 'PASS: 1 …' in 'replay-l2: PASS: 709 …\n')`. Replay succeeded; `in` failed.
2. `test_default_committed_replay_succeeds_with_network_poisoned` at `test_replay_l2_mutations.py:162` — stdout equality, same two PASS lines, `captured.err` already cleared.
3. `test_vector_id_binding_mutation_reports_partition` at `test_replay_l2_mutations.py:121` — `assert 709 == 1`. Dies on the cardinality literal; never reaches `_run(case) == 1`.

Unmodified three-pin baseline on the same copy: `3 passed in 14.06s`.

The coordinator's "12 passed / tautology → 5 failed including this test" result was not re-derived. Full suite not re-run (~6 min; coordinator running it).

## Attack 6 — third comment

Real. `3200eea` replaced `pipeline/tests/test_replay_l2_mutations.py:157` (`FM-391..396 yield the measured 709-entry partition`) with the same machine-maintained warning the other two pins already carry. Current prose immediately above the three pins:

- `test_replay_l2.py:37-44` — mechanism; historical 708→709 / 281→283 is marked "fixed and not a live count" (the non-derivability evidence, same as `45ac01c`).
- `test_replay_l2_mutations.py:116-120` — mechanism; no live count.
- `test_replay_l2_mutations.py:157-161` — mechanism; no live count.

No current-count restating remains next to the three literals.

## Disposition

The v1 false lock (corrupt L1 → `main() != 0` before the count strings; third pin not invoked; tautologies still red) is gone. The rewrite records pin bytes, requires a successful add, restores stale pin bytes over a still-green corpus, invokes all three pins, and checks `"3 failed"` plus both PASS strings. That is the literal-oracle property. MERGE.
