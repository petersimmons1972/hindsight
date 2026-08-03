# PLAN-03 — measure whether recurrence actually drops
Issue: petersimmons1972/hindsight#29 · Status: **WITHDRAWN 2026-08-03** — rejected on validity (Codex) and worth (Grok) by two orthogonal cross-vendor reviews; mechanize first, measure later · Blocked-by: none · Blocks: —

> **WITHDRAWN — not being built.** This instrument is dead. Two cross-vendor adversarial reviews,
> commissioned with orthogonal premises to reject, both returned REJECTED: Codex on validity (the
> time axis measures corpus assembly, not failures), Grok on worth (the census already answers the
> question the instrument was designed to measure). See `docs/DECISIONS.md` rows 22–26 and §12
> below for the full record. The design content past this point is kept as history of what was
> designed and why it was rejected — do not dispatch this plan.

## 1. CONTEXT YOU DO NOT HAVE

The doctrine spine this repo serves (`~/projects/ops-plans/three-laws.md`) ends on a terminal
question: **"Does mechanizing rules reduce failure, or relocate it?"** Nothing measures the answer,
and with the tools on `main` today nothing *can*: post-hoc matching of a new entry to an old family
runs on a clusterer measured at **1/77** blind-paraphrase recall. This plan builds the instrument.
It is deliberately scheduled early — pre-registration must precede the mechanisms it will judge, or
the analysis is retrofitted, and this repo's own C3 measurement refused exactly that.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight
Branch from: main    Work on: feat/recurrence-trend-instrument
Existing artifacts: pipeline/L2/clusters.jsonl (pinned) · pipeline/L2/recurrence-report.md
                    qa-ledger/actor-results.jsonl · catalog/failure-modes.md
