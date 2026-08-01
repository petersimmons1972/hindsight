# Shared context — hindsight packets

*This file is prepended to every packet brief at dispatch time. Read it first.*

## What this repository is

`hindsight` is the cross-repo failure-mode registry for a ~15-repo fleet. Its job is
to stop the same failure being rediscovered over and over. It exists because the
previous approach — writing failures down in prose, in ~9 incompatible formats,
scattered across repos — demonstrably did not work: "trust the completion signal" was
independently re-logged at least 7 times in 3 weeks under 7 different IDs.

The registry is currently a diary. These packets make it a gate.

## Layout you will be working in

```
catalog/failure-modes.md   canonical catalog, 145 rows, single source of truth
guard/                     the catalog guard + its contract tests
guard/tests/               pytest + bats
pipeline/                  L0 manifest -> L1 extraction -> L2 clusters -> L3 invariants
pipeline/L1/*.jsonl        458 normalized entries across 14 sources (the corpus)
pipeline/tests/fixtures/   ground-truth fixtures authored by the coordinator
bin/                       add-failure-mode, sync tooling
conf/consumers.conf        the 12 repos that consume the floor
```

Read `README.md` and `CLAUDE.md` in the repo root before starting. `CLAUDE.md`
contains non-negotiables that apply to your work.

## The L1 entry schema

Every line of `pipeline/L1/*.jsonl` is one JSON object:

```json
{"id":"<sourceprefix>-<localid>","source_path":"...","source_anchor":"...",
 "instance":"what concretely went wrong","check":"the check that would catch it|null",
 "enforcement":{"file":"...","kind":"test|hook|ci|lint|schema"}|null,
 "auto":"machine|judgment","first_seen":"YYYY-MM-DD|null"}
```

Some records also carry `class_hint`. Treat unknown extra keys as tolerated, missing
required keys as an error.

## Hard constraints — these are not style preferences

1. **Never delete data to satisfy a validator.** Eleven real failure modes
   (`FM-REC-01..11`) were nearly lost that way already. If a record violates a rule,
   fix the rule or carry the record — the rule is younger than the data.
2. **An honest `null` beats an invented value.** Never fabricate a file path, a test
   name, or an enforcement mechanism to fill a field. A fabricated mechanism is worse
   than an admitted gap because it reads as covered.
3. **No silent truncation, ever.** If you cannot process something, fail loudly and
   name it. Do not skip, do not `continue` past it, do not cap silently. Two separate
   defects in this repo's own pipeline were silent-drops; both are now regression-tested.
4. **Never read an exit status through a pipe.** `cmd | head` reports *head's* status.
   Use `${PIPESTATUS[0]}` or avoid the pipe. This is catalogued as CI-17: the habit
   that saves context destroyed a measurement and produced a false green.
5. **Do not weaken an existing test to make your change pass.** If a test encodes a
   contract you are deliberately changing, update it to assert the NEW contract in both
   directions and say so in the PR body.
6. **Dependencies:** only `numpy` is available. Do NOT add `sentence-transformers`,
   `qdrant-client`, `scikit-learn`, `torch`, or any vector database. The corpus is 458
   entries; an in-memory similarity matrix is the correct tool at this scale. If you
   believe you need a new dependency, stop and say so in the PR rather than adding it.
7. **Python 3, standard library + numpy.** Match the existing code style in
   `guard/failure_mode_catalog_guard.py` and `pipeline/reconcile_l1.py`: type hints,
   `from __future__ import annotations`, dataclasses where they earn their place, and a
   module docstring that explains *why* the file exists, not what it does.

## Verification contract

Your work is accepted when the packet's `--check` command exits 0. That command runs
automatically after you finish and before anything is pushed. It is the contract — not
your description of what you did.

Write the tests to be genuinely capable of failing. A test suite that passes while the
feature is broken is the exact defect class this repository catalogues, and a
cross-vendor reviewer will be explicitly instructed to attack your tests on that basis.

## Out of scope for every packet

- Editing `catalog/failure-modes.md` content (rows are data, not yours to rewrite).
- Editing anything under `pipeline/L1/` (that is the extracted corpus).
- Editing `pipeline/tests/fixtures/` (coordinator-authored ground truth).
- Any network call except where a packet explicitly authorises one.
- Any write outside this repository.
