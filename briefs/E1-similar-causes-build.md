# E1 stage 2 — BUILD `bin/similar-causes.py` against a spec you did not write

**You are the implementer. You are stage 2 of 3.** A different vendor wrote the acceptance suite
before you existed on this packet, and a third vendor will attack your work afterwards.

Read `QA-PROTOCOL.md` in the repo root first — it explains the ordering and what is being measured.
Then read `CLAUDE.md` for the non-negotiables.

## Your one job

Make `bash bin/tests/test_similar_causes.sh` pass by writing `bin/similar-causes.py`.

The suite is already in the tree — 27 tests across 7 fixture corpora. Read it. It is the contract.

## The rule that matters most

**You may add tests. You may not weaken, delete, skip, relax or exempt a single existing one.**

This is enforced, not requested: `bin/tests/test_similar_causes.sh` is in the dispatch protect-set,
and any modification to it aborts your run. So put additional tests in a **new** file,
`bin/tests/test_similar_causes_extra.sh`, rather than appending to the protected one.

If you believe a test is wrong, do not edit it. Stop, leave it failing, and say so explicitly in
your summary with your reasoning. A test you cannot satisfy is information; a test you quietly
edited is a manufactured green, and this repository has already closed one PR unmerged for exactly
that (15 lines changed across 6 corpus files took a phantom count 15 → 0; restoring the data
restored all 15).

Changing the suite to fit the implementation is the single failure this three-stage shape exists to
prevent. It will be checked by diffing your branch's test file against the committed one.

## What the tool is

A **lookup**, not a guard. For a proposed failure-mode description, print the corpus entries most
worth a human's attention, and say plainly that it does not determine duplication.

C3 was originally specified as a guard that would *reject* duplicate causes. That was cancelled by
measurement: three approaches were tested against blind holdouts and all three missed the bar
(pooled recall@5 of 1/77, 0.523 and 0.262 against a 0.70 requirement; distractor separation at or
below chance in every case). The binding constraint is that the maximum distractor score **exceeds**
the maximum true-positive score, so no threshold separates them at any operating point.

Consequences for you, and the suite enforces all of them:

- **Never exit non-zero because a match was found.** Exit codes report operational failure only.
- **Never emit language asserting something IS a duplicate.** It prints candidates; a human judges.
- **Do not add a `--threshold`, `--reject`, `--check-duplicate` or equivalent flag.** T21 exists
  specifically to stop the guard being reintroduced through an option.

## Ranking

Your choice. **Ranking quality is explicitly not under test** — the measurements above already
established that no available ranker clears a quality bar, and asserting recall here would
re-litigate a settled question. Something simple, deterministic and dependency-free is correct.
Do not add a dependency to chase accuracy that has already been measured as unreachable.

Standard library only. The runner is a plain Debian image where `pip install --user` fails with
`externally-managed-environment` (PEP 668) — a previous packet lost a round to this.

## Hard constraints

- **Never modify anything under `pipeline/L1/`.** It is the source corpus, and it is protected at
  dispatch time. A PR was closed unmerged for editing it.
- **Never modify `catalog/failure-modes.md`.**
- The tool is **read-only at runtime**: it must not write, move or create any file, including
  caches or sidecars. T19/T20/T27 hash the tree and will catch it.
- Do not touch any file outside `bin/similar-causes.py` except to ADD tests.

## Verification you must actually run

State the literal output of each in your summary — not a claim that you ran it:

```bash
bash bin/tests/test_similar_causes.sh          # must be: 27 passed, 0 failed
git diff --stat origin/main -- bin/tests/      # must show additions only, no changes to existing tests
python3 guard/failure_mode_catalog_guard.py    # must exit 0
```

Then **mutation-test your own work** — it is the technique that found every real defect in this
campaign, and stage 3 will use it against you. Break your implementation in at least four ways
(make the header conditional; make a found match exit 1; silently cap at 10 without disclosing;
treat an empty corpus as zero candidates) and confirm the suite catches each. Report any mutation
that **survives** — a surviving mutant is a hole in the suite, and reporting it is worth more to
this packet than hiding it.

## Budget

**Cap: 60 tool calls.** If you hit it, stop and say exactly what is unfinished. A partial result
reported as complete is worse than a reported cutoff.

## Deliverable

Your final summary must begin with a literal first line, one of:

`BUILD COMPLETE: 27/27 passing, 0 existing tests modified`
`BUILD INCOMPLETE: <n>/27 passing` — followed by which tests fail and why you could not satisfy them.