Green baseline: pytest 179 passed + 2 skipped, bats 109, guard OK (171 IDs), reconcile COMPLETE 5/5.
```

## 3. GOAL

Ship `pipeline/recurrence_trend.py` plus a **pre-registration committed before any post-period data
exists**, such that the terminal question gets an answer in one of three named directions —
including the negative one.

Three arms, reported separately and **never pooled** (founder ruling R-a, 2026-08-02):

- **Arm A — confirmatory.** Hindsight's own ingest mechanism (`plans/02`, shipped 2026-08-02).
  Families under test are chosen by RULE, never hand-picked: every family at n≥5 as of the freeze
  commit (22 families), randomly split by a seed committed in PREREG — prior art surfaced for one
  half, suppressed for the held-out half. The only arm with a pre-registered control and an empty
  post-period, and **the only arm that can support REDUCED**. Earliest verdict ~2026-11-01.
- **Arm B — retrospective, EXPLORATORY.** 8 families have a working mechanism today, rising to 13
  if the 5 stale paths are repaired. Blocked until `mechanisms.jsonl` carries real ship dates
  recovered by git archaeology — no mechanism records one today. Recorded in advance: most of the
  13 are expected to have too little post-period span to support a trend. Arm B's floor is n≥3
  (ruling R-l), giving six families — c-043 (n=10), c-045 (n=7), c-063 (n=6), c-082 (n=3), c-104
  (n=3), c-191 (n=3) — across fleet, fleet-dispatch and substack.
- **Arm C — CLAIMED-ONLY.** 9 families whose only enforcement claim is not real: 7 genuine phantoms
  (c-013, c-001, c-002, c-006, c-015, c-177, c-169) plus 2 malformed values that were never a file
  path at all (c-040, c-072). The largest are c-013 (n=22), c-001 (n=13), c-040 (n=9) and c-002
  (n=5). Compared against Arm B (real mechanism)
  and the comparator pool (no claim). If claimed-only recurs like no-claim, the effect is
  mechanical; if it recurs like real-mechanism, the effect was attention, not mechanization.
  **Needs no counters and no ship dates.**

- **Unit:** a cause family (`c-NNN`, or hand-declared where the clusterer under-reports).
- **Intervention:** a mechanism ship event in `pipeline/recurrence/mechanisms.jsonl` —
  `{family, mechanism_path, ship_commit, ship_date, fire_counter_path}`.
- **Outcome:** new instances per 30 days **per 100 entries logged corpus-wide**, pre vs post.
- **Comparator:** a size-matched POOL, not one family — all 15 families at n≥5 carrying zero
  enforcement claims of any kind (real, phantom or malformed): c-003 c-004 c-007 c-008 c-038 c-044
  c-049 c-051 c-055 c-058 c-070 c-085 c-101 c-117 c-178. This rule regenerates that exact
  enumeration deterministically from the frozen L2, which is what makes the pool rule-selected
  rather than hand-picked. Matching gap on record: the largest pool family is n=11 against a test
  family at n=22.

## 4. DEFINITION OF DONE

- **D1** `pipeline/recurrence/PREREG.md` is committed **before** any post-period data is collected,
  naming: the three arms; Arm A's randomisation seed and the rule generating its family list; the
  15-family comparator pool; the declared detection-bias direction and its disqualification
  threshold (D8); the denominator definition; and the decision rule below verbatim. PREREG must
  also declare each family's arm memberships and state that the arm axes are independent (R-k) —
  Arm A varies whether hindsight surfaces prior art, Arms B and C vary whether a cross-repo
  mechanism exists, and a family may legitimately appear in more than one arm.
- **D2** The fire-count requirement is scoped per arm (ruling R-i): **Arm B** mechanisms count their
  own firings, appended to `pipeline/enforcement/fired.jsonl`; **Arm A**'s counter is hindsight's own
  ingest log; **Arm C** is exempt by construction — a family whose only enforcement claim is not
  real has nothing that could fire. **Without a fire count a post-period zero is unfalsifiable** —
  "prevented it" and "never ran" are indistinguishable.
- **D3** An Arm B family whose mechanism never fired is **excluded from the numerator and reported
  as UNEXERCISED**, never as a success. Exit 1 if any Arm B family under test lacks a fire count.
  Arm A is checked against the ingest log instead; Arm C carries no fire-count obligation (R-i).
- **D4** Bypasses are counted too — `--force-*` overrides, disabled steps, `continue-on-error`,
  skips. *A mechanism whose override rate rises while its violation rate falls is relocating
  failure into the override.* This is the only direct evidence the RELOCATED arm will ever have.
- **D5** The report prints **raw count and share-of-corpus together**. Pre-registered reading: **a
  drop in raw count with a flat share is NOT evidence of reduction** — it means logging slowed.
- **D6** Instrument validated before use (FM-153): `pipeline/tests/fixtures/recurrence_trend_synthetic.jsonl`
  carries an injected known drop **and a known-flat family**; the tool must recover **both**. A tool
  that only detects drops will detect one in noise.
- **D7** The report prints its own limitations, as the recurrence report already prints its recall
  limit.
- **D8** The detection-bias direction is declared in PREREG and applied as a rule. Pre-period
  recurrence is visible only through the L2 clusterer (**1/77** blind-paraphrase recall);
  post-period recurrence comes from write-time `recurrence_of`, whose recall is strictly higher.
  Post-period counts are therefore biased **upward** — conservative against REDUCED, uninformative
  for a null. **A drop smaller than the declared bias reads UNDERPOWERED by rule**, never REDUCED.

**Decision rule, pre-registered:**
- **REDUCED** — post-period share ≤50% of pre-period for ≥2 test families, over ≥90 days post with
  ≥50 post-period entries, **and** each mechanism fired ≥1 time, **and** Arm A's randomised holdout
  did not drop as much (ruling R-j). The 15-family size-matched pool is a descriptive reference for
  Arms B and C only and can never change a verdict — it is not randomised, so a failure against it
  would be uninformative.
- **RELOCATED** — the targeted family's share drops while corpus-wide share is flat or rising,
  **and** ≥1 new family appears caused by a mechanism being bypassed or misconfigured.
- **UNDERPOWERED** — neither threshold met, or mechanisms did not fire. **Report the negative with
  the same weight as a positive and do not re-cut the windows.** Re-cutting is fitting the
  evaluation set.

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.**
- **R2 Both directions, always.**
- **R3 Ground-truth fixtures are coordinator-authored**, committed before the packet is dispatched.
- **R4 Empty / zero / missing input must FAIL LOUD.** The two zeros must be distinguishable.
- **R5 No exit status through a pipe.**
- **FM-153** Validate the instrument against known-good and known-bad before trusting its count.
- **FM-155** A count must measure units of work PERFORMED, never units merely PRESENT.

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6, plus one specific to this plan.*

- **NEVER delete a catalog row or L1 record**; **NEVER regenerate `catalog/id-ledger.txt`.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER relax a test to make a change pass.** **NEVER edit `conf/` or `pipeline/L1/` to pass a check.**
- **NEVER read a command's exit status through a pipe** (CI-17).
- **NEVER modify a file not listed in §7.**
- **NEVER adjust the decision rule, the windows, or the family list after seeing any post-period
  number.** If the rule turns out to be wrong, say so and stop — do not re-cut.

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/pipeline/recurrence_trend.py
/home/psimmons/projects/hindsight/pipeline/recurrence/PREREG.md
/home/psimmons/projects/hindsight/pipeline/recurrence/mechanisms.jsonl
/home/psimmons/projects/hindsight/pipeline/tests/test_recurrence_trend.py
/home/psimmons/projects/hindsight/pipeline/tests/fixtures/recurrence_trend_synthetic.jsonl
```

