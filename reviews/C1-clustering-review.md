# Adversarial review — PR #3 / C1 clustering engine

**Reviewer:** Grok (independent vendor from author/Codex)  
**Target:** `dispatch/C1-clustering-engine` @ `536071d` (+ parent `fd0d0ff`)  
**Scope:** `pipeline/cluster.py`, `pipeline/tests/test_cluster.py`, consumption risk for `pipeline/L2/clusters.jsonl`  
**Method:** re-run suite; re-derive HTTP vs TF-IDF on the live embed host; mutate implementation/contract; construct FP/FN inputs against the ground-truth fixture.

Default posture: **reject the premise**. The question is not “does TF-IDF recall look good on a green day,” it is **can this suite pass while clustering is broken for the path operators actually run**.

---

## Executive result

**FAIL.** Independently confirmed:

1. The packet suite is **currently red** (1 failed / 7 passed).
2. The **default production path** (`--backend auto` → live HTTP @ `DEFAULT_THRESHOLD=0.17`) collapses the entire 458-entry corpus into **one cluster**. That output is already on disk in the author worktree as `pipeline/L2/clusters.jsonl` (`backend: http`, `size: 458`).
3. HTTP **never** clears the ground-truth contract at any threshold tried in `{0.17, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85}`.
4. The suite **never exercises HTTP clustering quality**. It forces TF-IDF for the only ground-truth gate. A silent / default HTTP path that writes confident nonsense stays invisible.
5. TF-IDF “success” on ground truth is **load-bearing on hand-authored regex markers** (`_cause_shape_markers`) tuned to fixture wording — not pure embedding similarity. Remove the markers → completion-signal recall drops to ~0.29 and the suite fails.
6. Concrete **false-positive** and **false-negative** inversions exist for the TF-IDF+marker path; the suite does not look for either.

Coordinator commit `536071d` already discloses the HTTP collapse. This review re-derives that claim and treats the disclosure as **admission of an open blocker**, not as clearance.

---

## Suite status (actually run)

```
python3 -m pytest pipeline/tests/test_cluster.py -q
→ 1 failed, 7 passed
FAILED test_http_backend_discovers_native_per_text_embedding_shape
  assert 120.0 <= 3.0   # test_cluster.py:158
```

Cause: coordinator timeout split (`probe_timeout≤3s`, `request_timeout=120s`) was not paired with a test update. The test still asserts every `urlopen` timeout is `≤3.0`, so **bulk embed correctly using 120s fails the only HTTP test**.

This is a small symptom of the larger defect: the suite’s HTTP coverage is a **shape/timeout unit probe**, not a clustering acceptance gate.

Guard suite on this branch: green (unrelated to C1 quality).

---

## Claim re-derivation: both backends clear the bar

### TF-IDF @ 0.17 (forced)

| Metric | Result |
|--------|--------|
| clusters | 200 |
| max size | 21 |
| completion-signal together | 6/7 (0.857) — outlier `fleet-MDL-18` alone |
| shared-mutable-checkout | 6/7 (0.857) — outlier `fleet-OPS-48` alone |
| fail-silent-gate | 4/4 |
| dedup-identity-key | 3/3 |
| convergence-not-corroboration | 2/2 |
| listed must_not_merge pairs | all disjoint |
| headline (≥6) | 6 |
| wall time | ~1.8s |

**TF-IDF meets the fixture numbers.** That is real for this path only.

### HTTP (live `http://leviathan.petersimmons.com:8004`, endpoint `/v1/embeddings`)

Probe: `HttpEmbeddingBackend().available is True` — **genuinely networked**, not a silent TF-IDF fall-through.  
Mean off-diagonal cosine under L2-normalised neural embeddings: **~0.475** (dense, high baseline). Sparse TF-IDF baseline is far lower; the shared default `0.17` is therefore not a shared scale.

| threshold | n clusters | max size | GT contract |
|-----------|------------|----------|-------------|
| 0.17 | 1 | **458** | **FAIL** (all precision pairs merge) |
| 0.40 | 1 | 458 | FAIL |
| 0.50 | 37 | 145 | FAIL (recall+precision) |
| 0.55 | 111 | 35 | FAIL |
| 0.60 | 200 | 13 | FAIL |
| 0.65–0.85 | 303–431 | 10 | FAIL (completion recall stuck ~0.29, headline 2) |

**HTTP does not clear the bar at any calibrated-looking threshold in the sweep.** There is no “both backends agree via independent methods” result to accept.

### Default selection path

`select_backend("auto")` prefers HTTP whenever the host answers. The only CLI test calls:

```python
MODULE.main(["--backend", "tfidf", "--output", str(output)])
```

So **CI green (once the timeout assert is fixed) does not imply production green**. That is the silent-success failure family this repo catalogues.

Artifact already written under the author worktree:

