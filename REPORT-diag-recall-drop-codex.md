# Recall-baseline gate diagnosis

Lane: `dispatch/diag-recall-drop-codex` at `11757a7f6e1384746b1b9622e1e89a59c3c8de9f` (`origin/main` at investigation time). Read-only diagnosis; no catalog, baseline, or pipeline artifact was changed.

## Findings

### F1 — the reported refusal is not reproducible at this revision

`bin/add-failure-mode.sh` invokes the gate as `python3 "$REPO_ROOT/pipeline/recall_baselines.py" --update --backend released` ([`bin/add-failure-mode.sh:798-810`](bin/add-failure-mode.sh#L798-L810)). I ran that exact argument set against a copy of the committed baseline artifact in `/tmp`, so it could not alter the worktree:

```console
$ /tmp/hindsight-diag-venv.AZ497a/bin/python3 pipeline/recall_baselines.py \
    --artifact /tmp/hindsight-recall-baseline.<random>.json --update --backend released
recall-baselines: RECORDED: 15 (family,backend) rows -> hindsight-recall-baseline.<random>.json
$ echo $?
0
```

The committed `pipeline/L2/recall-baselines.json` already records `shared-mutable-checkout` as **5/7 = 0.7142857142857143** for `released`, `tfidf`, and `http`; it does not contain the claimed current 6/7 (`0.8571428571428571`) floor. Therefore the exact refusal in the brief requires a stale/different baseline artifact or revision; it cannot be produced from this clean `origin/main` checkout.

The initial baseline artifact in commit `43a81220` likewise already says released 5/7 and TF-IDF 5/7. The explanatory source independently records the historical transition as corpus growth from 673 to 678 entries with no code change ([`pipeline/recall_baselines.py:4-29`](pipeline/recall_baselines.py#L4-L29); [`pipeline/tests/test_cluster.py:937-954`](pipeline/tests/test_cluster.py#L937-L954)).

### F2 — current retrieval is a corpus-sensitive recall limitation, not a current precision merge

I installed only `numpy` into a throwaway `/tmp` virtual environment because the checkout has no NumPy installed; this was required to exercise the actual TF-IDF implementation. The current live TF-IDF run over 816 L1 entries produced:

```console
completion-signal: 6/7 c-001: fleet-OPS-11,fleet-OPS-16,fleet-OPS-21,fleet-OPS-23,fleet-OPS-28,fleet-orch-OPS-11 | 1/7 c-033: fleet-MDL-18
shared-mutable-checkout: 1/7 c-106: fleet-OPS-8 | 5/7 c-051: fleet-OPS-13,fleet-OPS-36,fleet-OPS-38,fleet-OPS-41,fleet-OPS-45 | 1/7 c-061: fleet-OPS-48
```

So the strict fixture target is missed by **two**, not one, shared-checkout members today: `fleet-OPS-8` and `fleet-OPS-48`. They are not incorrectly merged with a `must_not_merge` family:

* `fleet-OPS-8` retrieves cluster `c-106 = (fleet-OPS-7, fleet-OPS-8)`. `fleet-OPS-7` is lost-agent evidence after a dispatch worktree was removed; it is a plausible operational neighbour but not a legitimate duplicate of the shared-mutable-checkout incident.
* `fleet-OPS-48` retrieves `c-061 = (fleet-CI-31, fleet-OPS-44, fleet-OPS-48, hc-FM-402)`. Those records concern test isolation fallback, a production trust-root write, and Terraform review scope. They are not legitimate near-duplicates of the A/B arms mutating one checkout in `fleet-OPS-48`.

The released partition agrees on the measured recall: the 7 members span `c-056` (5 members), `c-107` (`fleet-OPS-48`), and `c-113` (`fleet-OPS-8` with `fleet-OPS-7` and `hc-FM-162`), i.e. largest cluster **5/7 = 0.7142857142857143**.

I separately evaluated every precision pair in the fixture from `pipeline/L2/clusters.jsonl`:

```console
completion-signal/shared-mutable-checkout: PASS disjoint
completion-signal/fail-silent-gate: PASS disjoint
shared-mutable-checkout/dedup-identity-key: PASS disjoint
fail-silent-gate/convergence-not-corroboration: PASS disjoint
dedup-identity-key/convergence-not-corroboration: PASS disjoint
```

Thus FM-371's historical precision concern is not the mechanism of this result. Current evidence rules out a must-not-merge regression and does not show a fixture member retrieving a semantically valid but wrongly labelled neighbour. It supports the recorded corpus/TF-IDF sensitivity explanation.

### F3 — the right disposition is (a), but it has already happened here

Recommendation: **do not change retrieval or the fixture; retain the already-applied re-scoped ratchet.** The historical 0.8571 -> 0.7143 event was appropriately accepted as corpus-growth sensitivity, while precision remains absolute ([`pipeline/tests/test_cluster.py:946-983`](pipeline/tests/test_cluster.py#L946-L983)). A historical override, if the older 6/7 artifact must be released, should be the explicit operation:

```console
python3 pipeline/recall_baselines.py --update --allow-drop \
  --reason "Corpus growth changed TF-IDF IDF weights and fragmented shared-mutable-checkout from 6/7 to 5/7; all must_not_merge fixture pairs remain disjoint, and neither outlier's retrieved neighbour is a semantic duplicate."
```

For the present checkout, running that command would be wrong and unnecessary: there is no new drop to accept. A retrieval change is unsupported because it would be tuning around a historical corpus effect without evidence of a current semantic error; a fixture change is unsupported because both outliers still describe the asserted family and their current neighbours are not legitimate equivalents.

### F4 — using this gate inside `add-failure-mode.sh` is the wrong availability boundary

No: it is sensible to ratchet retrieval quality in the release/CI path, but not to make a new canonical failure-mode record unavailable when a *pre-existing* fixture recall value falls. The script writes/extracts the new canonical content and regenerates L2 first ([`bin/add-failure-mode.sh:746-795`](bin/add-failure-mode.sh#L746-L795)), then calls the recall gate, whose own comments explicitly say it refuses the write on any measured drop ([`bin/add-failure-mode.sh:798-810`](bin/add-failure-mode.sh#L798-L810)); the following replay check and rollback make the result all-or-nothing ([`bin/add-failure-mode.sh:812-825`](bin/add-failure-mode.sh#L812-L825)). That couples preservation of new failure knowledge to retrieval of old records. A recall regression must fail loudly and be investigated, but it should block promotion of the derived retrieval artifact, not block recording the incident that may explain or help fix the regression.

## Recommendation

Treat the reported refusal as stale state, not a current retrieval defect. Keep the existing 5/7 recorded baseline and strict precision fixture; locate the caller carrying the obsolete 6/7 baseline before changing anything. Decouple future canonical catalog filing from the L2 recall-ratchet release gate so a retrieval regression cannot prevent recording new failure modes.

VERDICT: pass

```json cli-dispatch-verdict
{"schema":"cli-dispatch.verdict/v1","verdict":"pass","pr":0,"head":"11757a7f6e1384746b1b9622e1e89a59c3c8de9f","summary":"Treat the refusal as stale baseline state; retain the recorded 5/7 corpus-artifact ratchet and decouple catalog filing from L2 recall release gating.","findings":[]}
```
