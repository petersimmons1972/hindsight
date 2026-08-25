# Independent review: hindsight PR#139 (hindsight#108)

**Branch:** `fix-108-derive-pins` (detached HEAD `45ac01c`)
**Base:** `main` `d8b3c5a`
**Commits:** `be8f5a8` (Codex, pin updater) then `45ac01c` (Claude coordinator, comments)
**Reviewer:** Grok. Neither prior party is independent of this change.
**Worktree:** `/home/psimmons/worktrees/review-108-grok` — left clean; no other file modified; no commit/push/merge.

**Verdict: MERGE**

The anti-tautology property is intact: the three pins are still compile-time literals, they still go red when the corpus or the literals drift, and cluster count is parsed from the replay report rather than computed from N. I could not break the write transaction, the fail-loud path, or fail-open the production regex on any realistic replay output. The dedicated anti-tautology test is weaker than its name, and the coordinator's comment commit left one live count in prose; neither is a merge blocker.

---

## What I ran (verified)

| Command | Result |
|---|---|
| `python3 -m pytest -q --color=no` in this worktree | **557 passed** in 339.35s (main baseline 554; this branch adds exactly 3 tests) |
| `bats bin/tests/test_add_failure_mode.bats` | **27 passed** |
| Pin tests on an unmodified `/tmp` copy of the tree | 3 passed |
| Same tests after L1 corruption outside the filing flow | 3 failed (red) |
| Same tests after rewriting the three literals to 708/281 with corpus unchanged | 3 failed **on the count comparisons** (replay itself still exited 0) |
| Same tests after making the count asserts tautological *and* corrupting L1 | still 3 failed |
| Extracted pin-updater against adversarial reports and smashed pin files | fail-closed; no partial write |
| `git diff be8f5a8 45ac01c` with comment lines stripped | **zero** non-comment changed lines |
| `git status` after all of the above | clean; pin files byte-identical to HEAD |

All mutation/corruption work was on `/tmp/review-108-attack/`. The real catalog was not filed into. `CATALOG=` overrides were used by bats and the release tests' own harness.

---

## Attack 1 — anti-tautology

**The three pins are still literals.** Confirmed by reading the files at HEAD:

- `pipeline/tests/test_replay_l2.py:45` — `"PASS: 709 entries, 283 clusters"` inside `assert ... and "..." in capsys.readouterr().out`
- `pipeline/tests/test_replay_l2_mutations.py:158` — `assert captured.out == "replay-l2: PASS: 709 entries, 283 clusters\n"`
- `pipeline/tests/test_replay_l2_mutations.py:121` — `assert len(payload["embeddings"]) == 709`

No test-time parse of the replay report, no `len(entries)`, no `re.search(r'\d+')` on stdout to build the expected value.

**Corrupt the corpus outside the filing flow (user-specified attack).** On a `/tmp` copy, one `"instance"` → `"instance_x"` in `pipeline/L1/homelab-canon.jsonl`, then the three pin tests:

```
3 failed in 0.71s
```

They went red. That is **not** a blocker under the stated criterion.

They did **not** go red *because of the count literals*:

- `test_committed_snapshot_replays_through_real_default_loader` failed `assert (1 == 0)` on `REPLAY.main([])` (short-circuit; the `"PASS: 709..."` conjunct was never evaluated). Stderr: `missing required fields ['instance']`.
- `test_default_committed_replay_succeeds_with_network_poisoned` failed the same `main() == 0` check, **before** line 158's exact string compare.
- `test_vector_id_binding_mutation_reports_partition` **passed** `len(...) == 709` (snapshot cardinality unchanged) and failed later on the expected `partition mismatch` prefix.

**Wrong literals, corpus unchanged (the actual oracle).** Restored L1, rewrote only the three digits to 708/281:

- Replay exited 0 and printed `PASS: 709 entries, 283 clusters`.
- All three tests failed on the literal comparison (`'PASS: 708...' in 'PASS: 709...'`, exact `==` mismatch, `709 == 708`).