## 8. RED-FIRST PROCEDURE

Write `test_recurrence_trend.py` against the synthetic fixture **first**; run it and observe every
test fail on absence. Paste that run. Only then implement.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | `python3 pipeline/recurrence_trend.py --prereg pipeline/recurrence/PREREG.md; echo "exit=$?"` | per-family pre/post **with denominators and fire counts** |
| A2 | `python3 pipeline/recurrence_trend.py --prereg … --families-missing-fire-count` | exit 1 (D3) |
| A3 | `python3 -m pytest pipeline/tests/test_recurrence_trend.py -q` | all pass; both synthetic families recovered (D6) |
| A4 | `python3 pipeline/recurrence_trend.py --input /dev/null; echo "exit=$?"` | non-zero, names the empty input (R4) |
| A5 | `grep -ci 'limitation\|not causal\|directional' <report>` | ≥1 (D7) |
| A6 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥179 passed, 0 failed |
| A7 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf` | **empty** |
| A8 | `bats guard/tests/*.bats bin/tests/*.bats` | ≥109 ok, 0 failures |

## 10. MUTATION REQUIREMENT

- **M1** UNEXERCISED families counted as successes → D3's test must die.
- **M2** share-of-corpus dropped, leaving raw counts only → D5's test must die.
- **M3** the known-flat synthetic family reported as a drop → D6's test must die.

Report survivors explicitly.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight && git checkout -- pipeline/ && \
  git checkout main && git branch -D feat/recurrence-trend-instrument
```

## 12. WITHDRAWAL RECORD (supersedes this plan's original §12)

**Ruling, founder, 2026-08-03: Plan 03's three-arm recurrence-trend instrument is WITHDRAWN.
Mechanize first, measure later.** `docs/DECISIONS.md` rows 22–26.

Two cross-vendor adversarial reviews were commissioned with **orthogonal premises to reject**, and
both returned REJECTED. Neither is neutral; each was commissioned to reject. They matter because
they converged from opposite directions:

- **Codex rejected on VALIDITY.** The outcome's time axis measures corpus assembly, not failures —
  roughly 90% of repaired rows are ingest-dated rather than organically logged. Arm A randomises
  whether *prior art is displayed*, not whether a family is mechanized. Family-level assignment is
  incoherent with per-write delivery. There is no power model. Arm C is selected on the very
  property it is meant to compare.
- **Grok rejected on WORTH.** The census already answers the question: 8 of 192 families have a
  resolving mechanism, and the two largest recurrent families were never mechanized at all. That is
  non-treatment, not a causal gap — so a holdout would manufacture a control arm out of live
  governance risk to measure something the census shows directly.

**The Arm A holdout (P2a) was never implemented.** Prior art was never withheld from any family;
`plans/02` stays fully enabled corpus-wide; no 90-day degradation occurred. Also on record: Grok's
claim that the P0 date-repair defect count was structural was confirmed by a ninth defect instance
while the reviews were still running.

**What this withdraws:** the three-arm design in §3–§4 above (Arm A confirmatory holdout, Arm B
retrospective, Arm C CLAIMED-ONLY), its decision rule, and packets P1–P4. None of it ships. The
design content in §1–§11 is kept as history of what was designed and why it was rejected, not as a
live spec.

**What survives, and where it goes instead:**

- **#32 — land the dated corpus**, dropping the instrument-specific reporting P0 was building
  toward. The date repair itself (git-derived `first_seen`, ingest-date fallback flagged per row) is
  still useful independent of the withdrawn instrument.
- **#33 — repair the 5 stale enforcement paths and reclassify the 9 unreal claims** (P1's census
  work, kept; its consumer — the withdrawn instrument's Arm C — is not).
- **#38 — mechanize c-013** (n=22). **#39 — mechanize c-001** (n=13, this project's founding
  example). These two outrank #32/#33: the census already shows what the instrument was going to
  spend months measuring, so the leverage is building the mechanisms, not re-confirming their
  absence.
- **#22 (`plans/04`)** and **#20 (`plans/05`)** are unaffected by this withdrawal.
- **#34, #35, #36, #37** (P2, P2a, P3, P4) are **closed as not planned**. **#29 remains the parent
  tracker**, retitled to the mechanize-first direction.

This plan file's original escalation notes (data-repair rationale, packet split) are preserved below
verbatim as the historical record of what was designed:

**The measurement-input ruling landed 2026-08-02** (`docs/DECISIONS.md` rows 10–17). Three of the
plan's own premises did not survive the measurements taken during that interview, and the design
above reflected the corrected facts, not the original ones:

- **There is no cross-repo history to backdate against.** No mechanism carries a ship date; the
  `enforcement` object is `{file, kind}` only. Surviving families span days, not months.
- **The corpus's two largest recurrent families have no real mechanism.** c-013 (n=22) named two
  enforcement mechanisms and c-001 (n=13) named one — all three are verified genuine phantoms, files
  that were never built — which is why Arm C existed.
- **The instrument changes at the intervention boundary**, so the bias was declared rather than
  measured away (D8).

**Serial packet split, as originally designed (none of it now ships):**

- **P0 — date repair.** Git-derive `first_seen` for the 242 undated rows; ingest-date fallback for
  the remainder, flagged per row. Survives as #32.
- **P1 — mechanism ledger.** Hand-author `mechanisms.jsonl` by git archaeology across the 3 owning
  repos for the 8 real mechanisms then (13 once the 5 stale paths are repaired); classify the 9
  claimed-only families. Survives as #33.
- **P2 — PREREG + fixture, coordinator-authored (R3).** Closed as not planned (#34).
- **P2a — Arm A holdout, TIME-CRITICAL.** Never implemented. Closed as not planned (#35).
- **P3 — counter/bypass instrumentation.** Closed as not planned (#36).
- **P4 — analyzer.** Closed as not planned (#37).

## 13. REPORT FORMAT

First line **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`, then baselines, the
red-first run, §9 actual-vs-expected, §10 results, `git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch feat/recurrence-trend-instrument off main.
Read /home/psimmons/projects/hindsight/plans/03-recurrence-trend-instrument.md in full and execute it
exactly as written. It is self-contained. Modify ONLY the five files in section 7. The decision rule
in section 4 is PRE-REGISTERED: you may not alter it, the windows, or the family list at any point.
Complete section 8 first and paste the failing run. Run every command in section 9 verbatim.
Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
