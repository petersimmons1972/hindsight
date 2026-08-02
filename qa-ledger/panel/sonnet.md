Repo is clean (all test files were in /tmp, outside the clone). Final verdict below.

VERDICT: DEFECTIVE

1. **Severity: HIGH** — `-h` / `--help` (and any unambiguous abbreviation of it, e.g. `--hel`, `--h`) bypass the tool entirely: argparse's built-in help intercepts before the corpus is even loaded, so the mandatory header never prints, no lookup happens, and the process exits **0**. This directly breaks the stated contract "It must print, verbatim and unconditionally, the header ... " — exit 0 with no header is exactly the case the contract calls out as forbidden, and here it's trivially reachable because the entry point never carves out an exception for argparse's default `-h`/`--help`.

   Reproducing commands:
   ```
   $ python3 bin/similar-causes.py --corpus /tmp/qa_corpus -h ; echo exit=$?
   ```
   Output: full argparse usage/help block, **no** "Candidates for human review..." line, `exit=0`.
   ```
   $ python3 bin/similar-causes.py --corpus /tmp/qa_corpus --help ; echo exit=$?
   ```
   Same result: help text, no header, `exit=0`.
   Confirmed the header is genuinely absent (not just visually missed):
   ```
   $ python3 bin/similar-causes.py --corpus /tmp/qa_corpus -h >/tmp/help_out.txt 2>&1; echo exit=$?
   exit=0
   $ grep -c "Candidates for human review" /tmp/help_out.txt
   0
   ```
   The acceptance suite (27 tests) never exercises `-h`/`--help`, so this gap is untested.

2. **Severity: LOW (usability/robustness gap, not a contract breach)** — `argparse` is constructed with default `allow_abbrev=True`, so a free-text query that happens to be an exact unambiguous prefix of `--corpus` (`--c`, `--co`, `--cor`, `--corp`, `--corpu`) is swallowed as an attempt to set the `--corpus` option rather than treated as query text, producing a usage error instead of a lookup:
   ```
   $ python3 bin/similar-causes.py --corpus /tmp/qa_corpus --corp ; echo exit=$?
   usage: similar-causes.py [-h] [--corpus CORPUS] query
   similar-causes.py: error: argument --corpus: expected one argument
   exit=2
   ```
   This falls inside the contract's tolerated "bad usage" exit bucket (the tool doesn't fabricate a wrong duplicate/no-duplicate answer, it just refuses to run), so I'm not calling it a contract violation on its own — but it's a real robustness edge the suite doesn't cover, and the fix (either `allow_abbrev=False` or documenting a `--` separator requirement) is cheap. Using `--` correctly avoids it: `python3 bin/similar-causes.py --corpus DIR -- --corp` runs the lookup normally (verified, exit 0, header printed).

Everything else checked and found sound (no reproducible defect):
- Exit-0-on-match guarantee holds even when the query itself is a threshold/reject/guard-shaped flag (`--threshold=0.01`, `--fail-on-match`, `--guard`, etc.) — matches the suite's T21 intent; I additionally confirmed with flags not in the suite's list.
- No traceback, no non-zero exit, and header still prints for zero-width/invisible-whitespace-only and non-ASCII queries.
- No filesystem writes anywhere under the clone during any run (`git status --porcelain` clean before/after; no stray `__pycache__`).
- `readable()`'s combined stat-bits + `os.access` check correctly refuses root-bypass scenarios per the existing T07 test design.
- Truncation disclosure, header-unconditional-with-candidates, and non-increasing score ordering all held under my own ad hoc probes, consistent with the suite's own T16/T17/T22/T24.

I did not evaluate ranking/recall quality (explicitly out of scope) and did not attempt to construct an actual TOCTOU delete-between-stat-and-open race (would require instrumenting the interpreter mid-run; flagging as an untested hypothesis, not a finding, since I couldn't reproduce it with a plain command).