So the pins still catch a successful replay whose counts do not match. That is the property the filing-flow updater must not destroy. It did not destroy it.

**The PR's own lock for this property does not lock it.** See Finding 1.

---

## Attack 2 — is M parsed or computed?

**Parsed. Independently.** `bin/add-failure-mode.sh:607-613`:

```python
matches = re.findall(r"^replay-l2: PASS: (\d+) entries, (\d+) clusters$", report, flags=re.MULTILINE)
...
entries, clusters = matches[0]
```

Both groups come from the same match. `clusters` is never `str(int(entries))` or similar. The three rewrites substitute `{entries}` and `{clusters}` separately; the embedding pin uses `{entries}` only.

**Verified:** running the extracted updater with `replay-l2: PASS: 999 entries, 1 clusters` wrote `PASS: 999 entries, 1 clusters` into both stdout pins and `== 999` into the embedding pin. M is not a function of N.

**Historical claim is true.** `d8b3c5a` (FM-396) is the measured 708→709 / 281→283 move. `86b38e7` is 707→708 / 280→281. Adding one entry has moved clusters by +1 and by +2. Computing M from N is wrong, and this branch does not do it.

---

## Attack 3 — transaction integrity

**Can it write a pin it did not snapshot?** Not on the current control flow. Snapshot of both pin files is `bin/add-failure-mode.sh:444-445`, inside `if [[ $RUN_FULL_LOOP -eq 1 ]]`. The rewrite is lines 599-658, inside the same `if` that starts at 494. Light-path (`CATALOG=` override, `RUN_FULL_LOOP=0`) never snapshots pins and never writes them. I read the whole script; there is no second write site.

**Can it snapshot without writing?** Yes, and that is the rollback path: snapshot is taken *before* any catalog write (433-446), pin rewrite is after replay (591+). Any failure in between leaves snapshots unused until the `EXIT` trap (`rollback_on_error`, 451-458) restores. That is correct.

**Death between catalog append and pin rewrite.** Under `set -e`, a non-zero child fires `EXIT` and `restore_journal` puts the tree back, pins included (expected set at 71-72). SIGKILL does not run the trap: catalog/L1/L2 can be new and pins still old. That crash window already existed for every other file in this journal. This branch **adds two files to the same window**; it does not create a new class of half-write. After a SIGKILL in that window the stale literals would fail tests (same shape as main, where pins were never auto-updated). The journal on disk would still contain the pin snapshots if the process got as far as printing `UNDO:`.

**Validate-all-then-write holds.** Extracted updater: smash the *second* pin file, first file locatable — first file hash unchanged after `SystemExit`. Writes happen only after every `subn` returns `count == 1`. A later `write_text` error is covered by the existing undo trap (comment at 653-655 is accurate).

**Pin write outside `RUN_FULL_LOOP`?** No such path.

I could not produce a pin write that was not snapshotted, or a successful add that left pins unrestorable by `--undo`. The Python test `test_successful_canonical_add_derives_all_replay_pins_and_undo_restores_them` passed as part of the 557.

---

## Attack 4 — fail-loud, no partial write

**Verified on the extracted updater (no catalog involved):**

- Smash `test_replay_l2.py` → `SystemExit` `"found 0 matches"`, mutations file hash unchanged.
- Smash `test_replay_l2_mutations.py` → same, first file hash unchanged (so not an eager first write).
- Duplicate the first pin assertion → `"found 2 matches"`, no write.

**Verified on the full script by running the suite:** `test_unlocatable_replay_pin_fails_loudly_without_partial_write` is one of the three new tests inside the 557. It replaces the first pin file with `"pin intentionally unavailable\n"`, asserts non-zero exit, `"replay pin"` in output, and digest equality for catalog, ledger, L1, snapshot, clusters, and both pin files.

I did not re-run that one test in isolation on top of the 557; the 557 includes it. Combined with the extracted-updater hashes, I am satisfied both halves hold: non-zero exit, no partial write, catalog not left mutated.