```json
{"_meta": {"backend": "http", "entry_count": 458, "linkage": "average", "threshold": 0.17}}
# followed by a single cluster with all 458 members
```

Downstream C2/C3 consuming that file get: one “family” for the entire fleet, total precision collapse, and a duplicate-cause guard that either blocks everything novel or is turned off.

---

## Attack the tests (mutation / suite-blindness)

### Mutations the suite **does** catch (TF-IDF contract)

| Mutation | Effect | Contract |
|----------|--------|----------|
| Constant identical embeddings | 1 cluster of 458 | FAIL precision |
| Threshold 1.0 / never-merge break | 458 singletons | FAIL recall/headline |
| Remove `_cause_shape_markers` | completion recall ~0.29, headline 2 | FAIL |
| Instance text once, no check/hint | recall collapse | FAIL |
| Threshold 0.01 / 0.05 over-merge | max 440–458 | FAIL precision |
| Single-link instead of average | max ~387 | FAIL |

So the TF-IDF ground-truth gate is not a pure count assertion — **when it runs**, over-merge and under-merge on the fixture families are visible.

### Mutations / defects the suite **does not** catch

1. **HTTP quality total failure (default path)**  
   Exact situation: leave `cluster_entries` / TF-IDF tests untouched; run `main()` with default `auto`.  
   Observed: 1×458 cluster, every `must_not_merge` pair shares a cluster.  
   Suite still only forces TF-IDF. **Survives.**

2. **Broken `HttpEmbeddingBackend.embed` returning constant vectors**  
   Same 1×458 collapse. No test calls HTTP embed on the corpus or asserts cluster cardinality bounds. **Survives.**

3. **ID leakage into `similarity_text`**  
   Mutation: prepend `entry.id` to the composed text.  
   Ground-truth contract still **PASS** (IDs are short noise vs long instance text + markers).  
   The only anti-leak test (`test_shared_id_prefix_does_not_merge_unrelated_records`) uses two hand-built entries with unrelated prose — it does **not** prove production embeddings ignore IDs under adversarial identity coupling. Weak, not suite-killing alone.

4. **No degeneracy invariant for plausible bad thresholds**  
   Out-of-range only: `0`, `-0.1`, `1.5` → exit 1, **no** output file. Good for absurd inputs.  
   **Plausible** `threshold=0.05` (same order of magnitude as the tuned 0.17): exit **0**, writes JSONL with **max cluster 440 / 458**.  
   No test requires `max(size) < entry_count`, or exit 1 when a single cluster swallows the corpus. Author note on `536071d` correctly says this invariant is missing — and it is still missing.

5. **Assertions that check sets of cluster IDs across families, not membership purity**  
   Precision is only the five listed pairs in the fixture. Unlisted pairs (e.g. `completion-signal` × `dedup-identity-key`) are unchecked. Under current TF-IDF they happen not to overlap; the suite would not notice if they did.

6. **Headline / recall can be satisfied by marker injection rather than embedding geometry**  
   See next section. A “clusterer” that only ran the regex markers into a few buckets would be much closer to green than a pure vectorizer — the suite cannot tell the difference.

### Suite structure defects (not nits)

- **Backend-agnostic claim is untested.** Fixture text requires both backends; only TF-IDF is gated.
- **No empty/missing CLI tests** in the suite (implementation happens to fail loud — see below — but that is not locked).
- **No adversarial novel-input tests** (FP into a family, paraphrase FN out of a family).
- **HTTP test couples to probe timeout semantics** and is currently red after a disclosed fix — proof the HTTP surface is fragile and under-specified in tests.

---

## Ground-truth recovery vs “would the test still pass if it did not?”

On TF-IDF @ 0.17 the families are recovered at the ≥0.75 bar, with two known in-corpus outliers:

- `fleet-MDL-18` (completion-signal) — **no marker hit**, separate cluster from the 6-member core.
- `fleet-OPS-48` (shared-mutable-checkout) — no marker system for that family; lexical residual.

**If recovery failed**, `_assert_fixture_contract` would fail — for the TF-IDF call site.  
**If recovery failed only on HTTP / auto**, the suite would still pass. That is the decisive suite-blind hole.

---

## Inversion 1 — False positive (novel lands inside an existing family)

Mechanism: `_cause_shape_markers` injects tokens such as `latentcompletiongap` / `latentbrokengate` **twelve times each** into the TF-IDF document when regexes fire. Those tokens dominate average-link merges.

### Concrete FP inputs (added to the real 458-entry corpus, TF-IDF @ 0.17)

