# Diagnosis: recall-baseline gate refusal (`released/shared-mutable-checkout` 0.8571 → 0.7143)

Lane: `dispatch/diag-recall-drop-grok`  
Checkout: `/home/psimmons/projects/hindsight/.dispatch/worktrees/diag-recall-drop-grok`  
HEAD: `11757a7f6e1384746b1b9622e1e89a59c3c8de9f`  
Scope: read-only. No catalog writes, no `--allow-drop`, no commits, no posts.

The 0.8571 → 0.7143 figure is **6/7 → 5/7** on the seven-member `shared-mutable-checkout` ground-truth family. It is a **corpus-growth fragmentation of one fixture member (`fleet-OPS-8`)**, not a `must_not_merge` regression and not a lookup miss. On this checkout the drop is **already recorded** in `pipeline/L2/recall-baselines.json`; verify against the committed partition **passes**.

---

## F1 — How `add-failure-mode.sh` runs the gate

Canonical writes set `RUN_FULL_LOOP=1` and, after growing L1, recapturing the HTTP snapshot, and rewriting `pipeline/L2/clusters.jsonl`, invoke exactly:

```810:810:bin/add-failure-mode.sh
    python3 "$REPO_ROOT/pipeline/recall_baselines.py" --update --backend released
```

Comments at `bin/add-failure-mode.sh` 798–809 state the intent: a canonical add grows the corpus; corpus growth is what originally pushed `shared-mutable-checkout` under the old absolute 0.75 floor (hindsight#121); `--update` re-records the new per-(family, backend) recall **and refuses the whole write** if any family dropped. A refused `--update` is a non-zero exit; the `rollback_on_error` trap at lines 589–620 then undoes the catalog row. The add therefore cannot land a new failure mode if retrieval of an *old* fixture family got worse.

`--backend released` means the committed `clusters.jsonl` partition (HTTP snapshot, threshold 0.22), not live TF-IDF. Live backends are supposed to be the test suite's problem (same comment, and CI `guard.yml` lines 80–88).

Nothing was written to the canonical catalog in this lane. Reproduction used a scratch copy of the artifact.

---

## F2 — Exact numbers on this checkout

Committed artifact (`pipeline/L2/recall-baselines.json`):

| backend | family | together/members | fraction |
|---|---|---|---|
| released | shared-mutable-checkout | 5/7 | 0.7142857142857143 |
| tfidf | shared-mutable-checkout | 5/7 | 0.7142857142857143 |
| http | shared-mutable-checkout | 5/7 | 0.7142857142857143 |

Provenance: `corpus_size=816`, `l1_sha256=95c26934e47238c78724c7250a36f34e5b853076908d5318951c565bcbf92361`.  
`overrides[]` contains only the 2026-08-20 `http/dedup-identity-key` 1.0→2/3 drop. There is **no** override log entry for `shared-mutable-checkout`. `reconciled_floors.released` contains only `dedup-identity-key` at 2/3.

Commands (numpy-capable interpreter: `/home/linuxbrew/.linuxbrew/bin/python3`; default `python3` 3.14 has no numpy, so `replay_l2.py` cannot import `cluster.py` on that interpreter):

```text
$ python3 pipeline/recall_baselines.py --backend released
recall-baselines: PASS: 5 (family,backend) rows at or above baseline across ['released']
EXIT=0

$ /home/linuxbrew/.linuxbrew/bin/python3 pipeline/replay_l2.py
replay-l2: PASS: 816 entries, 295 clusters

$ /home/linuxbrew/.linuxbrew/bin/python3 pipeline/recall_baselines.py --backend released
recall-baselines: PASS: 5 (family,backend) rows at or above baseline across ['released']

$ /home/linuxbrew/.linuxbrew/bin/python3 pipeline/recall_baselines.py --backend tfidf
recall-baselines: PASS: 5 (family,backend) rows at or above baseline across ['tfidf']
```

So **this tree does not currently refuse** `0.8571 -> 0.7143`. The recorded floor is already 5/7. A routine `--update --backend released` would rewrite provenance and exit 0.

---

## F3 — Reproducing the cited refusal (scratch artifact only)

The symptom string is produced when the recorded floor is still **6/7 = 0.857142…** and measured recall is **5/7**. Planting that historical floor on a `/tmp` copy, then running the same `--update --backend released` add-failure-mode uses:

```text
LIVE recorded released/shared-mutable-checkout: {'fraction': 0.7142857142857143, 'members': 7, 'together': 5}
PLANTED fraction: 0.8571428571428571

$ python3 pipeline/recall_baselines.py --artifact /tmp/hindsight-recall-diag.Gi4r6s/recall-baselines.json --backend released --update
recall-baselines: REFUSED: measured recall dropped below a recorded baseline.

  released/shared-mutable-checkout: 0.8571 -> 0.7143  (target 0.75)

Nothing was written. A drop is a real capability regression until proven
otherwise -- investigate first (hindsight#121 tracks the known one).
To accept it deliberately, re-run with:
  --update --allow-drop --reason "why this drop is acceptable"
The reason is recorded in the artifact's overrides log and in git history.
EXIT=1
```

Live `pipeline/L2/recall-baselines.json` was unchanged after that run (`together=5`).

Arithmetic: `6/7 = 0.857142…` formats as `0.8571`; `5/7 = 0.714285…` formats as `0.7143`. Target `0.75` is aspirational (`TARGET_FRACTION` in `pipeline/recall_baselines.py` line 62; fixture `min_fraction_together`). The **gate** is the recorded baseline, not 0.75 — that is the 2026-08-19 #121 ruling in the module docstring.

---

## F4 — Which of the 7 fixture members moved

Ground-truth family (`pipeline/tests/fixtures/recurrence_ground_truth.json`):

`fleet-OPS-8`, `fleet-OPS-13`, `fleet-OPS-36`, `fleet-OPS-38`, `fleet-OPS-41`, `fleet-OPS-45`, `fleet-OPS-48`.

Released / HTTP snapshot partition (`pipeline/L2/clusters.jsonl`, meta `backend=http, entry_count=816, threshold=0.22, linkage=average`; in-memory recluster from the snapshot: **0 assignment mismatches vs committed**):

| member | cluster | size | role |
|---|---|---|---|
| fleet-OPS-13 | **c-056** | 31 | majority (5) |
| fleet-OPS-36 | **c-056** | 31 | majority |
| fleet-OPS-38 | **c-056** | 31 | majority |
| fleet-OPS-41 | **c-056** | 31 | majority |
| fleet-OPS-45 | **c-056** | 31 | majority |
| **fleet-OPS-8** | **c-113** | 3 | **the 6/7 → 5/7 move** |
| fleet-OPS-48 | c-107 | 1 | historical 6/7 outlier (already out) |

C1-era measurement (`reviews/C1-clustering-review.md`): `shared-mutable-checkout` 6/7, outlier `fleet-OPS-48` alone. The **new** departure is `fleet-OPS-8`. `fleet-OPS-48` was already the tolerated miss that kept 6/7 above 0.75; losing OPS-8 is what crosses 0.75 (5/7 = 0.7143).

Live TF-IDF (`TfidfEmbeddingBackend`, threshold 0.17, `MAX_CLUSTER_MEMBERS=40`): **same 5/7 split** — OPS-13/36/38/41/45 together, OPS-8 alone-of-family in a 2-member cluster, OPS-48 in a 4-member cluster. Recorded tfidf baseline is already 5/7, so `recall_baselines.py --backend tfidf` PASSes.

---

## F5 — What OPS-8 clusters with, and whether that neighbour is a near-duplicate

**Released cluster c-113 (size 3):** `fleet-OPS-8`, `fleet-OPS-7`, `hc-FM-162`.

- `fleet-OPS-8` (fixture SMC): concurrent live session in a shared checkout; “52 uncommitted files … 18 more reformatted mid-session in a shared checkout”.
- `fleet-OPS-7` (**not** in the fixture family): `cli-dispatch land` destroyed `.dispatch/agent.log` “right before an anomaly (**18 unattributed reformatted files in a shared checkout**) surfaced 2 hours later.” Same incident, different cause (forensic-log destruction vs concurrent writers).
- `hc-FM-162`: coordinator committed catalog rows in the shared checkout mid-dispatch. That **is** SMC-shaped; it is a later cataloguing, not one of the original 7.

`bin/similar-causes.py` on OPS-8's own instance (token overlap, not clustering):

```text
1.000 | fleet-OPS-8     (self)
0.152 | fleet-OPS-7     (same-incident sibling, not SMC family)
0.143 | fleet-OPS-38    (SMC family)
0.116 | fleet-OPS-45    (SMC family)
0.113 | fleet-OPS-13    (SMC family)
```

OPS-8 **does retrieve itself** (1.000) and still retrieves three of the other six family members in the top 10. It does **not** fail the “own query” lookup. What changed is the **cluster assignment**: average-link glued OPS-8 to the same-incident OPS-7 narrative, producing a 3-member cluster instead of joining the 31-member c-056 sink.

HTTP snapshot nearest neighbours for OPS-8 (raw cosine on committed vectors; clustering uses the 0.10 dense / 0.90 lexical blend, so these ranks are relative, not the agglomeration scores):

```text
0.6772  hc-FM-263          (in c-056 majority; coordinator commit to shared checkout while a lane is live — cites fleet-OPS-41)
0.6735  hc-FM-171          (worktree-remove of untracked evidence; not SMC)
0.6637  fleet-OPS-47       (stale checkout mistaken for current; not SMC)
0.6537  fleet-OPS-41       [SMC-FAMILY, in c-056]
0.6451  fleet-OPS-13       [SMC-FAMILY, in c-056]
```

OPS-8's **nearest** embedding neighbour is a legitimate later SMC-class catalog row that **already sits in the majority cluster**. Pairwise HTTP cosine OPS-8 × OPS-7 is only 0.5853 — *lower* than OPS-8 × the majority members. The split is agglomeration order (early merge with distinctive shared incident phrasing “18 … reformatted files in a shared checkout”), not “OPS-8 is a different cause.”

Mean raw HTTP cosine of the c-113 trio onto all 31 c-056 members: OPS-8 0.5952, hc-FM-162 0.5967, OPS-7 0.5465. OPS-7 is the drag. That is corpus growth: dozens of later `hc-FM-*` shared-checkout recurrences inflated c-056 to 31 (cap is 40), and OPS-8's same-incident non-family sibling pulled it into a side cluster.

---

## F6 — Precision (`must_not_merge`) is currently clean; FM-371 is latent, not this drop

Fixture pairs, checked on **released HTTP** and **live TF-IDF** at n=816:

| pair | released | live TF-IDF |
|---|---|---|
| completion-signal × shared-mutable-checkout | NONE | NONE |
| completion-signal × fail-silent-gate | NONE | NONE |
| shared-mutable-checkout × dedup-identity-key | NONE | NONE |
| fail-silent-gate × convergence-not-corroboration | NONE | NONE |
| dedup-identity-key × convergence-not-corroboration | NONE | NONE |

The paused-stash note (“PR128 round-2 regen artifacts exposed a real TF-IDF must_not_merge precision regression”) is **not true of this checkout**. `INVESTIGATION-FINDINGS-132.md` documents that regression at n=696 as an average-link sink (103 members, margin +0.002117 over 0.17) and the fix that landed (`MAX_CLUSTER_MEMBERS=40`). Live TF-IDF here: 265 clusters, largest=40, no forbidden pair overlap.

FM-371 (queried via `bin/query-failure-modes.sh FM-371`, not by reading `docs/HIGH.md` whole) remains a real **latent** embedding-quality issue: HTTP raw cosine `fleet-OPS-38 × fleet-MDL-18` (completion-signal outlier) = **0.7182**, and `fleet-OPS-36 × fleet-MDL-18` = 0.6734. They do **not** share a cluster at threshold 0.22 + cap 40. Lowering the HTTP threshold to pull OPS-8 back into c-056 is how you would *create* the FM-371 merge, not how you would fix this recall drop.

---

## F7 — `similar-causes` over the 7: who fails to retrieve family, vs who fails to cluster

Query = each member's own `instance` text. SMC IDs appearing in the top-10 rendered rows:

| query | self? | other SMC in top 10 | note |
|---|---|---|---|
| fleet-OPS-8 | yes 1.000 | OPS-38, OPS-45, OPS-13 | next hit is OPS-7 (same incident) |
| fleet-OPS-13 | yes | OPS-36, OPS-38, OPS-45, OPS-41 | majority member |
| fleet-OPS-36 | yes | OPS-45, OPS-13, OPS-38 | majority member |
| fleet-OPS-38 | yes | OPS-41, OPS-45, OPS-13 | majority member |
| fleet-OPS-41 | yes | OPS-38 | majority member |
| fleet-OPS-45 | yes | OPS-36, OPS-38, OPS-13 | majority member |
| fleet-OPS-48 | yes 1.000 | **none** | historical hard singleton |

Family-claim query (“Two or more concurrent agents or dispatches operate in one working tree…”): top hit `hc-FM-128` (0.290, later catalog SMC), then `fleet-ORC-13`, then `fleet-OPS-8` (0.127), `fleet-OPS-45`, `fleet-OPS-41`. Lookup of the *class* still finds the class. The gate that is red (when the pin is 6/7) is **clustering recall**, not `similar-causes`.

---

## F8 — +1 corpus-growth probe (TF-IDF, scratch entries only)

Appending one unrelated L1-shaped record, and separately one SMC-shaped record, then re-clustering with the real TF-IDF backend:

```text
TF-IDF after +1 unrelated:   SMC 5/7=0.7143  (still OPS-8 and OPS-48 out)
TF-IDF after +1 SMC-shaped:  SMC 5/7=0.7143
must_not_merge after +1 SMC-shaped: all five pairs NONE
```

A single additional catalog row does not, on TF-IDF, drop this family to 4/7. The HTTP add path recaptures embeddings and could still move the average-link cut; that is why the ratchet exists. It is not evidence that *this* 6/7→5/7 drop is a new retrieval bug.

---

## Q1 — Reproduce

See F2–F3. The add path is `recall_baselines.py --update --backend released` (`bin/add-failure-mode.sh:810`). Against the committed artifact that command would **pass** on this tree (recorded = measured = 5/7). Against a planted 6/7 floor it prints exactly:

`released/shared-mutable-checkout: 0.8571 -> 0.7143  (target 0.75)` exit 1, nothing written.

---

## Q2 — Corpus artifact vs real defect

**Corpus artifact.** One of seven fixture members (`fleet-OPS-8`) left the majority cluster because the corpus grew a large shared-checkout recurrence sink (c-056, 31 members, many `hc-FM-*` recurrences of the same cause) and because OPS-8 shares distinctive incident wording with non-family `fleet-OPS-7`. It still retrieves itself and still retrieves family members via `similar-causes`. No `must_not_merge` pair merges on released or live TF-IDF. `fleet-OPS-48` is the pre-existing 6/7 outlier, not the new move.

Ruled out as *this* drop:

- Precision regression (stash / PR128 / FM-371 firing now): F6, overlap=NONE.
- “SMC FM no longer retrieves for its own query”: F7, all seven retrieve self at 1.000.
- Stale fixture membership: OPS-8's instance is still the family's claim (concurrent writers in one checkout). OPS-7 is the one that does **not** belong in the family; the clusterer attached OPS-8 to it anyway.

---

## Q3 — Which fix is right

**Recommendation: (a) re-scope the floor**, and only on a tree whose recorded pin is still 6/7.

Do **not** (b) “fix retrieval” as a small change. The HTTP threshold is already the first 0.005 step that restored precision (`pipeline/cluster.py` header). Raw cosine `fleet-OPS-38 × fleet-MDL-18 = 0.7182` is a loaded gun; lowering 0.22 to re-absorb OPS-8 is how FM-371 becomes a live merge. The 40-member cap already stopped the TF-IDF sink (#132). A representation/marker change is a research project, not a one-line fix, and it is not what this drop is.

Do **not** (c) edit the fixture. The seven members are still the right ground-truth incidents. Dropping OPS-8 (or OPS-48) to make 5/5 = 1.0 would be the validator grading its own homework — the failure this fixture exists to forbid (`recurrence_ground_truth.json` purpose block).

If a checkout still records 6/7 and `--update --backend released` is refusing, the justified command is:

```bash
python3 pipeline/recall_baselines.py --update --backend released \
  --allow-drop --reason "Corpus growth at n=816 fragmented shared-mutable-checkout 6/7 -> 5/7: fleet-OPS-8 left the majority cluster (c-056, 5 members) to join same-incident fleet-OPS-7 (forensic-log destruction, not an SMC fixture member) plus hc-FM-162. Not a must_not_merge regression: completion-signal x shared-mutable-checkout remain disjoint on released HTTP and live TF-IDF. fleet-OPS-48 remains the historical singleton outlier from the 6/7 era. Do not lower the HTTP threshold: fleet-OPS-38 x fleet-MDL-18 raw cosine 0.718 is the FM-371 precision landmine. Not #118; same corpus-growth class as #121/#178."
```

`--reconcile` is **not** required: `shared-mutable-checkout` is not in `reconciled_floors` (only `released/dedup-identity-key` is). `--allow-drop` alone updates the raw baseline and appends `overrides[]`.

On **this** checkout that command is a no-op: there is no drop to accept (F2). Do not run it here just to leave a reason string; the pin is already 5/7.

Optional follow-on, not required to unblock a 6/7 pin: add a `reconciled_floors.released.shared-mutable-checkout` entry at 5/7 in the same style as dedup-identity-key, so a future `--update` cannot silently treat 5/7 as a forgotten raw number. That is documentation of a reviewed exception, not a retrieval fix.

---

## Q4 — Should `add-failure-mode.sh` gate writes on this metric?

The write path at `bin/add-failure-mode.sh` 798–810 re-measures recall of a **frozen 7-member 2026-07 fixture** after every canonical add, and a drop rolls back the new row (trap 589–620). That is the right *shape* of a ratchet for a release artifact: corpus growth must not silently launder a worse partition into `clusters.jsonl`. It is the wrong *control point* for the catalog's purpose.

The catalog exists to record new failure modes. This gate refuses that recording because clustering of *old* labeled incidents moved. hindsight#178 was exactly this: “a throwaway, single-row canonical add with content wholly unrelated to the fixture family” blocked repo-wide (`bin/tests/test_add_failure_mode_release.py` 386–407). The script already special-cases the known `dedup-identity-key` 2/3 floor (lines 806–809: “A normal catalog add must never need an environment override for that known state”). `shared-mutable-checkout` 5/7 is the same class and is **not** in `reconciled_floors`, so the next 5/7→4/7 fragment will again freeze every canonical write until a human runs `--allow-drop` — including writes that have nothing to do with shared checkouts.

Measure it, fail CI's `recall_baselines.py --backend released` step (`guard.yml` 80–88), and keep `--update` on the add path as “record if ≥ pin, else refuse” only after the known corpus-growth floors are reconciled. Blocking *intake* of new FMs because retrieval of old ones drifted is how the registry goes mute about the very growth the metric is reacting to.

---

## Recommendation

Treat 6/7 → 5/7 as a **reviewed corpus-growth fragment of `fleet-OPS-8`**, same class as #121/#178, not as a clustering bug to patch under D1. If a tree still pins 6/7, accept 5/7 with the `--allow-drop --reason` text in Q3. Do not touch the fixture. Do not lower the HTTP threshold (FM-371 landmine). On this origin/main checkout the pin is already 5/7 and the gate is green; no override is needed here.

If the next add ever prints `0.7143 -> 0.5714` (4/7), that is a *new* drop and needs a fresh investigation — this report does not pre-authorize that.

```
ADVISORY: ADV.1
Decision: Keep the add-path ratchet, but treat shared-mutable-checkout 5/7 as a reviewed corpus-growth floor (like dedup-identity-key 2/3) rather than a retrieval bug to “fix” with threshold or fixture edits.
Options: A: --allow-drop / reconciled_floors pin at 5/7, leave clustering alone | B: lower HTTP threshold or change representation to force 6/7 | C: drop OPS-8/OPS-48 from the fixture
Lean: A — B is how FM-371 becomes a live must_not_merge; C falsifies the ground-truth contract. Uncertainty: HTTP add-path reclustering after a *new* catalog row was not executed (would write L1/snapshot); TF-IDF +1 held at 5/7 with clean precision.
Context: bin/add-failure-mode.sh:798-810; pipeline/L2/recall-baselines.json released/shared-mutable-checkout 5/7 at n=816; fleet-OPS-8 in c-113 with fleet-OPS-7 + hc-FM-162; OPS-38×MDL-18 cosine 0.7182.
```

---

```json cli-dispatch-verdict
{"schema":"cli-dispatch.verdict/v1","verdict":"pass","pr":0,"head":"11757a7f6e1384746b1b9622e1e89a59c3c8de9f","summary":"6/7→5/7 is corpus-growth fragmentation of fleet-OPS-8 (joined same-incident OPS-7), not a must_not_merge defect; re-scope the floor if a tree still pins 6/7 — this checkout already records 5/7 and verify passes.","findings":[{"severity":"medium","title":"add-failure-mode.sh gates catalog intake on old-fixture recall; next 5/7→4/7 will freeze every canonical write (same class as #178)","file":"bin/add-failure-mode.sh","line":810,"confidence":0.85},{"severity":"low","title":"FM-371 remains latent: HTTP raw cosine fleet-OPS-38 × fleet-MDL-18 = 0.7182; do not lower threshold 0.22 to recover OPS-8","file":"pipeline/cluster.py","line":18,"confidence":0.9}]}
```
