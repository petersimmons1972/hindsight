# FINDINGS — measured results that must outlive their phases

These were paid for in defects. They are kept here, out of the plans, because a plan gets superseded
and a measurement does not. **Every number here is a measurement, not an estimate.** Where something
is a hypothesis, it says so.

## The six-layer manufactured-green ladder

The campaign's most transferable artifact. One defect — *CI reports green while verifying nothing* —
relocated through six layers, each repair revealing the next:

```
data (edit the L1 records the check reads)
  -> config (shrink conf/source-roots.conf so less is in scope)
    -> control flow (return 0 at the SKIPPED branch, before the floors)
      -> environment (the ratchet is a no-op under CI's shallow checkout)
        -> scope (the CI exemption flag is hardcoded, so the exempt path is taken forever)
          -> EXIT CODE (the verdict is honest and the return value is 0 anyway)
```

**The sixth rung was found 2026-08-02 by a cross-vendor lane and reproduced by the coordinator.**
`pipeline/reconcile_l1.py` prints `PARTIAL: … (1/5 sources resolved)`, names the four sources it did
not check, explains that it certifies only the resolved ones — and **returns 0**. On a CI runner the
four sibling sources do not exist, so this is what the "Reconcile L1 corpus" step does on every run.

It is the most dangerous rung so far for one reason: **it needs zero file changes**, because it is
the state of `main`. And unlike the enforcement step's explicit `SKIPPED`, it presents as an ordinary
successful step.

**The generalisable lesson: an honest message and an honest exit code are different properties.**
Ledger row V12 ("a gate must not certify what it never compared") *passes* on this tool, because its
reporting is scrupulous. Row V5 ("coverage holds") *fails* on the same command, because the exit code
does not carry the verdict. **A gate is its exit code; everything else is documentation.**

**And the bypass got *shorter* each round:** 3 config files → 1 file → 0 for an honest tree. That
metric is the signal. **When the bypass shortens, the design is wrong — stop patching.** This is why
`plans/05` relocates the check rather than attempting a seventh round.

## Mechanizability of the harness rule corpus

Pre-registered before measuring (`~/projects/ops-plans/three-laws.md`): *"At 60% this is
transformative; at 15% it is a rounding error and the leverage is elsewhere."*

Measured over 145 normative rules, 9 isolated agents, counts recomputed from JSONL rather than agent
self-reports: **mechanism 8.3% · partial 31.7% · judgment 59.3%.** Below the rounding-error line.

Two findings resize any plan built on it: **4 of the 12 mechanisms already exist** — the entire live
enforcement surface is one PreToolUse hook plus one settings value — so buildable-new is **5.5%**;
and all 8 high-confidence rows are `mechanism`, not one `partial` is high confidence, so 40% is an
eroding ceiling.

**Conclusion, stated against interest: Law 1 cannot fix context rot.** It removes ~8% of a corpus
that is 0.025% of spend. Simplifying context and mechanizing rules are *independent* programs.
Rejected hypothesis on record: **mechanizability does not track blast radius** (5.6% destructive vs
9.2% elsewhere).

*"The leverage is Laws 2 and 3" is a hypothesis with no pre-registered metric of its own. It is not
a finding, and it should not be cited as one.*

## The duplicate-cause guard cannot be built

Three approaches, all **refuted by measurement**, not abandoned:

| approach | pooled recall@5 | distractor separation |
|---|---|---|
| clustering engine | 1 of 77 blind paraphrases reached any real entry | — |
| similarity ranking (Arm C) | 0.523 | FP 0.75, AUC 0.53–0.57 |
| structured extraction (Arm B) | **0.262** | AUC 0.543 / 0.350 — chance and below chance |

**The binding constraint is a missing signal, not a threshold: the maximum distractor score exceeds
the maximum true-positive score**, so no cutoff separates them at any operating point. **Do not
sweep further** — that is fitting the evaluation set.

Retrieval *ranking* is nonetheless a real gain: pooled recall@10 = 0.662 versus the partitioner's
1-of-77. The signal is there; what is absent is the ability to *decide*. Hence a lookup, not a gate.

**Direction of error, and why it is survivable:** every miss observed is a family member landing in
its *own* cluster, never in a foreign one. No false merges were found and all C(5,2) family pairs
stay disjoint. The engine **under-reports recurrence and never fabricates it** — for a registry whose
purpose is "this has happened before", that is the survivable direction. It costs recall, not
trustworthiness, and the report must print the limitation on itself.

## The import confound that disqualified verify-discriminating

The tool copied each new test into a merge-base worktree and counted any nonzero exit as
discriminating. Measured both directions:

- test red only because it imports a module the branch adds → `exit=0, discriminating: 1/1`
- the identical assertion without that import → `exit=1, discriminating: 0/1`

