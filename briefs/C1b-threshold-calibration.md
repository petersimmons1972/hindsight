# C1b — Per-backend threshold calibration (REPAIR)

## Context

`pipeline/cluster.py` (PR #3) passes its test suite and is broken on the real path.

Measured on the 458-entry corpus:
- `--backend tfidf` : 200 clusters, largest 21. Recovers every ground-truth family
  (completion-signal 6/7 in a cluster of 7; fail-silent 4/4 in 10; dedup-key 3/3 in 7;
  convergence 2/2 in 3). This is GOOD and is the validated configuration.
- `--backend http`  : **ONE cluster containing all 458 entries.**

Cause: `DEFAULT_THRESHOLD = 0.17` was tuned for sparse TF-IDF cosine and reused unchanged
for dense neural embeddings, whose baseline cosine between arbitrary texts is far higher.
Everything exceeds 0.17, so average-link merges the entire corpus.

The suite missed this because every test forces the TF-IDF fallback for determinism. That
is a test suite passing while the feature is broken — the defect class this repo exists to
catalogue.

## Files
- **Modify** `pipeline/cluster.py`, `pipeline/tests/test_cluster.py`.
- **Never modify** `pipeline/tests/fixtures/recurrence_ground_truth.json`.

## Required changes

1. **Per-backend thresholds.** Each backend declares its own default. `--threshold` still
   overrides. Calibrate the HTTP default empirically against the live endpoint
   (`http://leviathan.petersimmons.com:8004`, healthy, ~13ms per single embedding) so the ground-truth
   families are recovered with the same recall/precision the TF-IDF path achieves. Record
   the measured numbers you used in the module docstring — a magic constant with no
   recorded derivation is how the current bug happened.

2. **A degeneracy invariant, enforced at runtime and in tests.** Clustering must FAIL LOUD
   when the result is degenerate on ANY backend, e.g. a single cluster holding more than
   ~40% of the corpus, or a multi-member cluster count of 1. Emitting one 458-member
   cluster as a successful result is the worst possible outcome: it satisfies every recall
   check while destroying all information. Exit non-zero with a clear message naming the
   backend and threshold.

3. **Tests must exercise the ACTIVE backend, not only the fallback.** Keep the
   deterministic forced-TF-IDF tests. ADD a test that runs the HTTP backend when reachable
   and asserts the same ground-truth contract, and SKIPS (not passes) when unreachable — a
   skipped test reads as untested; a passed one reads as verified, and that difference is
   the whole bug.

4. Add a regression test pinning the degeneracy invariant itself: construct an input where
   a too-low threshold would merge everything, and assert the run FAILS rather than
   returning one cluster.

## Acceptance
Gate: `python3 -m pytest pipeline/tests/test_cluster.py -q`
Plus, verifiable by the reviewer: `python3 pipeline/cluster.py --backend http` must produce
a non-degenerate clustering that recovers the ground-truth families, or exit non-zero.

## Constraints
numpy only. Network only to the embedding host named above. Do not lower any bar in the
fixture; if a backend cannot meet it, make that backend fail loudly and say so in the PR.

## Model
`--harness codex --effort high`.
