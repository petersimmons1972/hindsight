# hindsight — plan spine

*One accepted version. Revise in place; never append drafts. Supersedes `PLAN-TDD.md`, frozen
verbatim at `archive/PLAN-TDD-2026-08-02.md`. Nothing was deleted in the split.*

## Why this repo exists

Writing failure modes down provably did not stop them recurring. In one corpus alone, "trust the
completion signal" was independently re-logged **≥7 times in 3 weeks** under 7 different IDs;
shared-mutable-checkout **7×**; fail-silent gate 4×. So the registry must be a **gate**, not a
diary.

The pipeline now runs L0→L2 and answers the founding question from real data:

> *"A terminal SUCCESS signal was treated as proof the work succeeded — 13 times across 4 repos,
> 2026-06-12 to 2026-07-25, span 43 days."*

## What is actually true today

Do not trust these numbers — run them. Every count in the previous plan drifted.

| assertion | command | last measured |
|---|---|---|
| catalog sound | `python3 guard/failure_mode_catalog_guard.py` | OK, 171 IDs |
| corpus coverage | `python3 pipeline/reconcile_l1.py` | COMPLETE 5/5 |
| python suites | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | 179 passed, 2 skipped |
| bash suites | `bats guard/tests/*.bats bin/tests/*.bats` | 109 ok |
| CI on main | `gh run list --branch main --limit 1 --json status,conclusion` | completed/success |

## The finding that re-points this plan

**The registry does not consult itself.** Verified by inspection 2026-08-02:

- `.githooks/pre-commit` is 5 lines and execs only the catalog guard.
- `bin/similar-causes.py` has **no production caller** — only its own tests.
- `bin/add-failure-mode.sh` contains zero references to similar / cluster / recurrence.
- `bin/require-real-ci.sh` is called only by `bin/land.sh`; `guard.yml` runs its tests, not the tool.

In the one repo where we fully control the moment of action, **adding a failure mode does not check
whether the corpus already knows it.** Everything built so far hardens the machinery *around* a
registry that is, for its own repo, still a diary.

The second consequence is worse: the terminal question — *does mechanizing rules reduce failure, or
relocate it?* — is currently **unmeasurable**, not merely unmeasured. Post-hoc family matching runs
on a clusterer measured at **1/77** blind-paraphrase recall. The only viable numerator is recurrence
recorded **at write time**, which is the same change as `plans/02`.

## Scope correction, stated plainly

The word "gate" changed referent and no phase was re-derived from the new one. The original gate —
*the registry rejects a re-described duplicate* — was **cancelled by measurement**, not deferred:
recall@5 0.523 against a 0.70 bar, and max distractor score exceeding max true-positive score, so no
threshold separates them at any operating point. Three approaches were refuted, not one abandoned.

What replaces it is narrower and honest: the registry **surfaces prior art at the moment of writing
and claims nothing more**. Plans below are derived from *that* deliverable.

Also on record, because a plan that hides its own negative result is the failure family this repo
catalogues: harness-corpus mechanizability measured **8.3% mechanism / 31.7% partial / 59.3%
judgment**, against a rule pre-registered at "60% transformative, 15% a rounding error."
**Law 1 cannot fix context rot.** The leverage is Laws 2 and 3, and that claim is a hypothesis with
no pre-registered metric of its own — it is not a finding.

## Plans

Each is self-contained and executable by a model with zero conversational context
(`codex exec "$(cat plans/NN-....md)"`). Ceiling (advisory target): **≤250 lines, ≤6 §7 paths, exactly 1 issue.**

