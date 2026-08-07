# Discriminating-test gate (supported-shape)

`bin/verify-discriminating.sh` implements the founder-ruled **supported-shape**
gate for hindsight#23 (plan 07).

## Contract

1. **Enumerate shapes.** Only `*.bats`, `test_*.py`, and `*_test.py` are
   candidates. Unstructured `test_*.sh` and symlinked tests are **refused**.
2. **Refuse added-module tests.** A Python test that imports a module present
   on `HEAD` but absent at the merge-base is `UNSUPPORTED_SHAPE:added-module`
   — never certified (PR #48 class).
3. **Certify only behavioral reds.** For supported tests, reverse non-test
   implementation hunks at `HEAD` (never merge-base-copy the tests), run the
   test, and require a **behavioral** failure. Import/syntax failures after
   reversion are not certified.
4. **No silent 0/0.** Zero changed tests ⇒ exit 1.
5. **Called from land.** When `VERIFY_DISCRIMINATING_BASE` is set, `bin/land.sh`
   runs this gate before the CI rollup gate.

## Usage

```bash
# Local / PR land (base is the PR base ref, usually main)
VERIFY_DISCRIMINATING_BASE=main bin/land.sh <pr> --merge   # land invokes gate
bin/verify-discriminating.sh --base main                   # direct
```

## Non-goals

- Universal discrimination of every possible TDD shape (explicitly rejected).
- Merge-base worktree copies of tests (disqualified by measurement).
- Workflow edits (wiring is land/env only).