| id | instance (abbrev.) | markers | Lands with |
|----|--------------------|---------|------------|
| `novel-INV-1` | “Inventory **report** listed the host in the **wrong state** after a **forced-early** SNMP poll timeout.” | `latentcompletiongap` | **completion-signal majority** (`fleet-OPS-11/16/21/23/28`, `fleet-orch-OPS-11`) |
| `novel-SES-1` | “Operator tried to **resume** a **headless** tmux session and attached to a different user's shell.” | `latentcompletiongap` | **same completion-signal cluster** |
| `novel-PKG-1` | “Packaging job **exited 0** and published an **artifact** that was an empty tarball…” | `latentcompletiongap` | **same completion-signal cluster** |
| `novel-TLS-1` | “Certificate probe **exited 0** while edge still served expired certificate **status** page.” | `latentbrokengate` | **entire fail-silent-gate family** (all 4 members) |
| `novel-GATE-1` | “Canary set **ran_ok** true after only compiling…” | `latentbrokengate` | **entire fail-silent-gate family** |
| `novel-DEP-1` | “**dependency** returned **404**; verifier treated that as **reject**…” | `latentbrokengate` | **entire fail-silent-gate family** |

Control without markers (`novel-CTRL-1`, DNS TTL) correctly stayed a singleton.

**Consequence for C3:** a genuinely novel failure whose prose happens to match these patterns is absorbed into a known recurrence cluster → guard treats it as duplicate → real new entries rejected → operators disable the guard.

Markers are not abstract “shape” features; they are **fixture-shaped surface regexes** (e.g. `resume`+`headless`, `report`+`forced.early|wrong.state`, bare `ran_ok`). That is homework-grading with extra steps.

---

## Inversion 2 — False negative (known duplicate shape falls outside every family cluster)

### Concrete FN inputs (same protocol)

| id | instance | markers | Result |
|----|----------|---------|--------|
| `fn-COMP-1` | “The agent claimed the task was finished, but the file it was supposed to create never appeared on disk.” | none | **singleton**, no overlap with completion-signal |
| `fn-COMP-2` | “Automation said success while the expected output directory stayed empty the whole time.” | none | **singleton** |
| `fn-COMP-3` | “Worker process announced done; the promised patch set was absent from the branch.” | none | **singleton** |
| `fn-COMP-4` | “Subagent printed complete in the log, yet the PR body it owed never got opened.” | none | **singleton** |
| `fn-GATE-1` | “Missing credentials made the checker crash; dashboard painted the cell green anyway.” | none | **singleton**, no fail-silent overlap |
| `fn-GATE-2` | “Network blip during the probe was swallowed; operators saw only a soft skip, not a red failure.” | none | **singleton** |

These are the **same root causes** as the fixture families, rephrased without the regex triggers. Pure TF-IDF without markers already fails completion-signal on the real corpus; the markers paper over that only for wording that matches the authored patterns.

**In-corpus FN (partial):** `fleet-MDL-18` is a labeled completion-signal member that does not take a marker and does **not** join the majority cluster — tolerated only because 6/7 still clears 0.75.

**Consequence for C2/C3:** known duplicates reappear as “novel”; the registry remains a diary for any incident that does not use the magic phrases.

---

## Degeneracy / empty / truncated paths

| Input | exit | output written? | Notes |
|-------|------|-----------------|-------|
| `--threshold 0` / `-0.1` / `1.5` | 1 | no | range check only |
| `--threshold 0.05` (plausible) | **0** | **yes**, max size **440** | **no degeneracy guard** |
| `--threshold 0.99` / `1.0` | 0 | yes, 458 singletons | useless but “successful” |
| empty input dir | 1 | no | loud |
| empty `.jsonl` | 1 | no | loud |
| blank JSONL line | 1 | no | loud |
| truncated JSON line | 1 | no | loud |

Empty/malformed L1: **implementation fails loud** (good). **Not locked by tests** except two unit cases for missing fields / missing `source_anchor` on `load_entries`.

Bad threshold: the brief/review packet asks that a bad threshold exit 1 and write nothing. Only the open interval bounds are enforced. A threshold that induces corpus-swallowing is a **successful write**. That is decorative guarding.

---

## What was tried that did **not** break TF-IDF@0.17

Recorded for balance — these are not green lights for merge:

- Constant / no-merge / over-merge / marker ablation / single-link mutations **do** fail the TF-IDF contract when applied to that path.
- Empty/truncated inputs fail loud on the CLI.
- HTTP is not silently replaced by TF-IDF mid-flight when selected; failures raise. The bug is **successful wrong clustering**, not a hidden fallback.
- Backend selection logs to stderr and `_meta` when the CLI is used with forced TF-IDF (tested).
- Average-link vs single-link: single-link fails the contract here; average-link is doing real work **for TF-IDF**.
- Live embed host is reachable and returns finite vectors (re-derived).

None of that rescues the default HTTP path, the missing corpus-swallow invariant, the marker-shaped FP/FN surface, or the red suite.

---

## File/line anchors for blockers