The suite test only smashes pin file 0. The extracted updater closes the gap for pin file 1 and for ambiguity.

---

## Attack 5 — the regex

Production parser (`bin/add-failure-mode.sh:607`):

`r"^replay-l2: PASS: (\d+) entries, (\d+) clusters$"` with `re.MULTILINE`.

Fed the extracted parser:

| Input | n matches | Behaviour |
|---|---|---|
| Happy path | 1 | accept 709, 283 |
| Empty / FAIL line / N-only | 0 | fail-closed |
| Log prefix on the same line | 0 | fail-closed |
| ANSI around `PASS` or the whole line | 0 | fail-closed |
| Thousands separator `1,234` | 0 | fail-closed |
| PASS text inside a longer same-line error | 0 | fail-closed |
| Two PASS lines | 2 | fail-closed (`!= 1`) |
| CRLF, trailing space, leading space, tab | 0 | fail-closed |
| Float, negative, extra parenthetical | 0 | fail-closed |
| Exact line, no trailing newline | 1 | accept (print() always has `\n`, so not live) |
| PASS then FAIL / FAIL then PASS (PASS on its own line) | 1 | accept |
| PASS as its *own line* inside a surrounding error message | 1 | **accept** |
| Fullwidth unicode digits `７０９` | 1 | accept (`\d` is Unicode Nd in Python) |

Fail-closed on everything the prompt named except:

1. **A PASS line that is a whole line inside some other message.** Current `replay_l2.py:128-130` prints PASS only on success, once, to stdout; errors go to stderr, which is **not** in `REPLAY_OUTPUT`. And a non-zero replay never reaches the updater (`set -e` on the command substitution at 591). Fail-open here is dormant given today's `replay_l2.py`.
2. **Unicode Nd digits.** `print(f"... {entries} ...")` with a Python `int` cannot emit them. Dormant.

Rewrite patterns at 619-635 are unique in the current pin files (1/0/0 and 0/1/1 across the two files). Happy rewrite to 710/284 updated digits only; the historical `708 -> 709` / `281 -> 283` comment was left intact (the updater rewrites digits, not comments — measured).

---

## Attack 6 — second commit `45ac01c`

**Executable delta is empty.** `git diff be8f5a8 45ac01c` with comment-only `+/-` lines removed: no remaining lines. Two files, comments only. Coordinator's subset re-run of 39 tests was more than this delta needed; the full 557 still passes.

**On its merits.**

The commit's stated rule is: do not restate a *live* count in prose, because the updater rewrites digits not comments; keep the 708→709 / 281→283 move as *historical, fixed* evidence that M is not f(N).