| # | plan | issue | status |
|---|---|---|---|
| 01 | `plans/01-enforcement-disclosure.md` | #18 | COMPLETE — PR #27 merged; main guard green |
| 02 | `plans/02-ingest-consults-corpus.md` | #19 | COMPLETE — PR #28 merged; main guard green |
| 03 | `plans/03-recurrence-trend-instrument.md` | #29 | **WITHDRAWN 2026-08-03** — rejected on validity (Codex) and worth (Grok); `docs/DECISIONS.md` rows 22–26 |
| 04 | `plans/04-sync-repair-and-distribute.md` | #22 (closes #24) | FOUNDER-BLOCKED — decide push-vs-pull before merging the #40/#41/#43/#44/#46 stack; #24 must choose this path or C6c |
| 05 | `plans/05-enforcement-locality.md` | PR #12 | BLOCKED — issue #20 closed with packet 20-1/PR #52; the remaining locality work is held behind Plan 04 and closes PR #12 only when its replacement capability lands |
| 06 | `plans/06-l3-invariant-ledger.md` | #21 | FOUNDER-BLOCKED — coordinator fixture landed in PR #63; resolve W1/W2 disk-artifact contract before dispatch |
| 07 | `plans/07-discriminating-rebuild.md` | #23 | FOUNDER-BLOCKED — PR #48 closed as unsound; choose supported-shape gate, language-aware reducer, or diagnostic-only behavior |
| 08 | `plans/08-reconcile-partial-is-not-pass.md` | #25 | **COMPLETE — PR #26 merged; main guard green** |

`docs/INVARIANTS.md` is the canonical R1–R9 + PROHIBITIONS source. `docs/LEDGER.md` is executed,
not read. `docs/DECISIONS.md` records founder rulings and whether each is APPLIED, HALF-APPLIED, or
OPEN — #18 was lost for a day because "half-applied" had nowhere to live.

## Sequencing

```
08  #25  PARTIAL must not exit 0       <- COMPLETE: PR #26 merged, main guard green
01  #18  enforcement disclosure        <- COMPLETE: PR #27 merged, main guard green
02  #19  ingest consults the corpus    <- the dogfooding closure; prerequisite for 03
03  ---  recurrence-trend instrument   <- WITHDRAWN 2026-08-03; replaced by #38/#39 mechanization
04  #22  sync repaired, becomes the distribution channel (closes #24)
05  PR #12  enforcement locality; then close PR #12  <- #20 closed by packet 20-1 / PR #52
06  #21  L3 invariant ledger, reshaped from prose to a validated ledger  <- fixture merged; W1/W2 artifact contract needs founder ruling
07  #23  discriminating rebuild, attack-spec-first                       <- PR #48 rejected; design-ruling blocked
```

**08 first**, added after a cross-vendor ledger audit on 2026-08-02 and reproduced by the
coordinator: `reconcile_l1.py` prints `PARTIAL (1/5 sources resolved)` and **returns 0**, so the CI
step reports green while comparing one source in five. It is the sixth rung of the ladder, it
presents as an ordinary successful step rather than an explicit skip, and unlike every earlier rung
it requires **no edit at all** — it is the current state of `main`.

**01 second** because it is two files and discharges a ruling currently *worse than what was
authorised* — and because if a Terra dispatch cannot execute it cleanly, the template is wrong and
we learn that at minimum cost.

**03 third and not last**: it must be pre-registered before more mechanisms ship, or the analysis is
retrofitted. The measurement-input ruling landed 2026-08-02 (`docs/DECISIONS.md` rows 10–17) and
three of this plan's premises did not survive it. There is no cross-repo history to backdate
against — no mechanism carries a ship date — and the corpus's two largest recurrent families,
c-013 (n=22) and c-001 (n=13, this project's founding example), turned out to have no real
mechanism at all: c-013 named two enforcement mechanisms and c-001 named one — all three are verified
phantoms. That finding became a third arm.
The instrument now runs three arms, reported separately and never pooled: **Arm A** confirmatory
(hindsight's own mechanism, rule-selected with a randomised holdout, the only arm that can support
REDUCED, earliest verdict ~2026-11-01); **Arm B** retrospective and exploratory, floor n>=3 (six
families: c-043, c-045, c-063, c-082, c-104, c-191), blocked on ship-date
recovery; **Arm C** CLAIMED-ONLY, comparing families whose only enforcement claim is not real
against those with a real one and those with none — which needs no counters and no ship dates. It
splits serially into P0 date repair, P1 mechanism ledger, P2 coordinator-authored PREREG and
fixture, P2a the time-critical Arm A holdout, P3 cross-repo counters, P4 the analyzer.
**RELOCATED stays unreachable until P3 lands and must not be approximated.**

**Superseded 2026-08-03 — WITHDRAWN.** The paragraph above is kept as history of the ruled design;
it did not ship past P0/P1. Two cross-vendor adversarial reviews, commissioned with orthogonal
premises to reject, both returned REJECTED: Codex on validity (the time axis measures corpus
assembly, not failures — ~90% of repaired rows are ingest-dated; Arm A randomises prior-art display,
not mechanization; no power model; Arm C selected on the property it measures), Grok on worth (the
census already shows 8 of 192 families mechanized and the two largest recurrent families never
mechanized at all — non-treatment, not a causal gap). The Arm A holdout (P2a) was never
implemented — `plans/02` stayed fully enabled corpus-wide. Full record: `docs/DECISIONS.md` rows
22–26, `plans/03` §12. Replacement priority is mechanization over measurement: #38 (c-013, n=22),
#39 (c-001, n=13) outrank #32 (land the dated corpus) and #33 (repair 5 stale paths, reclassify 9
unreal claims). #34/#35/#36/#37 closed as not planned; #29 remains the parent tracker.

