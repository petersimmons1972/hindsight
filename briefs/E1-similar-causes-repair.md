# E1 stage 2b — REPAIR `bin/similar-causes.py` against the hardened spec

**You are the implementer again.** You wrote `bin/similar-causes.py` and it passed all 27 tests of
the attack spec first time. Three independent stage-3 verifiers then attacked it and **all three
returned DEFECTIVE**. The adversary has since hardened the suite; your job is to make the hardened
suite pass.

Read `QA-PROTOCOL.md` first. The full verifier output, with exact reproductions, is committed at
`qa-ledger/e1/stage3-verifier-output.txt`. Read it before you change anything.

**Important context so you calibrate correctly:** the mutation verifier's own summary was *"the
implementation as committed is correct; the defect is that the suite does not hold it there."* Most
of what follows is not sloppiness on your part — it is the suite having been too weak to force the
right thing. Two of the findings, however, are real bugs in your code (H1 and H2 below), and one is
a real silence bug (H5).

## The rule that has not changed

**You may add tests. You may not weaken, delete, skip, relax or exempt an existing one.** The spec
is in the dispatch protect-set; modifying it aborts your run. Additional tests go in
`bin/tests/test_similar_causes_extra.sh`.

If you believe a test is genuinely wrong, leave it failing and say so with your reasoning. A test
you cannot satisfy is information. A test quietly edited is a manufactured green, and a PR was
already closed unmerged in this repo for exactly that.

## What must be fixed

### H1 — the exit code must NEVER discriminate "match found" from "no match"

This is the whole point of the packet and it was defeated twice on the default corpus path.

1. **Uncaught `UnicodeEncodeError`.** `print()` of a candidate row raises when stdout's codec cannot
   encode the text, and that only ever happens on the match path. Reproduced with
   `PYTHONIOENCODING=ascii` against the real corpus (which contains em dashes) — match exits 1,
   no-match exits 0. Also reproduced with **no environment variable at all** when a record's
   `instance` contains a lone surrogate (legal JSON, accepted by `json.loads`).
2. **`| head -1` exits 120 on match, 0 on no-match.** Your `except BrokenPipeError: raise
   SystemExit(1)` is dead code — the error fires while flushing `sys.stdout` during interpreter
   shutdown, outside the `try`. A verifier built a working duplicate-guard on top of this in two
   lines of shell.

Fix the **property**, not just these two mechanisms: no invocation may reveal match-vs-no-match
through exit status, under any encoding, any corpus content, or any downstream pipe. Make output
encoding-safe rather than encoding-dependent, and handle the broken-pipe case where it actually
occurs, not where it looked like it would.

### H2 — corpus text reaches stdout unsanitized

`record.instance`, `record.identifier` and `record.source` are interpolated straight into stdout.
Consequences, both reproduced:

- A record containing `ESC[2J ESC[H` **erases the mandated header** and puts a forged header plus
  `VERDICT: DUPLICATE ... rejected as duplicate` on screen. The byte stream still contains the real
  header, so `grep -Fxq` sees nothing wrong — but a terminal displays a duplication verdict.
- A record containing newlines forges extra candidate rows: **15 scored rows against a stated cap of
  10**, scores *increasing* down the page, no truncation notice, fabricated provenance pointing at
  `catalog/failure-modes.md`.

No field may introduce a line break or a control sequence into the output. Sanitize on the way out.

### H3 — the cap and the truncation count must be exact

The cap is 10, and the disclosed total must be the **true** number of candidates, not any number.

### H4 — match semantics must hold on the DEFAULT corpus, not only fixtures

A mutant adding a full duplicate-guard **only when `--corpus` is absent** passed 27/27, because
every match test used a fixture corpus. Whatever you do must be identical on both paths.

### H5 — silent partial corpus load (a real bug)

`load_records()` guards only the *total* zero case; individual unparseable records are dropped with
a bare `continue`. Reproduced: **309 of 475 records (65%) dropped with zero bytes on stderr**, output
one candidate different from healthy. Separately, a **UTF-8 BOM silently discards the first record**
of every file it prefixes.

Skipping bad lines is acceptable. The **silence** is not. Emit a count of loaded and skipped records
to stderr whenever anything was skipped, keep exit 0 for that case, and read files in a way that
tolerates a BOM. Note the distinction the contract already draws: an empty or unreadable corpus
fails loud; a populated corpus with no similar entries is a legitimate exit 0. Do not collapse them.

## Constraints (unchanged)

- Standard library only. `pip install --user` fails on the runner with `externally-managed-
  environment` (PEP 668).
- **Never modify `pipeline/L1/` or `catalog/`.** Both are protected at dispatch time.
- Read-only at runtime: no writes, caches or sidecars.
- No `--threshold`, `--reject`, `--check-duplicate` or equivalent. The rejection semantics were
  cancelled by measurement and are not coming back through an option.

## Verification you must actually run, and quote

```bash
bash bin/tests/test_similar_causes.sh                    # every test, including the new ones
bash bin/tests/test_similar_causes_extra.sh              # if you add one
git diff --stat origin/main -- bin/tests/                # additions only to the protected spec
PYTHONIOENCODING=ascii bash bin/tests/test_similar_causes.sh   # H1: must still be green
```

Then mutation-test yourself: re-apply the four vectors above as mutants and confirm the hardened
suite kills each. **Report any mutant that survives** — a surviving mutant is a remaining hole, and
reporting it is worth more than hiding it.

## Budget

**Cap: 70 tool calls.** If you hit it, stop and say exactly what is unfinished.

## Deliverable

First line, literally one of:

`REPAIR COMPLETE: <n>/<n> passing, 0 existing tests modified`
`REPAIR INCOMPLETE: <n>/<m> passing` — with which tests fail and why.
