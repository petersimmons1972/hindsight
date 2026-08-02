VERDICT: DEFECTIVE

Baseline confirmed first: `bash bin/tests/test_similar_causes.sh` → `=== summary: 27 passed, 0 failed (of 27) ===`. Clone left untouched (`git status --short` empty); all fixtures were built under `/tmp/pv1`, outside the repo. Tool under test: `/home/psimmons/.claude/jobs/2c17b6f5/tmp/p_opus/bin/similar-causes.py`.

---

**1. HIGH — Exit status becomes a function of "was a match found", reconstructing the cancelled rejection guard. An unhandled `UnicodeEncodeError` fires while printing a candidate row, so the same corpus exits 1 on a matching query and 0 on a non-matching one.**

The candidate row is printed with a bare `print()` (line 151) and nothing guards stdout's encoding. The **default repo corpus** is full of non-ASCII (`±`, `σ`, `—`), so any stdout encoding that is not UTF-8 turns "found a candidate" into a non-zero exit.

Reproduced against the real `pipeline/L1` corpus, no fixture:

```
$ cd /home/psimmons/.claude/jobs/2c17b6f5/tmp/p_opus
$ PYTHONIOENCODING=ascii python3 bin/similar-causes.py "estimand invalidation determinism campaign" >/tmp/pv1/o1 2>/tmp/pv1/e1; echo "EXIT=$?"
EXIT=1
$ tail -3 /tmp/pv1/e1
    print(f"{value:.3f} | {record.identifier} | source: {record.source} | {record.instance}")
    ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
UnicodeEncodeError: 'ascii' codec can't encode character '\xb1' in position 89: ordinal not in range(128)

$ PYTHONIOENCODING=ascii python3 bin/similar-causes.py "zzzqqq wwwvvv" >/tmp/pv1/o2 2>/tmp/pv1/e2; echo "EXIT=$?"; cat /tmp/pv1/o2
EXIT=0
Candidates for human review. This tool does not determine duplication.
```

Same binary, same corpus, same env: **match → exit 1, no match → exit 0.** Any wrapper (CI step, cron, systemd unit, `set -e` script) that sets a non-UTF-8 stdout encoding gets a working duplicate-rejection guard for free — precisely the thing that was deliberately cancelled. Note `LC_ALL=C` alone does *not* reproduce (PEP 538 coerces it to C.UTF-8), which is why this is invisible to a locale-only test.

Second-order damage in the same run: stdout was truncated to the header only —
```
$ cat -A /tmp/pv1/o1
Candidates for human review. This tool does not determine duplication.$
```
so the candidate list is silently cut off mid-print with no truncation disclosure, and the human sees "zero candidates" on stdout while the process dies.

The same crash is reachable under a normal UTF-8 environment via a corpus record containing a lone surrogate (valid JSON, `json.loads` accepts it):

```
$ python3 bin/similar-causes.py --corpus /tmp/pv1/c1 "widget failure in the cache layer"; echo "EXIT=$?"
Candidates for human review. This tool does not determine duplication.
1.000 | a-1 | source: x.md | widget failure in the cache layer
Traceback (most recent call last):
  ...
  File ".../bin/similar-causes.py", line 151, in main
    print(f"{value:.3f} | {record.identifier} | source: {record.source} | {record.instance}")
UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position 29: surrogates not allowed
EXIT=1
$ python3 bin/similar-causes.py --corpus /tmp/pv1/c1 "zzzzz qqqqq"; echo "EXIT=$?"
Candidates for human review. This tool does not determine duplication.
EXIT=0
```

Why the suite misses it: T13/T14 exercise non-ASCII *queries*, never a non-ASCII *record on the print path* under a hostile stdout encoding; T23's no-traceback assertion is scoped to malformed JSONL only.

---

**2. HIGH — Corpus fields are printed raw, so a single record can inject additional output lines: verdict language, a fabricated truncation count, and ANSI escapes that erase the mandatory header.**

`instance`, `id`, and `source_path` go straight into the f-string. A JSON string may legally contain `\n` and `\u001b`.

