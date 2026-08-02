# E1 stage 2c — sanitize tool output (2 failing tests)

You are the implementer. The hardened 37-test acceptance suite is in the tree and **35 of 37
pass**. Two fail, both from the same root cause. Fix that cause; change nothing else.

```
bash bin/tests/test_similar_causes.sh
FAIL: T32 terminal-rendered output keeps advisory header despite ANSI in corpus
FAIL: T34 multiline-forged instance cannot exceed cap or invert scores
```

## The root cause

`record.instance`, `record.identifier` and `record.source` are interpolated straight into stdout
with no sanitization. A single corpus record therefore controls the shape of the output:

- **ANSI control sequences.** A record containing `ESC[2J ESC[H` (erase display, cursor home)
  wipes the mandated advisory header that was printed one line earlier, and a forged header plus
  `VERDICT: DUPLICATE ... rejected as duplicate` is what the terminal actually displays. The byte
  stream still contains the real header, which is why a `grep -Fxq` check saw nothing wrong.
- **Newlines.** A record whose `instance` contains newlines forges extra candidate rows that are
  byte-identical in shape to tool-authored ones: 15 scored rows against a stated cap of 10, scores
  *increasing* down the page, no truncation notice, and fabricated provenance pointing at
  `catalog/failure-modes.md`.

This matters because the tool's entire contract is that it does not render a duplication verdict.
Corpus text that can forge one defeats the contract without touching a line of the logic.

## What to do

Sanitize every corpus-derived field on the way out, so that no field can introduce a line break, a
control character, or an escape sequence into the output. One candidate record must produce exactly
one output line. Keep the text readable — escape or replace, do not silently truncate the content
to nothing.

## Constraints

- **Do not modify `bin/tests/test_similar_causes.sh` or `bin/tests/fixtures/similar-causes/`.**
  Both are in the dispatch protect-set; touching them aborts your run. Extra tests go in
  `bin/tests/test_similar_causes_extra.sh`.
- **Never modify `pipeline/L1/` or `catalog/`.**
- Standard library only (PEP 668: `pip install --user` fails on the runner).
- Read-only at runtime: no writes, caches or sidecars.
- Preserve everything already fixed and passing: `utf-8-sig` BOM handling, the skipped-record count
  on stderr, `backslashreplace` output encoding, broken-pipe handling, the unconditional advisory
  header, the exact cap of 10 and its truncation disclosure, and — above all — **exit status must
  never distinguish "match found" from "no match"** under any encoding, corpus content or pipe.

## Verify and quote the literal output

```bash
bash bin/tests/test_similar_causes.sh                          # must be 37 passed, 0 failed
PYTHONIOENCODING=ascii bash bin/tests/test_similar_causes.sh    # must also be 37 passed
git diff --stat -- bin/tests/                                   # additions only
```

Then mutation-test your fix: re-introduce raw interpolation for each field in turn and confirm T32
and T34 fail each time. Report any mutant that survives.

**Cap: 40 tool calls.**

First line of your summary, literally one of:
`REPAIR COMPLETE: 37/37 passing, 0 existing tests modified`
`REPAIR INCOMPLETE: <n>/37 passing`
