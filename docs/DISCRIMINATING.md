# Discriminating-test gate

`bin/verify-discriminating.sh` evaluates changed test files in a temporary
worktree at `HEAD`.  It reverses only the diff hunks for non-test files, then
runs every detected test.  A passing test is rejected; a failing test is
accepted unless its output shows an import failure, which is an import
confound rather than behavioural evidence.

The gate detects `*.bats`, `test_*.py`, `*_test.py`, and `test_*.sh`, including
rename-plus-edit changes.  Symlinked test files and a branch with no changed
tests fail loudly.  Every changed non-test file is reported as an
implementation hunk scheduled for reversal; code-shaped files outside the
detection globs are additionally reported as unrecognised.

Landing invokes the check when `VERIFY_DISCRIMINATING_BASE` identifies the
PR's base ref.  This keeps the mechanism branch-aware: after a change is
already landed, there are correctly no new tests relative to that checkout.
