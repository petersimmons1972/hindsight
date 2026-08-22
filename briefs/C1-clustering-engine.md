# C1 — Clustering engine

## Context

This is the keystone packet. Everything downstream — the recurrence report, the family
and global synthesis, and the duplicate-cause guard that finally makes the registry a
gate — consumes your output. If your clusters are wrong, every later stage produces
confident nonsense from them.

The job: group the 458 L1 entries by *underlying root cause*, so that the same failure
described in different vocabulary by different people at different times lands in one
cluster. That is the whole point — lexical near-duplicates are easy and are not the
problem. "The tool exited 0 but produced nothing" and "the agent reported complete
while its artifact was absent" are the same failure and must cluster together.

## Files

- **Create** `pipeline/cluster.py` — the engine.
- **Create** `pipeline/tests/test_cluster.py` — the tests.
- **Do not modify** `pipeline/L1/*`, `pipeline/tests/fixtures/*`, or `pipeline/reconcile_l1.py`.

## Design

**Pluggable embedding backend, two implementations behind one interface:**

1. `HttpEmbeddingBackend` — POSTs to a local embedding server, default
   `http://leviathan.petersimmons.com:8004` (llama.cpp/ROCm, already running). Probe it on init with
   a short timeout (≤3s). This is the **only** authorised network call in this packet,
   and only to that host. Discover the endpoint shape defensively: try
   `/v1/embeddings` (OpenAI-style `{"input": [...]}` → `{"data":[{"embedding":[...]}]}`)
   and `/embedding` (llama.cpp native). If neither answers correctly, the backend
   reports unavailable — it must not raise past init.
2. `TfidfEmbeddingBackend` — numpy only. Character n-gram (suggest 3–5) plus word
   unigram TF-IDF, L2-normalised. No sklearn: implement the vectoriser directly.

Selection: HTTP if reachable, else TF-IDF. **Log which backend was selected, loudly, to
stderr and into the output file's metadata.** A silent backend switch that changes
results is unacceptable.

**Clustering:** cosine similarity over the full 458×458 matrix (trivial at this size),
then agglomerative merge with a tunable threshold (`--threshold`, sensible default).
Single-link merging tends to chain and over-merge; prefer average-link or complete-link
and justify your choice in the module docstring.

**Text used for similarity:** compose from `instance` primarily, with `check` and
`class_hint` as secondary signal. Do **not** use `id` or `source_path` — clustering on
IDs would let entries group by where they came from rather than by what went wrong,
which is precisely the identity-key defect catalogued as ORC-1a/b/c. Guard against it.

## Output

`pipeline/L2/clusters.jsonl` — one JSON object per cluster:

```json
{"cluster_id":"c-001","size":7,"members":["fleet-OPS-11", "..."],
 "source_repos":["fleet","claude-codex"],"first_seen":"YYYY-MM-DD|null",
 "last_seen":"YYYY-MM-DD|null","representative":"<member id>",
 "label":"<short human-readable root-cause phrase>"}
```

Plus a `_meta` first line recording backend used, threshold, entry count, and linkage.
Singleton clusters are legitimate output — most entries are not recurrences — and must
be emitted, not dropped.

## Acceptance (TDD)

Gate: `python3 -m pytest pipeline/tests/test_cluster.py -q`

Your tests **must** load `pipeline/tests/fixtures/recurrence_ground_truth.json` and
assert every contract it declares. That file is coordinator-authored ground truth; it
is not yours to edit, and editing it to make a test pass is an automatic fail.

Required assertions, at minimum:

1. **Recall** — for each family, ≥75% of its members land in one cluster.
2. **Precision** — no pair listed in `must_not_merge` shares a cluster. *Recall alone
   is trivially satisfiable by putting the whole corpus in one cluster; precision is
   what makes it meaningful. Both must hold simultaneously.*
3. **Headline** — the completion-signal cluster is reported with ≥6 distinct members.
4. **Backend-agnostic** — the same assertions pass with the TF-IDF backend forced. Write
   this test so it forces the fallback explicitly rather than depending on network state,
   so it is deterministic in CI where the embed host is unreachable.
5. **No ID leakage** — a test proving that entries do not cluster merely because their
   IDs share a prefix (e.g. construct two entries with adjacent IDs and unrelated text
   and assert they do not merge).
6. **Determinism** — same input and threshold produce identical cluster assignment
   across runs.

If the TF-IDF backend cannot meet the ground-truth bar, **do not lower the bar**. Tune
the representation — n-gram range, weighting, threshold, linkage. If after genuine
effort it still cannot, stop and report that in the PR body with the numbers you
measured. Reporting a real limit is a good outcome; quietly relaxing the fixture is not.

## Constraints

- numpy only. No sklearn, no torch, no vector DB. See shared context item 6.
- Runtime budget: full clustering of 458 entries must complete in under 60s on the
  TF-IDF path.
- Network: only the embedding host named above, only on the HTTP path, always with a
  timeout, never fatal on failure.

## Out of scope

- The recurrence report (packet C2 consumes your `clusters.jsonl`).
- The guard integration (packet C3).
- Any change to the L1 corpus or the reconciler.

## Model

`--harness codex --effort high`. This packet carries the most design judgment of the set.
