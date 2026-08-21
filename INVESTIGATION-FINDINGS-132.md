# hindsight#132 investigation: TF-IDF c-052 boundary fragility

## Verdict

`MAX_CLUSTER_MEMBERS=40`, enforced during average-link agglomeration, is
sufficient by itself.  This is the fix to land.  No threshold adjustment,
feature change, or per-boundary pin was added.

## Reproduction

Starting at `3d23dfe`, I ran the sanctioned fresh-release path in this
worktree:

```text
$ python3 pipeline/capture_embedding_snapshot.py --model BAAI/bge-m3 --revision bge-m3-Q8_0.gguf --dimensions 1024
$ python3 <release-from-snapshot snippet>
regenerated: 696 entries, 276 clusters, threshold=0.22
$ python3 pipeline/replay_l2.py
replay-l2: PASS: 696 entries, 276 clusters
$ python3 -m pytest -q pipeline/tests/test_cluster.py::test_false_positive_novel_failure_does_not_join_an_existing_family pipeline/tests/test_cluster.py::test_ground_truth_contract_with_forced_tfidf_backend
FF
AssertionError: ('completion-signal', 'shared-mutable-checkout')
2 failed in 9.01s
```

The capture command completed successfully against the authorized embedding
host; no artifact was fabricated.  The failure is entirely in the forced
TF-IDF path, as the brief stated.  The HTTP snapshot replay was already
consistent before the fix.

## Root cause and measured margin

This is an average-link sink, not semantic similarity introduced by the two
escaped pipes.  The pipe edit changed the corpus-wide TF-IDF IDF weights by a
small amount.  It did not materially change the strongest direct
cross-family pair:

| Corpus | strongest direct pair | cosine | margin over 0.170 threshold |
| --- | --- | ---: | ---: |
| `3d23dfe^` (unescaped FM-379/382) | `fleet-MDL-18` / `fleet-OPS-36` | 0.202652976 | +0.032652976 |
| `3d23dfe` (escaped FM-379/382) | `fleet-MDL-18` / `fleet-OPS-36` | 0.202640593 | +0.032640593 |

The decisive score is instead the average-link merge between already large
clusters.  Before the edit, no completion-signal/shared-mutable-checkout merge
occurred.  After it, the algorithm merged a 37-member cluster containing five
shared-checkout fixture members with a 66-member cluster containing
`fleet-MDL-18` at **0.172117302**, only **+0.002117302** over the 0.170
cutoff.  That produced a 103-member sink and violated the absolute precision
contract.  Thus a tiny corpus-wide feature-weight perturbation crossed a
2.1e-3 aggregate margin even though the direct offender pair moved only
1.24e-5.

The trace was computed from the exact `3d23dfe^` and `3d23dfe` L1 records,
with only the two changed FM-379/382 records substituted for the pre-edit
case.  The post-edit crossing merge contained these fixture members:

```text
completion-signal: fleet-MDL-18
shared-mutable-checkout: fleet-OPS-13, fleet-OPS-36, fleet-OPS-38,
                         fleet-OPS-41, fleet-OPS-45
```

## Cap evaluation and elimination result

I inspected `baf76222` (`pipeline: cap cluster size during agglomeration
(#130)`), found via `git log --all --oneline --grep cluster`.  Its mechanism
rejects an oversize candidate pair and continues agglomeration; it does not
stop clustering at the first refusal.  The historical commit reports an
independent 25--60 cap sweep at 698 entries with no precision violation or
recall-baseline drop; 40 is an interior value, not a per-trigger threshold.

I then re-ran the exact current 696-entry TF-IDF corpus in memory using that
mechanism, before modifying this branch:

```text
unbounded: 250 clusters; largest=103; forbidden family crossing present
cap=40:   254 clusters; largest=40;  blocked oversize pairs=20;
          forbidden family crossing absent
```

This eliminates the hypothesis that a threshold change or TF-IDF feature
change is required: the same vectors and the same 0.170 threshold pass once
the sink cannot grow beyond 40.  No other candidate fix was pursued, because
the brief explicitly directs landing the cap when it alone dissolves the
fragility.

## Applied fix

`pipeline/cluster.py` now:

1. defines `MAX_CLUSTER_MEMBERS = 40` and includes it in the release digest;
2. blocks any candidate pair whose combined membership would exceed 40, while
   preserving all other candidate merges;
3. retains the existing fraction guard and additionally rejects a bad
   threshold that merely fills many capped clusters (aggregate saturation over
   40% of the corpus).

The aggregation guard matters: without it, a very low threshold can look
healthy merely because a single giant blob is split into many cap-sized blobs.

## Fresh final release and verification

After the code change I repeated the controlled snapshot capture and derived
the L2 partition from that exact snapshot:

```text
$ python3 pipeline/capture_embedding_snapshot.py --model BAAI/bge-m3 --revision bge-m3-Q8_0.gguf --dimensions 1024
$ python3 <release-from-snapshot snippet>
regenerated: 696 entries, 279 clusters, threshold=0.22
$ python3 pipeline/recall_baselines.py --update --backend released
recall-baselines: RECORDED: 15 (family,backend) rows -> recall-baselines.json
$ python3 pipeline/replay_l2.py
replay-l2: PASS: 696 entries, 279 clusters
```

Red-to-green proof for the two required tests:

```text
$ python3 -m pytest -q pipeline/tests/test_cluster.py::test_false_positive_novel_failure_does_not_join_an_existing_family pipeline/tests/test_cluster.py::test_ground_truth_contract_with_forced_tfidf_backend
..                                                                       [100%]
2 passed in 8.42s
```

Full local verification commands all exited zero:

```text
python3 -m pytest guard/tests/ pipeline/tests/ -q
python3 guard/failure_mode_catalog_guard.py
python3 pipeline/replay_l2.py
python3 pipeline/recall_baselines.py --backend released
bats guard/tests/*.bats
bats bin/tests/*.bats
python3 pipeline/reconcile_l1.py --source homelab-canon
python3 pipeline/validate_l1.py
python3 guard/failure_mode_catalog_guard.py --verify-enforcement --require-roots 1
git diff --check
```

Key outputs were: catalog guard `OK (383 canonical IDs)`; replay `PASS: 696
entries, 279 clusters`; released recall baselines `PASS: 5 (family,backend)`;
reconciliation `COMPLETE: 0 enumerable entries unaccounted for (1/1 sources
resolved)`; L1 schema `VALID: no schema violations`.  The enforcement verifier
reported its pre-existing documented one-phantom debt and exited zero.  There
are no remaining failures in the final state; the only initial failures were
the two issue-132 TF-IDF tests reproduced above, and both now pass.

## Reviewer summary

Land the 40-member in-agglomeration cap and the regenerated L2 artifacts.  At
`3d23dfe`, an unrelated two-record text edit moved a 103-member average-link
sink across a 0.002117 TF-IDF aggregate margin, merging completion-signal with
shared-mutable-checkout.  The TF-IDF elimination re-run used identical vectors
and threshold, so the cap's verdict rests on that controlled comparison.  The
HTTP snapshot is a fresh capture: 6 of 696 HTTP-backend embeddings drifted on
recapture (maximum absolute delta 0.036), which is expected embedding-host
nondeterminism; the HTTP-path tests pass against that snapshot.  The cap
preserves the tested recall floor, prevents future large-cluster drift, and
keeps replay internally consistent.