Verdict + false truncation injection:
```
$ python3 bin/similar-causes.py --corpus /tmp/pv1/c2 "cache eviction storm"; echo "EXIT=$?"
Candidates for human review. This tool does not determine duplication.
0.500 | b-2 | source: y.md | cache eviction storm benign second row
0.214 | b-1 | source: y.md | cache eviction storm
VERDICT: DUPLICATE of b-1 — submission rejected.
Showing 10 of 4212 candidates.
EXIT=0
```
Two candidates matched; the output asserts a duplication verdict and claims 4212 candidates were truncated. Both lines are corpus text, indistinguishable from tool output.

Header erasure via ANSI (`ESC[2J ESC[H` = clear screen, home cursor):
```
$ python3 bin/similar-causes.py --corpus /tmp/pv1/c3 "token bucket refill stall" > /tmp/pv1/o3 2>&1; echo "EXIT=$?"; cat -v /tmp/pv1/o3
EXIT=0
Candidates for human review. This tool does not determine duplication.
0.267 | z-1 | source: z.md | ^[[2J^[[H^[[1;31mREJECTED: duplicate of z-1. Do not file.^[[0m
token bucket refill stall
```
On a terminal the human sees a red "REJECTED: duplicate of z-1. Do not file." at the top of a cleared screen and **no header at all** — the one line the contract says must appear unconditionally is wiped by the tool's own output.

Scope, stated honestly: I verified the live corpus is currently clean — 475 records across `pipeline/L1/*.jsonl`, **0** with an embedded `\n`/`\r`. So this is not firing today; it is an unguarded path in a corpus that is machine-generated by an upstream extraction pipeline from repo docs. T04's verdict-language scan only ever reads fixtures the suite itself authored, so it can never catch record-sourced verdict text.

---

**3. MEDIUM — Caller-controlled `--corpus` text is echoed verbatim on the error path with a non-zero exit, producing a rejection verdict on stderr. The implementer explicitly blocked this for unknown options and left it open here.**

Lines 125–127 carry the comment *"Do not repeat arbitrary caller-controlled option text. In particular, a guard-shaped unknown option must not look like a tool verdict."* The `--corpus` value gets no such treatment (lines 60/62/64/71/106/141):

```
$ python3 bin/similar-causes.py --corpus "/tmp/pv1/DUPLICATE - submission REJECTED, matches FM-161" "quorum loss"; echo "EXIT=$?"
Error: Corpus path does not exist: /tmp/pv1/DUPLICATE - submission REJECTED, matches FM-161
EXIT=1
```

A wrapper that chooses the `--corpus` argument gets `exit 1` plus verdict-shaped text on stderr — the same guard shape the unknown-option handler was written to prevent. T21 probes guard-shaped *flags*, never a guard-shaped *path value*.

---

**4. MEDIUM — A corpus line that fails to parse is dropped silently, so an incomplete lookup is reported as a clean "no candidates" answer.**

Fixture: two records, the first (the only one matching the query) has a trailing-comma JSON error.
```
$ printf '{"id":"g-1","source_path":"g.md","instance":"quorum loss during rolling restart",}\n{"id":"g-2","source_path":"g.md","instance":"unrelated topic about fonts"}\n' > /tmp/pv1/c4/g.jsonl
$ python3 bin/similar-causes.py --corpus /tmp/pv1/c4 "quorum loss during rolling restart"; echo "EXIT=$?"
Candidates for human review. This tool does not determine duplication.
EXIT=0
```
The corpus contains a near-verbatim match. The tool reports zero candidates, exit 0, and emits nothing on stderr about the dropped line. The human's only legitimate reading of that output is "nothing similar is on file" — a wrong result presented as a right one. T23 permits skip-bad-lines but never requires the skip be disclosed; a one-line stderr note ("skipped N unparseable lines in g.jsonl") would close it without changing the exit code.

---

Not filed, per scope: ranking/recall behavior. Notes on things I checked that were **clean** — query text is never echoed into stdout (the anti-echo intent holds on the success path); `>10` truncation disclosure is present and correctly counted; the header is byte-exact; a punctuation-only query (`"!!!"`) yields exit 0 with no division-by-zero; `head -1` piping produced no BrokenPipe stderr noise; multi-word leading-dash queries (`"-- cache eviction storm"`) parse correctly as positionals.

Not reached within the tool-call cap: I did not test non-UTF-8 *locale* variants beyond `LC_ALL=C` (no alternate locales installed to verify), did not syscall-trace to independently confirm the read-only claim beyond the suite's hash checks, and did not test corpus files that are FIFOs or symlinks outside the corpus directory.