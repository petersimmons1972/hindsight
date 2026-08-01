# C2 — Recurrence report

## Context

This renders the project's headline deliverable: a document that names, with evidence,
every lesson the fleet has paid for more than once. It is what turns "we keep repeating
ourselves" from an assertion into a citation.

## Files
- **Create** `pipeline/recurrence_report.py`, `pipeline/tests/test_recurrence_report.py`.
- **Input** `pipeline/L2/clusters.jsonl` (from C1). **Output** `pipeline/L2/recurrence-report.md`.

## Behaviour
Read clusters, emit markdown:
1. **Summary** — corpus size, cluster count, how many clusters have >1 member, and the
   single most-repeated root cause with its count.
2. **Recurrence table**, clusters with ≥2 members only, ranked by member count then by
   date span: label, count, member IDs, source repos, first/last seen, span in days.
3. **Per-cluster detail** for the top 15: the label, each member's `instance` text, and
   its source path — so a reader can verify the grouping is real rather than trust it.
4. **Singletons appendix** — count only, plus the note that a singleton is not proof of
   non-recurrence, only of non-detection.
5. **Provenance footer** — backend used, threshold, linkage, generation timestamp, and
   the input file's entry count. A report that does not say how it was produced cannot
   be audited.

## Acceptance (TDD)
Gate: `python3 -m pytest pipeline/tests/test_recurrence_report.py -q`
- Golden-file test over a small synthetic `clusters.jsonl` fixture you author.
- Ranking is correct and stable for ties (deterministic tie-break, assert it).
- A cluster with a null `first_seen` renders without crashing and without inventing a date.
- Empty input produces a valid report stating zero clusters, not a traceback.
- The provenance footer is present and reflects the `_meta` line.

## Constraints
Read-only with respect to `clusters.jsonl`. No network. stdlib only.

## Out of scope
Clustering (C1); any judgment about what the clusters *mean* (that is W1/W2, done by
synthesis agents, not by this renderer).

## Model
`--harness codex --effort medium`.