That split is self-consistent, and the historical numbers are factually right (`d8b3c5a`'s own message: "Repinned once for this add: 708 -> 709 entries, 281 -> 283 clusters.").

It does **not** finish the job it names. See Finding 2.

Nothing else in that commit is factually wrong. "one said 707 above an assertion of 709" matches `be8f5a8`'s embedding-pin comment vs `== 709`.

---

## Attack 7 — test discrimination

New assertions, each with a **single-line** change to `bin/add-failure-mode.sh` that leaves **that** assertion green:

| Assertion | File:line | Single-line script change that stays green |
|---|---|---|
| `added.returncode == 0` (derive test) | `test_add_failure_mode_release.py:360` | Delete the pin-updater `python3` block. Add still succeeds; later pin-equality fails, this one does not. |
| `replay_pin == (entries, clusters)` | `:363` | Drop `^` and `$` on line 607. Honest replay stdout is still exactly one such substring; helper `_reported_counts` (line 233) is already unanchored, so both sides still agree. |
| `exact_pin == (entries, clusters)` | `:364` | Same `^$` deletion. |
| `embedding_pin == entries` | `:365` | Same. Or `{int(entries)}` instead of `{entries}`. |
| undo restores pin digests | `:372-373` | None that I found which is both one line and still a real undo bug. Removing *only* the snapshot lines makes `restore_journal` fail "incomplete" (expected set still lists the pins). This pair actually discriminates. |
| unlocatable: `returncode != 0` | `:391` | `if count != 1` → `if False` and also `raise SystemExit("ERROR: replay pin")` unconditionally: still != 0. Cheap. A *real* miss: see uniqueness below. |
| `"replay pin" in stdout` | `:392` | Change the error to `"ERROR: replay pins broken"` — still contains the substring. |
| protected digests == before | `:393` | Write eagerly after each spec, rely on rollback. The test smashes file 0 first, so even eager write never reaches a mutation of a protected file. Does **not** distinguish validate-then-write from write-then-rollback. |
| drift test: `returncode != 0` and `"2 failed"` | `:415-419` | **`clusters = entries`** after line 613. Pins become `(N, N)`. Derive test would die; **this test stays green**, because L1 corruption fails `main() == 0` / missing `instance`, never the count literals. |

**Missed mutation (the prior "6 mutations all killing cases" report).**

`if count != 1` → `if count == 0` at `bin/add-failure-mode.sh:647`.

That drops the uniqueness half of fail-loud (two matching asserts in one file would both be rewritten). Every new test stays green: the unlocatable test uses 0 matches, not 2; the fixtures have exactly one match per pattern. I independently confirmed the production code *does* refuse 2 matches; the suite just never asks.

Second miss, more serious: the drift test does not die if the pin tests themselves are made tautological. See Finding 1. That is a test-file mutation, not a script mutation, but it is the mutation the drift test exists to kill and it does not kill it.

No new assertion is incapable of failing. Several are capable of failing for the wrong reason, or of surviving the mutation they advertise.

---

## Attack 8 — worse than main?

**New way for filing to fail:** yes, and it is the point. If a pin pattern is unlocatable or the replay report is not exactly one PASS line, the add aborts and the trap rolls the catalog back. On main, filing succeeded and CI went red until someone hand-edited the pins. That is a new operational failure (a reformat of those three asserts now aborts every canonical add) and it is fail-loud rather than silent. I do not treat it as a defect.

**New way to corrupt the tree:** not in kind. The crash window now includes two test files; they are in the journal and in `restore_journal`'s expected set. SIGKILL in the old window already left catalog vs L2 inconsistent; now catalog vs pins can be inconsistent the same way. Non-KILL failures restore both.

**Light path** (`CATALOG=` override) is unchanged: no pin I/O. Confirmed by bats (CATALOG-overridden tests) and by `test_non_canonical_add_does_not_trigger_a_release`.

I could not find a successful-add path that leaves the real catalog mutated when a pin rewrite fails.

---

## Findings

### Finding 1 — Severity: MAJOR

- **File:** `bin/tests/test_add_failure_mode_release.py:396-420`
- **What is wrong:** `test_external_corpus_drift_still_fails_the_literal_replay_pins` does not test that the count literals are independent oracles. It corrupts L1 so replay *fails* (`missing required fields ['instance']`). Both selected tests die on `REPLAY.main([]) == 0`. The count strings are not consulted. The third pin (`len == 709`) is not even in the pytest invocation.

  I reproduced the claimed red, then reproduced the same red after replacing the literals with tautologies (`assert REPLAY.main([]) == 0`, `assert captured.out.startswith("replay-l2: PASS:")`, `assert len(...) == len(...)`). A future change that derived expected counts from the replay report at test time would keep this test green.

- **Reproduction:**
  ```bash
  # on a copy, not the worktree
  # 1) corrupt L1 as the test does → pin tests fail on main()==0
  # 2) restore L1, make the three asserts tautological, corrupt L1 again → still fail
  # Contrast: restore L1, change only 709/283 → 708/281 → fail on the literals while replay exits 0
  ```
- **What I would change:** Drive a *successful* replay with different counts, then expect the literals to disagree. Concrete: after a canonical add, restore the two pin files from their pre-add bytes (or rewrite them to N-1), leave L1/L2 at the post-add snapshot, run the three pin tests, assert they fail *and* that the failure text contains the old vs new counts. Keep the L1-byte corruption as a separate digest test if you want it; do not call it the anti-tautology lock. Include `test_vector_id_binding_mutation_reports_partition`.
- **Status:** open
- **Not a blocker of the product:** the literals themselves still work (Attack 1b). This is a false lock in the new tests.

### Finding 2 — Severity: MINOR

- **File:** `pipeline/tests/test_replay_l2_mutations.py:157`
- **What is wrong:** Commit `45ac01c` says it replaced the live-count comments and that the updater rewrites digits, not comments, so any live count in prose will lie. It fixed the comments above the first two pins and left the third:

  ```
  # fm-backlog 2026-08-21: FM-391..396 yield the measured 709-entry partition (cluster count per replay).
  assert captured.out == "replay-l2: PASS: 709 entries, 283 clusters\n"
  ```

  That 709 is a live count. The next successful canonical add will update line 158 and leave line 157 wrong — the exact failure the commit exists to prevent. The historical 708→709 / 281→283 block in `test_replay_l2.py:41-42` is marked "fixed and not a live count" and is fine.

- **Reproduction:** `sed -n '155,159p' pipeline/tests/test_replay_l2_mutations.py`. Extracted updater rewrite to 710/284 left this comment at 709.
- **What I would change:** The same machinery comment used above line 121, with no numeral. Do not restyle it in a follow-up that the coordinator then "verifies" with a subset run; it is a one-line comment.
- **Status:** open

### Finding 3 — Severity: MINOR

- **File:** `bin/add-failure-mode.sh:647` (untested uniqueness) and `bin/tests/test_add_failure_mode_release.py:233` (looser helper)
- **What is wrong:** Two production constraints have no killing test:
  1. `count != 1` (ambiguous pins). The unlocatable test only covers `count == 0`.
  2. Anchored report parse. `_reported_counts` uses `replay-l2: PASS: (\d+) entries, (\d+) clusters` with no `^$`. Deleting the anchors on line 607 leaves every new assertion green. I measured the helper accepting prefixed, ANSI-wrapped, CRLF, and in-line-error forms that production rejects.
- **Reproduction:** extracted updater with a duplicated assert → fail-closed (mechanism works). Single-line `if count != 1` → `if count == 0` would not be caught. Single-line deletion of `^` and `$` on 607 would not be caught.
- **What I would change:** Import or copy the production regex into the test helper (one source). Add a fixture with two matching pin lines and assert fail-loud + no write. Optional: one case whose add stdout contains a prefixed PASS line, and assert the updater refuses rather than that the helper parses it.
- **Status:** open

No BLOCKER findings. I could not make the pin tests stay green against outside-filing corpus corruption, could not make the updater compute M from N, could not get a pin write without a snapshot on this control flow, and could not get a partial write on an unlocatable pin.

---

## Verified vs reasoned

**Verified by running**

- Full pytest 557 / bats 27.
- Pins are literals; wrong literals fail on the comparison while replay is green.
- L1 corruption outside filing turns the three tests red.
- Tautological pin tests still go red under that same L1 corruption (so the PR's drift test does not uniquely protect the literals).
- M is taken from the second parse group; 999/1 writes through.
- Unlocatable / duplicate pins: `SystemExit`, no hash change on either file.
- Adversarial report table above.
- `45ac01c` is comment-only.
- Historical 708→709 / 281→283 is in `d8b3c5a`.
- Worktree clean after the review.

**Reasoned from the script (not crash-injected)**

- SIGKILL between catalog append and pin rewrite leaves a half-written tree; same class as the pre-existing journal window.
- `set -e` + EXIT trap rolls back non-KILL failures, including pin-updater `SystemExit`.
- A PASS-shaped whole line inside an error message would be accepted *if* it were the only match *and* replay exited 0; today's `replay_l2.py` does not produce that.
- Bats undo tests (lines 362-367, 654-658) never digest the pin files; pin undo is covered by the Python test, not by bats.

---

## Verdict

MERGE
