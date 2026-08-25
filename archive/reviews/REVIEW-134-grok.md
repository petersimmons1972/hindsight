# REVIEW: hindsight PR#134 (lands PR#129's content post-#128)

Reviewer: Grok (grok-build lane, separate harness from the Codex builder), read-only.
Adjudicated by the coordinator (bg job 92e4a093, 2026-08-20 late).

## Verdict: FAIL at 19a816f -> remediated -> MERGE-READY at abf6074

Grok's HIGH finding, CONFIRMED by direct measurement: the two-commit shape was not
bisect-safe -- 409ec38 committed a clusters.jsonl derived from 698 entries while its
snapshot still held 696 embeddings (measured: 696@409ec38 vs 698@19a816f); 19a816f then
moved the snapshot without touching clusters. Head-state was chain-consistent (replay_l2
re-derives and passed) but the intermediate commit was a hazard, and LAND-129-NOTES
misattributed which artifacts moved where.

Remediation: squashed to ONE atomic commit (abf6074) carrying rows + release together;
tree byte-identical to the reviewed one. Grok's secondary caveat (receipt lacked the
command/output pair for its key counts) resolved by coordinator re-measurement.

Verification at the abf6074 tree, coordinator-executed: pytest guard+pipeline 545 passed;
replay_l2 PASS 698 entries / 278 clusters; catalog guard OK, next FM-386; recall
baselines provenance-only. Guard CI green x2 at abf6074.
