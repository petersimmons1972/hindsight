# QA panel — adversarial verification of `bin/similar-causes.py`

You are performing an **adversarial verification** of a small tool. Report only defects you
**reproduce**, each with an exact command and its actual output.

## The artifact

`bin/similar-causes.py`, with its acceptance suite at `bin/tests/test_similar_causes.sh`.
**The suite currently PASSES: 27 of 27.** Your job is to find what the suite does not.

## What the tool is contractually required to do

- It is a **LOOKUP, not a guard**. For a free-text failure-mode description it prints up to 10
  candidate corpus entries for a human to judge.
- It must print, verbatim and unconditionally, the header:
  `Candidates for human review. This tool does not determine duplication.`
- It must **never exit non-zero merely because a match was found**, and must **never emit language
  asserting that something IS a duplicate**. A rejection guard was deliberately **cancelled** by
  measurement; anything that lets one be reconstructed defeats the tool's purpose.
- Exit non-zero **only** for operational failure (corpus unreadable, corpus empty, bad usage). Zero
  candidates from a *populated* corpus is a legitimate exit-0 answer.
- At most 10 candidates, with truncation disclosed if more matched.
- Read-only at runtime.

**Ranking quality is explicitly NOT under test.** Do not file findings about recall or ranking
accuracy — that question is settled by measurement and is out of scope.

## Rules

- Do not modify the tool or the suite except transiently to demonstrate a point; restore anything
  you touch.
- Do not push, merge, or open PRs.
- A finding you cannot demonstrate with a command is a hypothesis. Label it as such, or drop it.
- Severity **HIGH** means: it breaks a stated contract above, or it lets a wrong result be reported
  as a right one.
- **Tool-call cap: 50.** If you hit it, say exactly what you did not reach.

## Deliverable

Your final response MUST begin with a literal first line, exactly one of:

`VERDICT: CONFIRMED_GOOD`
`VERDICT: DEFECTIVE`

Then a numbered list of findings, each with severity, the reproducing command, and its real output.