**06 late, deliberately.** This departs from founder ruling 1, which named W1/W2/W3 as next, and the
departure was surfaced and approved rather than slipped in. Ruling 1 chose "build the recurrence
spine" over "wire up what exists"; the spine is delivered through L2. Building L3 before `02` means
re-deriving it once `recurrence_of` changes what a recurrence *is*.

### Deferred infrastructure design — #30 artifact equivalence

Issue #30 is not a license to run `cluster.py` against CI's live/absent embedding service. That
would make the gate nondeterministic and contradict the pinned-L2 contract. Its implementation
must separate provenance capture from deterministic verification: a controlled release task records
the exact L1 digest, cluster-code/config digest, backend/model identity, and ID-keyed embedding
snapshot; CI then replays clustering solely from that committed snapshot and byte-compares the
canonical L2 output. Deterministic mechanical L1 subsets are replayed against committed source
snapshots; non-mechanical L1 rows are covered by explicit source/revision hashes, not falsely
claimed regenerated. CI must fail on a changed L1 digest, missing/extra embedding ID, changed
vector/config provenance, or a changed L2 partition; it must never call the HTTP backend. Split
this into ≤6-path packets if its precise artifact formats exceed the plan ceiling.

Serial throughout (R8). Schedule 02, 04, 06, 07 as cross-vendor triangle packets — the QA hypothesis
is stuck at N=1 against a pre-registered rule needing ≥5, and four packets reaches it at zero extra
scope. Record each in `qa-ledger/actor-results.jsonl`. **Do not read the rule early.**

## Project-level exit criteria

A campaign with no declared end becomes a permanent condition — which is how the audition debt got
exempted three times. When X1–X6 all hold on green main, hindsight stops being a campaign and
becomes an operation; anything after that is new work needing a new decision, not campaign residue.

| # | criterion | command |
|---|---|---|
| X1 | Ingest is one command and consults prior art | `bash bin/add-failure-mode.sh … && python3 pipeline/reconcile_l1.py` → both 0, COMPLETE, row carries `recurrence_of` |
| X2 | Every claim is a command that has been run | `bash bin/verify-ledger.sh` → 0 |
| X3 | The floor reaches its consumers and each verifies its own claims | dry-run diff empty for all 12; `--require-attestations --max-age-days 14` → 0 |
| X4 | Recurrence trend measured against a pre-registered rule | `python3 pipeline/recurrence_trend.py --prereg pipeline/recurrence/PREREG.md` → per-family pre/post with denominators **and fire counts**; exit 1 if any family lacks a fire count |
| X5 | Plan packets keep required structure; L3 validator runs when present | `bash bin/check-plan-preamble.sh` (structure + advisory ceiling); `python3 pipeline/validate_l3.py` when `pipeline/L3/invariants.jsonl` exists |
| X6 | The terminal question has a written answer, whichever way it points | `docs/TERMINAL-ANSWER.md` exists, cites X4 by commit hash, states REDUCED / RELOCATED / UNDERPOWERED |

## Out of scope

- **D2's 8 unbuilt mechanisms** — decided *build*, but they are PreToolUse hooks belonging in
  `~/.claude`, not this repo (Law 2: reach follows context).
- **Re-running the W3 classifier over the harness corpus** — answered by `pipeline/harness/RATIO.md`.
- **Deliberate hash forgery** in any attestation design. The threat being closed is the ordinary
  edit, the lazy shortcut, the routine optimization. Say so; do not imply it away.
