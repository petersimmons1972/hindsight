# QA protocol — the cross-vendor triangle

*Founder-directed, 2026-08-02. Written because we do not have this shape yet, and because the
hypothesis that it changes outcomes is worth testing rather than asserting.*

---

## The problem this exists to fix

On 2026-08-01/02 this repo ran a full campaign in one shape: **Claude builds (sonnet), Claude
verifies (opus)**. Every actor result is captured in `qa-ledger/actor-results.jsonl`.

**Measured baseline — 43 actor-runs, 15 explicit verdicts:**

| metric | value |
|---|---|
| first-pass acceptance (`CONFIRMED_GOOD` on first verify) | **2 / 15 = 13%** |
| `DEFECTIVE` verdicts | 13 |
| HIGH-severity findings raised by verifiers | 66 |
| rounds to acceptance, C4 lineage | **6, still not accepted** |
| rounds to acceptance, G1 lineage | 5 |
| rounds to halt, G2 lineage | 3 (design abandoned) |
| vendor on both sides of QA | **100% anthropic** |
| verify-role actors that emitted **no verdict line at all** | **16 / 31** |

Three things that baseline says:

**1. The adversary is always downstream of the builder.** The builder writes the implementation
*and* the tests that grade it, then a verifier attacks. A builder cannot anticipate an adversary
stronger than itself, so the verifier nearly always wins and a full round is spent. 13% first-pass
is not a quality problem with any one agent — it is what this ordering produces.

**2. Same-vendor QA has correlated blind spots.** Builders were sonnet, verifiers opus: same
family, same training, same priors. The single highest-yield review of the campaign was the one
**cross-vendor** actor — Grok on PR #3 — which found the default-path corpus collapse and the
markers-authored-from-tests defect that four same-vendor rounds had missed. This is our own
`convergence-is-not-corroboration` lesson turned on ourselves: N reviewers from one vendor is
closer to N=1 than to N.

**2b. Half the verifiers never returned a verdict.** 16 of 31 verify-role actors emitted no
`VERDICT:` line. Rule 4 exists because the landing gate matches on that literal string, so those
runs were **unlandable by construction** — the work was done and then could not be acted on. This
is not a failed verification; it is a failed *report*, and the two must never share a denominator
(dividing acceptance by all 31 gives a false 6% and hides the reporting gap inside the quality
number). The acceptance figures above divide by the 15 actors that actually returned a verdict.

**3. The one stage that worked in a single pass was adversary-first.** C1d's blind holdout — the
fixture author was a *different agent* that was forbidden to read the implementation it would
grade — produced the campaign's cleanest measurement with no repair round. That is the exception
that identifies the rule.

---

## The shape

| stage | actor | vendor | output |
|---|---|---|---|
| **1. Attack spec** | adversary | **A** (Grok / Codex) | the acceptance suite — the inputs that must fail — **committed before any implementation exists** |
| **2. Build** | implementer | **B** (Codex via `cli-dispatch`) | make the committed suite pass; may add tests, **may not weaken them** |
| **3. Verify** | skeptic | **C** (Claude / opus) | attack what stages 1 and 2 both missed |

Three properties, each earning its place:

- **Adversary-first inverts the order.** The builder is now downstream of the attack spec instead
  of upstream of it, so the cheap failures are found before implementation rather than after.
- **Vendor rotation decorrelates blind spots.** Different training, different priors, different
  things that "look fine". Agreement across A and C is real corroboration; agreement within one
  family is not.
- **The fixture is out of reach of whoever must satisfy it.** The defect that sank two rounds of
  C1 was one agent authoring both the regexes and the sentences grading them.

### Rules

1. **The attack spec is committed before implementation exists.** If it lands after, it is not an
   attack spec — it is a description of what was built.
2. **The implementer may not modify the attack spec.** Adding tests is fine; weakening, deleting
   or exempting is a refusal, escalated to the coordinator.
3. **Every mutation must be exercised in the environment that gates**, not only where it was
   written. A result from one environment is not a result (FM-158).
4. **Verdict is a literal first line**: `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`. The
   landing gate matches on that string and merges on nothing else.
5. **Every actor's result is appended to the ledger**, pass or fail, so the arms stay comparable.
6. **Retry ceiling 2 per lineage, then re-scope rather than re-run.** Tonight, C4 reached round 6
   and G2 round 3 before the design — not the implementation — turned out to be wrong. The signal
   to stop is not the round count; it is **the bypass getting shorter**, or the same defect class
   reappearing one layer up.

---

## The hypothesis under test

> Cross-vendor, adversary-first QA raises first-pass acceptance above 13% and reduces rounds-to-
> acceptance, without lowering the number of real defects found.

**Both halves matter.** A shape that raises first-pass acceptance by finding *fewer* defects is
worse, not better — it would just be a weaker adversary. So the ledger records severity counts
alongside verdicts, and a rise in acceptance with a fall in HIGH findings is a **negative** result.

### Metrics

Per packet, from `qa-ledger/actor-results.jsonl`:
- `first_pass` — verdict of the first verify actor
- `rounds_to_acceptance` — or `halted` / `descoped`
- `sev_high` raised, per stage, and **which stage caught what**
- vendor of each stage

### Pre-registered decision rule

Written before the first cross-vendor packet runs, so it cannot be fitted afterwards:

- **≥ 40% first-pass acceptance across ≥ 5 packets, with HIGH findings per packet not falling
  below the baseline mean** → adopt the triangle as the default and graduate this document to
  `fleet/`.
- **20–40%, HIGH findings held** → keep it for high-stakes packets only; mechanical work stays
  single-vendor.
- **< 20%, or HIGH findings drop materially** → the shape is not the lever. Record the negative
  result and stop paying the coordination cost.

**A negative result is a real result and gets recorded with the same weight as a positive one.**
The point is to know, not to be right — the alternative is asserting a process improvement the
way "both backends agree" was asserted, which is the failure this campaign spent a night
measuring.

---

## Honest limitations of the baseline

- **Not a controlled experiment.** The baseline packets were also the *hardest* ones and the
  earliest, when the briefs were least refined. Some of the 87% DEFECTIVE rate is brief quality
  improving over the night, not vendor sameness.
- **The role classifier in `bin/harvest-qa-ledger.py` is heuristic** — it infers role from prompt
  text, and rows tagged `verify` include some land/audit actors that quote verifier language.
  Verdict counts are exact; role counts are approximate. Stated here rather than smoothed over.
- **N is small.** 15 verdicts is enough to see a 13% rate is not 50%; it is not enough to
  distinguish 40% from 55%. The decision rule's thresholds are set wide for that reason.
- **One cross-vendor data point is an anecdote, not an arm.** Grok's PR #3 review is the reason
  for the hypothesis, not evidence for it.
