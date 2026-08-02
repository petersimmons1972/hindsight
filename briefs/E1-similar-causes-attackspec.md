# E1 stage 1 — ATTACK SPEC for `bin/similar-causes.py`

**You are the adversary, not the implementer. You are stage 1 of 3.**

There is no implementation of this tool and there must not be one when you finish. Your entire
deliverable is the acceptance suite that a *later, different* agent from a *different vendor* will
have to satisfy. It will be committed before that agent starts, and it may not weaken your tests.

Read `QA-PROTOCOL.md` in the repo root first — it explains why this ordering exists and what is
being measured. Then read `CLAUDE.md` for the non-negotiables.

## Why this tool exists, and what it is NOT

C3 was specified as a **guard**: `--check-duplicate-cause` would refuse a new catalog entry whose
cause already existed. That guard has been **cancelled by measurement**, not by opinion. Three
independent approaches were measured against blind holdouts:

| approach | pooled recall@5 | distractor separation |
|---|---|---|
| clustering engine | 1 / 77 reached any real entry | — |
| similarity ranking (Arm C) | 0.523 | FP 0.75, AUC 0.53–0.57 (chance) |
| structured cause extraction (Arm B) | 0.262 | AUC 0.543 / 0.350 (chance and below) |

Bar was recall@5 ≥ 0.70 and distractor FP ≤ 0.10. Everything missed, and the binding constraint is
that **the maximum distractor score exceeds the maximum true-positive score** — no threshold
separates them at any operating point.

So the rejection semantics are **removed, not weakened**. What ships is a lookup that surfaces prior
art for a human to judge. A guard that silently misses ~85% of reworded duplicates while implying it
catches them is precisely the failure family this repository exists to catalogue — a proxy reported
as the thing.

**Your tests must make it impossible to quietly reintroduce guard semantics.** That is the single
most important property you are protecting.

## The contract you are writing tests against

New file, `bin/similar-causes.py`. Nothing else in the repo may be modified by the implementer.

```
bin/similar-causes.py "<free-text description of a proposed failure mode>"
```

- Reads the corpus at `pipeline/L1/*.jsonl` (463 entries, field `instance`). **Read-only.**
- Prints **at most 10** candidate entries, ranked, each with its score and source.
- Prints, verbatim and unconditionally, the header:
  `Candidates for human review. This tool does not determine duplication.`
- Exit code is **advisory-shaped**: `0` whether or not candidates are found, because finding
  nothing is a legitimate answer from a lookup. Non-zero **only** for operational failure
  (corpus unreadable, corpus empty, bad usage).

Anything not pinned above is the implementer's choice — including the ranking function. **Do not
specify an algorithm.** You are pinning observable behaviour, not a design. Ranking quality is
explicitly NOT under test here; the measurements above already established that no available
ranker clears a quality bar, and a test asserting recall would just re-litigate a settled question.

## What to attack

Write tests that fail against a plausible naive implementation. At minimum:

1. **Guard-semantics regression.** The tool must never exit non-zero merely because a similar
   entry was found, and must never emit language asserting that something *is* a duplicate. Assert
   on the literal header and assert the absence of verdict-shaped output. Think about how an
   implementer under pressure would sneak a threshold back in, and close that door by name.
2. **Fail loud on an empty or unreadable corpus.** Zero candidates from a *populated* corpus is a
   valid result. Zero candidates because the corpus failed to load is a **defect that must exit
   non-zero and say so**. An implementation that cannot tell those apart is the single most likely
   real-world failure — the fail-silent family. Test both directions separately.
3. **Determinism.** Same query twice → byte-identical output, including tie order.
4. **The cap is a cap, not a silent truncation.** Never more than 10. If more than 10 candidates
   scored above zero, the output must say so rather than imply 10 was all there was.
5. **Read-only.** Assert the corpus and the catalog are unmodified after a run — compare hashes.
6. **Degenerate inputs.** Empty string, whitespace only, no argument at all, a query longer than
   any corpus entry, non-ASCII. Each must produce a defined outcome, not a traceback.

Add anything else you can break. You are rewarded for the tests that survive, not for coverage.

## Rules

- **Do not write `bin/similar-causes.py`.** If your suite passes when you finish, you have written a
  description of an implementation instead of an attack spec, and the packet is void.
- **Prove the red.** Every test must fail now. State in your summary the exact command you ran and
  what the failures were. A test that passes against a non-existent tool is a broken test, and
  "it errored because the file is missing" is not the same as "it failed for the reason I intend" —
  distinguish those.
- **Never modify `pipeline/L1/`.** It is the source corpus. A previous packet was closed unmerged
  for editing it to manufacture a green.
- Fixtures you need (a tiny corpus, an empty corpus, an unreadable one) go under
  `bin/tests/fixtures/similar-causes/`. The tool must be pointable at a fixture corpus — specify
  how in your tests and make that part of the contract.
- Gate command must be a single command: `bash bin/tests/test_similar_causes.sh`.

## Budget

Bounded packet. **Cap: 40 tool calls.** If you hit it before finishing, stop and say exactly what
is incomplete — a partial suite reported as complete is worse than a reported cutoff.

## Deliverable

`bin/tests/test_similar_causes.sh` plus fixtures. Your final summary must state, as its first line:

`ATTACK SPEC READY: <n> tests, all failing`