| Sev | Finding | Anchor |
|-----|---------|--------|
| **critical** | Default HTTP @ 0.17 → one cluster of 458; GT precision total fail; L2 artifact already wrong | `pipeline/cluster.py` `DEFAULT_THRESHOLD=0.17` (L27); `select_backend` auto→HTTP (L384–398); observed `pipeline/L2/clusters.jsonl` |
| **critical** | Suite never runs ground-truth contract on HTTP / auto | `pipeline/tests/test_cluster.py` L62–66, L123–126 only force `tfidf` |
| **critical** | Marker injection creates FP into completion-signal and fail-silent-gate for novel text | `pipeline/cluster.py` `_cause_shape_markers` L177–214; `similarity_text` L172–173 (×12 weight) |
| **high** | Marker ablation kills completion-signal recovery — “clustering” is not backend-agnostic geometry | same; mutation: empty markers → recall ~0.29 |
| **high** | Paraphrase FNs never join known families | no test; concrete inputs above |
| **high** | Plausible low threshold exits 0 and writes near-total merge; no max-cluster invariant | `cluster_entries` L450–451 only checks `(0,1]`; missing post-condition |
| **high** | Suite currently red: HTTP unit test vs 120s request timeout | `test_cluster.py:158` vs `cluster.py` L306–307, L343 |
| **medium** | ID non-leakage test is synthetic and does not fail if IDs are concatenated into production text | `test_cluster.py` L77–97; mutation prepend-id still PASS |
| **medium** | Precision pair list incomplete relative to C(5,2) families | fixture `must_not_merge` only 5 pairs |

---

## Required bar to reverse this verdict (not optional polish)

1. **Ground-truth contract must pass for the backend that `auto` actually selects**, or `auto` must refuse to select HTTP until a **backend-specific** threshold is calibrated and tested. Silent HTTP success at a TF-IDF threshold is a ship blocker.
2. **Invariant:** if `max(cluster.size) == entry_count` (or another calibrated degeneracy bound), exit nonzero and write **nothing**.
3. **Adversarial tests:** at least one FP (novel must not enter completion-signal / fail-silent via marker collisions) and one FN (paraphrase of completion-signal must join or the representation must be fixed without regex gaming).
4. Suite green again after timeout split — without weakening the HTTP test into a no-op.
5. Stop treating fixture-tuned `latent*` regexes as a substitute for a backend that generalizes; if markers remain, they need adversarial tests that try to break them.

Until then, C2/C3 must not consume `clusters.jsonl` from this engine’s default path.

---

## Verdict

The TF-IDF path can score the coordinator fixture; the suite can mostly police that path’s gross failure modes. That is necessary and nowhere near sufficient. The default networked path produces a single mega-cluster; the suite cannot see it; the representation cheats with fixture-shaped markers that both over-merge novel text and under-merge paraphrases; degeneracy for plausible thresholds is unguarded; the suite is red on the only HTTP test it has.

VERDICT: fail

```json cli-dispatch-verdict
{
  "schema": "cli-dispatch.verdict/v1",
  "verdict": "fail",
  "summary": "Default HTTP path collapses 458→1 cluster; suite only gates forced TF-IDF; marker-shaped FP/FN; suite red; no corpus-swallow invariant.",
  "findings": [
    {
      "severity": "critical",
      "title": "HTTP auto path at DEFAULT_THRESHOLD=0.17 merges entire corpus into one cluster",
      "file": "pipeline/cluster.py",
      "line": 27,
      "confidence": 1.0
    },
    {
      "severity": "critical",
      "title": "Ground-truth suite never exercises HTTP/auto clustering quality",
      "file": "pipeline/tests/test_cluster.py",
      "line": 62,
      "confidence": 1.0
    },
    {
      "severity": "critical",
      "title": "Cause-shape markers create false positives into completion-signal and fail-silent-gate",
      "file": "pipeline/cluster.py",
      "line": 177,
      "confidence": 0.95
    },
    {
      "severity": "high",
      "title": "Paraphrase false negatives: known completion/gate shapes remain singletons without marker keywords",
      "file": "pipeline/cluster.py",
      "line": 158,
      "confidence": 0.95
    },
    {
      "severity": "high",
      "title": "Plausible threshold 0.05 exits 0 and writes max cluster 440; no degeneracy invariant",
      "file": "pipeline/cluster.py",
      "line": 450,
      "confidence": 1.0
    },
    {
      "severity": "high",
      "title": "Suite red: HTTP unit test asserts timeout<=3.0 after request_timeout=120 fix",
      "file": "pipeline/tests/test_cluster.py",
      "line": 158,
      "confidence": 1.0
    },
    {
      "severity": "medium",
      "title": "ID anti-leak test does not fail if ids are concatenated into similarity_text",
      "file": "pipeline/tests/test_cluster.py",
      "line": 77,
      "confidence": 0.85
    }
  ]
}
```
