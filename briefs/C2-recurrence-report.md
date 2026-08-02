# C2 — Recurrence report

## Context

This renders the project's headline deliverable: a document that names, with evidence,
every lesson the fleet has paid for more than once. It is what turns "we keep repeating
ourselves" from an assertion into a citation.

It answers one sentence for a human reader:

> "This has happened before — N times, across M repos, between date X and date Y."

That sentence is the product. A report that cannot say it is not a recurrence report,
however green its suite.

## Files

- **Create** `pipeline/recurrence_report.py`.
- **Input** `pipeline/L2/clusters.jsonl` — the **pinned** partition. **Do not regenerate it.**
- **Output** stdout (`--format text|json`), and `pipeline/L2/recurrence-report.md` when
  `--output` is given.
- **`pipeline/tests/test_recurrence_report.py` already exists and is NOT yours to write.**
  *(This reverses the 2026-08-01 version of this brief. Plan rule R3 makes C2's gate a
  coordinator-authored ground-truth assertion, so it was authored before this
  implementation existed and derived by measuring the real corpus.)*

## Acceptance

```
python3 -m pytest pipeline/tests/test_recurrence_report.py -q
```

Currently **14 of 16 fail** because the module does not exist. All 16 must pass. Also run
the rest — you must not regress it:

```
python3 -m pytest pipeline/tests/ guard/tests/ -q
```

## Interface

```
python3 pipeline/recurrence_report.py [--clusters PATH] [--format text|json|markdown]
                                      [--output PATH] [--min-size N] [--top N]
```

Each group object carries at least: `cluster_id`, `size`, `members`, `source_repos`,
`first_seen`, `last_seen`, `label`, `span_days`.

**`size` must be derived from `len(members)`, never carried independently** — there is a
test asserting they agree, because a separately-carried count is a number that can drift
away from the evidence it claims to summarize.

**Ranking:** size descending, then date span descending, then `cluster_id` ascending as a
stable tiebreak. **Some clusters have `first_seen`/`last_seen` of `null`** (`c-043` is
one) — sorting must survive that rather than raising a `TypeError` comparing `None`, and
must not invent a date to fill the gap.

## Markdown report content

1. **Summary** — corpus size, cluster count, how many clusters have >1 member, and the
   single most-repeated root cause with its count.
2. **Recurrence table**, clusters with ≥2 members only, ranked as above: label, count,
   member IDs, source repos, first/last seen, span in days.
3. **Per-cluster detail** for the top 15: the label, each member's `instance` text, and
   its source path — so a reader can verify the grouping is real rather than trust it.
4. **Singletons appendix** — count only, plus the note that **a singleton is not proof of
   non-recurrence, only of non-detection.**
5. **Provenance footer** — backend, threshold, linkage, and the input file's entry count,
   read from the `_meta` line. A report that does not say how it was produced cannot be
   audited. *(Do not stamp a generation timestamp into the committed artifact — it makes
   every regeneration a spurious diff.)*

## Hard constraints — violating any of these fails the packet

1. **Never edit `pipeline/tests/test_recurrence_report.py`.** If you believe an assertion
   is genuinely unsatisfiable, **stop and say so in your final report with the measurement
   that proves it** — do not edit it, do not skip it, do not xfail it. Weakening a test to
   make code pass is the single failure this repository exists to catalogue.
2. **Never edit `pipeline/L1/**`, `pipeline/L2/clusters.jsonl`, or `catalog/**`.** The
   partition is pinned deliberately (FM-169): the same code on the same corpus produced a
   different cluster count on a cold-start run of the embedding service. Regenerating it
   would silently move the ground truth out from under the tests.
3. **No network. stdlib only.** Read the pinned file; never call the embedder.
4. **The default clusters path must derive from `__file__`,** never a hardcoded home
   directory. `pipeline/reconcile_l1.py` shipped with `/home/psimmons/...` baked in,
   resolved zero sources on CI, and printed `COMPLETE` anyway. There is a test for exactly
   this (`test_default_clusters_path_follows_the_module_not_a_hardcoded_home`).
5. **Nothing may fail open.** Empty file, `_meta`-only file, missing file, malformed line
   → **non-zero exit** naming what went wrong. **This corrects the 2026-08-01 brief**,
   which asked for "a valid report stating zero clusters" on empty input; plan rule R4 is
   the opposite, and the tests enforce R4. An empty report reads as "nothing has ever
   recurred", which is the exact inversion this repo exists to prevent.
6. **Never read an exit status through a pipe** (`cmd | head` reports *head's* status).
   Catalogued as CI-17; it has produced two false greens in this repo already.

## The honesty requirement — read this one twice

The text report **must state its own recall limitation**. This engine groups records that
share wording; it does **not** group records that share only an abstract cause shape.
Measured: **1 of 77** blind-authored paraphrases reaches any real corpus entry, and four
records that all describe "a gate that failed silently" land in four separate clusters.

So the report **under-reports recurrence**. That is the survivable direction of error —
it costs recall, not trustworthiness — but only if it is disclosed. A reader who does not
know this will read absence as evidence that nothing recurred. Say it on the report, in
plain language, not in a docstring.

## Out of scope

Clustering (C1); any judgment about what the clusters *mean* (that is W1/W2, done by
synthesis agents, not by this renderer).

## Your final report must include

- `VERDICT: pass` or `VERDICT: fail` as the **literal first line**.
- The pytest summary line for both commands above.
- Any assertion you believe is unsatisfiable, with the measurement.
- Anything you changed outside `pipeline/recurrence_report.py`, and why.
