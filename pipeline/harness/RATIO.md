# The mechanizable ratio — first measurement

*2026-08-01. Answers the question `ops-plans/three-laws.md` says must be answered before
any plan is sized: "What fraction of the harness corpus is actually mechanizable? At 60%
this is transformative; at 15% it is a rounding error."*

**Answer: 8.3% fully mechanizable. 40% at the optimistic ceiling. Below the founder's own
rounding-error line.**

---

## Method

145 normative rules classified: 102 memory files matching `/(feedback|lesson|principle)-`,
plus 43 distinct rules extracted from global `CLAUDE.md`. Nine isolated agents, each seeing
only its slice — the corpus never entered the coordinator's context (Law 2 applied to the
measurement itself). Raw classifications: `h01..h08.jsonl`, `claude-md.jsonl`.

Deliberately excluded: `reference`, `project`, and `user` memories. Those are *facts*, not
directives — there is nothing in them to enforce, and including them would have inflated the
denominator while leaving the numerator flat.

### The anti-inflation rule

"Mechanizable in principle" is cheap talk, and we were about to size a campaign on this
number. So a `mechanism` or `partial` claim was only accepted if it named **both** a concrete
deterministic check **and** its trigger point (`PreToolUse-hook`, `PostToolUse-hook`, `CI-job`,
`unit-test`, `lint-rule`, `git-hook`, `schema-constraint`, `wrapper-script`). Three exclusions
were enforced:

1. "Instruct the model harder" is not a mechanism. A mechanism runs whether or not anyone
   remembers.
2. "An LLM could check this" is not a mechanism. A model-based checker inherits the exact
   forgetfulness the rule already has.
3. A check that would fire constantly on legitimate work was downgraded — it would be
   disabled within a day, and then you have neither.

**0 of 145 rows violated the schema rule** (every mechanism/partial named check + trigger).
Counts were recomputed from the JSONL on disk, not taken from the agents' self-reports.

---

## Result

| bucket | n | share |
|---|---:|---:|
| `mechanism` — deterministic check, no model judgment | 12 | **8.3%** |
| `partial` — catches common violations, provably not all | 46 | 31.7% |
| `judgment` — requires intent/context; no deterministic check | 86 | **59.3%** |
| `obsolete` | 1 | 0.7% |

By corpus:

| corpus | n | mechanism | mech+partial | judgment |
|---|---:|---:|---:|---:|
| memory files | 102 | 6.9% | 37.3% | 61.8% |
| global `CLAUDE.md` | 43 | 11.6% | 46.5% | 53.5% |

`CLAUDE.md` is roughly twice as mechanizable as the memory corpus — consistent with it
holding more operational plumbing and fewer epistemic lessons.

### The confidence signal

**All 8 high-confidence classifications are `mechanism`. Not one `partial` is high
confidence** (39 medium, 8 low, 3 unstated). The optimistic bucket is precisely the
uncertain one, so 40% should be read as a ceiling that erodes under scrutiny, not as a
target.

---

## The finding that changes the plan

Of the 12 `mechanism` items, **4 already exist** and 8 have never been built:

| already enforced | by what |
|---|---|
| escalate before writing protected files | `protected-path-write-guard.sh` |
| never patch the guard unasked | same hook — `path:*.claude/hooks/*` is in its own list (verified self-protecting) |
| agent may self-manage the memory index | same hook's `exact:` entries |
| plan writes never gated | `worktree.bgIsolation: "none"` in `settings.json` |

**The entire live enforcement surface of this harness is one 354-line PreToolUse hook and
one settings value.** Everything else in 145 rules — including all 8 unbuilt mechanisms —
runs on the model remembering.

So the practical figure is worse than 8.3%. The *buildable-new* mechanism count is 8 of 145
= **5.5%**, and the already-won context reduction from Law 1 is 4 rules.

Unbuilt, and all cheap: block `git push --force` without branch-named authorization; reject
`nohup … &` inside a `run_in_background` Bash call; require an explicit `model` on every
Agent/Workflow spawn; block the `GH_TOKEN=$(gh-app-token …)` prefix; gate worktree/branch
deletion on `git status --porcelain` rather than `merge-base --is-ancestor`; retry ceiling;
per-call token ceiling on direct-API agents. Seven of the twelve share one trigger point
(`PreToolUse-hook`), so they are variations on an already-proven pattern, not seven new
mechanisms.

---

## A hypothesis this measurement rejected

The appealing reframe was: *the 8% that is mechanizable is exactly the set of rules whose
violation is unrecoverable* — which would make a small ratio still high-value. Cross-tabbing
bucket against whether the rule text governs a destructive/irreversible action does **not**
support it:

| group | n | mechanism | mech+partial |
|---|---:|---:|---:|
| destructive-domain | 36 | 5.6% | 50.0% |
| everything else | 109 | 9.2% | 36.7% |

Pure mechanizability is *lower* in the destructive group, not higher. (Keyword proxy on rule
text, not semantic classification — crude, and it would take a better classifier to settle.
But it is the test that was available, it pointed the wrong way, and the reframe is recorded
as rejected rather than quietly dropped.)

---

## What this means for the Three Laws

**Law 1 does not shrink context.** Mechanizing everything mechanizable removes ~8% of the
rule corpus. Starting context is 255 lines and, by the 2026-07-29 measurement,
instruction-file size is 0.025% of spend. Law 1 was never going to fix context rot, and the
two stated goals — simplify starting context, push work into isolated contexts — are
**independent programs**, not one program. Conflating them would have sized a campaign
against the wrong denominator.

**Law 1 is still worth doing, for a different reason.** It buys enforcement that fires at
turn 300, on eight specific rules, at the cost of a handful of hook patterns. That is a good
trade at a small scale. It is not a transformation.

**The leverage is Law 2 and Law 3.** 59% judgment is irreducible by definition — no check
will ever enforce "verify auth by exercising it" or "convergence is not corroboration." If
most rules cannot be mechanized, the way to survive their being forgotten is to bound what
forgetting can damage (smallest context) and to make it undoable (carry your own undo).
Those apply uniformly, regardless of whether a given rule is enforceable.

The 2026-08-01 incident supports this: Law 1 would not have prevented it (no hook existed or
was proposed for "don't run a `||` fallback against a real config"), but Law 3 would have
bounded it, and Law 2 would have kept the real `consumers.conf` out of reach.

---

## Terminal question

`three-laws.md` asks: *does mechanizing rules reduce failure, or relocate it?* This
measurement does not answer that. It answers the prior question — how much *can* be
mechanized — and the answer is: much less than the program assumed. The terminal question
still needs the eight mechanisms actually built and then observed.

## Side observation (not acted on)

The live guard's pattern list still contains bare `path:*token*`. `CLAUDE.md` describes a
2026-07-31 narrowing of that pattern; it is not present in the live file, and the only
allowlist in the hook is for `gh issue|pr create|comment`. Worth confirming whether the
narrowing landed. Not touched — protected path.
