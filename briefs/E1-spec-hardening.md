# E1 stage 1b — HARDEN your own attack spec against what it missed

**You are the adversary again.** You wrote `bin/tests/test_similar_causes.sh` (27 tests) before any
implementation existed. A different vendor then implemented `bin/similar-causes.py` and passed all
27. Three independent stage-3 verifiers then attacked the result, and **all three returned
DEFECTIVE**.

Read `QA-PROTOCOL.md` first. The full verifier output is committed at
`qa-ledger/e1/stage3-verifier-output.txt` — read it; the reproductions are exact.

**Your suite is what failed here, not only the implementation.** One verifier's summary was: *"The
implementation as committed is correct; the defect is that the suite does not hold it there."* It
ran 19 mutants against the implementation and **11 survived** — 11 ways to break the tool that your
27 tests still call green. This brief is not a criticism of the spec; it is the second half of the
job. Close the holes.

## Your job

Add tests to `bin/tests/test_similar_causes.sh` that FAIL against the current
`bin/similar-causes.py`, covering every vector below. You may restructure existing tests, but you
may not weaken any assertion that currently holds.

Work from the branch `dispatch/E1-similar-causes-build` (PR #15) so the implementation is present —
your new tests must be red against it, and that is the point.

## The holes, in priority order

### 1. The guard was rebuilt. Twice. On the default corpus path.

This is the one thing the packet exists to prevent, and it got through.

- **Exit code discriminates match from no-match.** `PYTHONIOENCODING=ascii python3
  bin/similar-causes.py "<query that matches>"` exits **1** via an uncaught `UnicodeEncodeError`
  (the real corpus contains em dashes); a non-matching query exits **0**. It also reproduces with
  **no environment variable at all** when a corpus record's `instance` contains a lone surrogate.
- **`| head -1` exits 120 on match, 0 on no-match.** The `except BrokenPipeError` handler is dead
  code: the error fires while flushing `sys.stdout` during interpreter shutdown, outside the `try`.
  A verifier built a working duplicate-guard on top of this in two lines of shell.

Test for the **property**, not these two mechanisms: *no invocation may distinguish "match found"
from "no match" by exit status, under any encoding, any corpus content, or any downstream pipe.*
Both of these were exit-status oracles; assume there are others.

### 2. Match semantics are never exercised on the default corpus.

Every match test uses `--corpus` fixtures. T19 is the only default-path test and it explicitly
tolerates a non-zero exit. So a mutant that adds a full duplicate-guard **only when `--corpus` is
absent** passes 27/27:

```python
if args.corpus is None and ranked and max(v for v, _ in ranked) > 0.05:
    print(f"DUPLICATE. This cause is already recorded as {record.identifier}...", file=sys.stderr)
    return 1
```

Pin the default path directly: a query with known matches in the real corpus must exit 0, print the
header, and print candidate rows.

### 3. Corpus text reaches stdout unsanitized.

One record can inject newlines and ANSI escapes. Reproduced: `ESC[2J ESC[H` erases the mandated
header and a forged header plus `VERDICT: DUPLICATE ... rejected as duplicate` is what the terminal
actually displays. Separately, forged rows made **15** scored rows appear against a stated cap of
10, with scores *increasing* down the page, no truncation notice, and fabricated provenance
pointing at `catalog/failure-modes.md`.

T02/T24 missed it because `grep -Fxq` on the byte stream cannot see erasure. T16/T17/T22 missed it
because their fixtures contain no newlines. Assert on **what a terminal renders**, and assert that
no field may introduce a line break.

### 4. Your forbidden-language check is a fixed list of 24 multi-word phrases.

The bare tokens `DUPLICATE`, `REJECT`, `DO NOT ADD` are not on it. A per-row verdict prefix
(`"DUPLICATE - DO NOT ADD" if value > 0.2 else "candidate"`) passes T04 and T21. Make the check
structural rather than a blocklist — a blocklist of phrases is enumerable, and the actor choosing
the phrasing gets to read your list.

### 5. Silent partial corpus load — the two zeros, again.

`load_records()` guards only the *total* zero case. Individual unparseable records are dropped with
a bare `continue`: **309 of 475 records (65%) vanished with zero bytes on stderr**, and the output
was one candidate different from healthy. A UTF-8 BOM silently discards the first record of every
file it prefixes.

T23 currently *sanctions* this by accepting "skip bad lines, exit 0" as a defined outcome. The
defect is not the skipping, it is the **silence**. Require a count of loaded and skipped records
whenever any were skipped, and assert it.

### 6. The cap and truncation notice are unpinned.

T16 asserts only `1 ≤ n ≤ 10`; T17 asserts only that *some* truncation-ish word appears. Neither
pins the cap at exactly 10, nor that the disclosed total is **correct**. A mutant reporting a false
count passes.

## Rules

- **Prove the red.** Every new test must fail against the current implementation on
  `dispatch/E1-similar-causes-build`. State the command and the actual failures.
- **Do not modify `bin/similar-causes.py`.** You are the adversary; a different vendor repairs it.
- **Never modify `pipeline/L1/` or `catalog/`.** Both are protected at dispatch time.
- Tool-call cap: **50**. If you hit it, say exactly which vectors are uncovered.

## Deliverable

First line of your summary, literally:

`SPEC HARDENED: <n> new tests, all failing against the current implementation`

followed by a table mapping each new test to the numbered hole it closes.