**It is not a discrimination check. It is a "does this test reference something new" check — which
every TDD diff satisfies by construction.** No classification fixes it: copying a file to an older
tree conflates "the behaviour is absent" with "the module is absent". Replacement design in
`plans/07`: revert the implementation hunks and run at HEAD.

## QA baseline, and the hypothesis under test

Measured over 44 actor-runs harvested from workflow journals:

| metric | value |
|---|---|
| first-pass acceptance (`CONFIRMED_GOOD` on first verify) | **2 / 15 = 13%** |
| HIGH findings raised by verifiers | 66 |
| rounds: C4 = 6 (never accepted) · G1 = 5 · G2 = 3 (halted) | |
| vendor on both sides of QA | **100% same-vendor** |
| verify-role actors emitting **no verdict line at all** | **16 / 31** |

Those 16 were **unlandable by construction** — the landing gate matches on that literal string. An
actor that returned no verdict has not failed a verification; it failed to *report* one, and the two
must never share a denominator.

**Five-model panel, identical brief, identical artifact, blind:** opus 4 findings / 3 known classes ·
grok 4 / 2 · codex 2 / 1 · sonnet 2 / **0** · haiku 1 / 1 weak. **Cheap tiers do not degrade
gracefully at adversarial review — never tier down adversarial verification.** Cross-vendor bought a
real live defect three opus lenses had missed. **Decomposition beat model choice:** the same model
scored 6/6 as three lenses versus 3/6 as one generalist.

**Pre-registered hypothesis, still under test at N=1:** *cross-vendor, adversary-first QA raises
first-pass acceptance above 13% and reduces rounds-to-acceptance, **without lowering the number of
real defects found**.* Both halves matter — a shape that raises acceptance by finding *fewer* defects
is a weaker adversary and counts as a negative. Needs ≥5 packets. **Do not read the rule early.**

## Mutation survival — why a green suite proves little

Three rounds, each re-swept with *fresh* mutants rather than re-running the killed ones:
round 1 **56 of 91 survived (62%)** · round 2 **39 survived (43%)**. Improving, not resistant.

Every real defect this campaign found came from **mutation testing, not code reading**. Both
DEFECTIVE verdicts in the first build round came from mutants that left their suites fully green.

## Capturing a long-running command through a buffering pipe destroys its output on timeout

**Committed 2026-08-02 by the coordinator, while auditing this repo.** A cross-vendor review was
launched as:

```bash
timeout 1500 codex exec "<brief>" 2>&1 | tail -200 > review.md
```

`tail -N` must buffer its entire input to know which lines are last. When `timeout` killed the
pipeline, `tail` died without flushing and wrote a **zero-byte file**. This happened twice, at
25 and 55 minutes. Both times the conclusion drawn was *"the reviewer produced nothing"* — and both
times that conclusion was **false**: the reviewer had been producing output continuously, and the
harness threw it away.

**This is CI-17's family, and worth recording separately because the mechanism differs.** CI-17 is
*exit status* lost through a pipe. This is *output* lost through a pipe under abnormal termination —
a pipe that is harmless on a clean exit and total data loss on a kill. The lesson generalises past
`tail`: `head`, `sort`, `wc`, and any aggregating filter have the same property.

**Fix:** redirect straight to the file (`> out.md 2>&1`) and trim afterwards if needed, so partial
output survives. **And instruct long-running reviewers to emit findings incrementally** rather than
saving them for a final summary — a summary-at-the-end contract turns any timeout into total loss.

**Second-order lesson, the one that matters:** the failure was silent and self-confirming. A
zero-byte file reads exactly like "the tool had nothing to say", so the wrong conclusion was reported
to the founder with confidence. **Distinguish "produced nothing" from "output not captured"** — that
is the two-zeros rule (R4) applied to a harness rather than to a gate.

*Owed: this needs a catalog row via the two-step loop (`bin/add-failure-mode.sh` →
`extract_mechanical.py` → regenerate L2 → reconcile). Deliberately not added mid-restructure, since
adding a row without the extract step sends `reconcile_l1.py` SHORT.*

## The registry does not consult itself

Verified by inspection 2026-08-02: `.githooks/pre-commit` is 5 lines and execs only the catalog
guard · `bin/similar-causes.py` has no production caller · `bin/add-failure-mode.sh` references
neither similarity nor clusters · `bin/require-real-ci.sh` is called only by `bin/land.sh`, never by
`guard.yml`.

**A mechanism nothing calls has been built twice now** (`require-real-ci.sh`, then
`similar-causes.py` — the second merged four hours after the first was catalogued as a trap). Any
plan shipping a new mechanism must prove it is *called*, by removing the wiring and observing a
failure.
