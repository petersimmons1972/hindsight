# Adversarial review — PR #3, C1 clustering engine (`pipeline/cluster.py`)

You are an adversarial reviewer from a different vendor than the author. **Reject the premise.
Do not list nits.** Default to FAIL if you cannot independently confirm the work is sound.

## Why this packet matters more than the others

Everything downstream reads `pipeline/L2/clusters.jsonl`. The recurrence report (C2) and the
duplicate-cause guard (C3) — the feature this entire repository exists to deliver — both consume
it. If clustering is wrong, C2/C3 produce confident nonsense and the guard blocks or admits the
wrong entries. This is the one packet where a second vendor's eyes were deliberately reserved.

## Attack the tests, not the implementation

The question is NOT "does the code work". It is: **can this suite pass while clustering is
broken?** Concretely:

- Mutate the implementation and see if the suite notices. Invert a comparison, drop a merge step,
  make the similarity function return a constant, truncate the corpus. **A mutation that survives
  is a defect — name the exact edit.** In this campaign, mutation testing has caught every real
  defect that code review missed, twice on packets whose suites were 100% green.
- Look for assertions satisfied by unconditional output, or that assert only a count while the
  contents are wrong.

## Find BOTH inversions, by name

1. **False positive** — an input where a genuinely NOVEL failure mode lands inside an existing
   cluster. Consequence: the C3 guard will reject real new entries, someone disables it within a
   week, and then there is no guard at all.
2. **False negative** — an input where a KNOWN duplicate falls outside every cluster. Consequence:
   the entire point of the project silently does not work.

Give a concrete input for each, or state plainly that you tried and could not construct one.

## Specific claims to re-derive, not accept

- The PR body claims both backends (HTTP neural embeddings and numpy TF-IDF) clear the bar and
  agree via independent methods. **Re-derive it.** Do not accept the numbers from the PR.
  Verify the HTTP backend is genuinely networked and not silently falling back to TF-IDF —
  a silent fallback that still "passes" is the failure family this repo catalogues.
- A degeneracy invariant is claimed: a bad threshold must exit 1 and write NOTHING. Probe it with
  a *plausible* threshold, not an absurd one. A guard that only fires on obviously-wrong input is
  decorative.
- Empty or missing input must FAIL LOUD. Zero clusters, an empty corpus, a truncated JSONL — none
  may produce a silent clean pass.

## Ground truth

`pipeline/tests/fixtures/recurrence_ground_truth.json` encodes known recurrence families
(completion-signal, shared-mutable-checkout, fail-silent-gate, dedup-identity-key). Check the
clustering actually recovers them — and check whether the test would still pass if it did not.

## Output

End with a single line, exactly `VERDICT: pass` or `VERDICT: fail`. Above it, every finding with
a concrete reproducing input or exact mutation, anchored to file and line. Say explicitly what
you tried that did NOT break it — that is as informative as what did.

## Required artifact

Write your full review to `reviews/C1-clustering-review.md` in the repo, ending with a line that
is exactly `VERDICT: pass` or `VERDICT: fail`. That file is the deliverable; the acceptance gate
checks it exists and carries a verdict line.
