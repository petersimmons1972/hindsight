# LAND-129 release notes

## Conflict resolution

Cherry-picked `7ba5585` onto main at `22699d0`. The catalog-facing artifacts
retain main's FM-377 through FM-383 and add FM-384 and FM-385 in numeric order.
The three conflicting derived L2 artifacts initially retained main's release
state, then were replaced through the sanctioned fresh-release procedure below;
`pipeline/cluster.py` was not changed.

## Fresh release

- Captured a fresh HTTP embedding snapshot with `BAAI/bge-m3`, revision
  `bge-m3-Q8_0.gguf`, dimensions 1024.
- Released from that snapshot: 698 entries, 278 clusters, threshold 0.22.
- `pipeline/recall_baselines.py --update --backend released` completed without
  `--allow-drop`; all five released family baselines remain at or above their
  recorded floors. The only baseline-artifact changes are release provenance:
  corpus size 696 to 698 and the L1 digest.

## Pin changes

- `test_replay_l2.py`: `696/279` to `698/278`.
- `test_replay_l2_mutations.py`: snapshot vector count `696` to `698`; replay
  output `696/279` to `698/278`.
