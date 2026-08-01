# C6b — Sync batch resilience (REPAIR)

## Context

`bin/sync-failure-modes.sh` (PR #2) passed its gate and a cross-vendor review REPRODUCED a
defect that the gate cannot see.

`bin/sync-failure-modes.sh:85` runs a bare `mkdir -p "$repo/docs"` inside the per-repo loop
under `set -euo pipefail`. If it fails for ANY single consumer — `docs` already exists as a
regular file, or a permission error on that one repo — bash kills the ENTIRE script. Every
consumer later in `conf/consumers.conf` is never attempted, and the summary table shows no
row for them at all: just a raw `mkdir:` error on stderr and process death.

Reproduced by the reviewer: two temp repos, the second with `docs` pre-existing as a regular
file. The first synced; the second aborted the whole run, leaving the rest of the list
untouched with no indication they were skipped.

This is silent truncation of a fleet-wide write, in the tool built to distribute the
failure-mode floor. A caller reads a partial run as a complete one. `mv -f ... "$destination"`
at line 98 has the identical exposure if `docs/failure-modes.md` is a directory in some
consumer.

The gate passed because the tests construct only the two failure cases the brief named
(not-a-git-repo, remote mismatch) and never a WRITE-TIME failure.

## Files
- **Modify** `bin/sync-failure-modes.sh`, `bin/tests/test_sync.sh`.

## Required changes

1. **No single consumer may abort the batch.** Every per-repo filesystem operation that can
   fail must be guarded so failure is contained to that repo's iteration. Give it a distinct
   status — e.g. `failed-write` — alongside the existing would-write / up-to-date /
   refused-mismatch / skipped-not-a-repo.

2. **The summary must account for EVERY repo in the conf, always.** A consumer that was
   never reached, or failed, must appear in the table with its reason. A row silently
   missing from a summary is indistinguishable from a row that succeeded, which is the
   defect being fixed.

3. **Exit code must reflect partial failure.** A run where some consumers failed exits
   non-zero, having still attempted all the others. Do not swallow the failure and exit 0,
   and do not abort early. Both are worse than reporting honestly.

4. **Preserve everything the review confirmed correct** — `--dry-run` default, mismatch
   refusal, no commit/push in consumers, the TOCTOU/symlink-escape hardening on the write
   path, and idempotency. Do not regress these while fixing the loop.

5. Minor, fix while you are here: `origin_fragment()` recognises only `git@github.com:`,
   `https://github.com/`, `ssh://git@github.com/`. Any other well-formed origin falls into
   `refused-mismatch`. It fails closed so it is not a safety issue, but give it a distinct
   `unrecognized-origin` status so a nuisance is not misread as a mismatch.

## Acceptance (TDD)
Gate: `bash bin/tests/test_sync.sh`

Add tests that FAIL against the current implementation:
- A consumer whose `docs` exists as a regular file: that repo reports `failed-write`, and
  **every subsequent consumer in the list is still attempted** — assert the later repo was
  actually written.
- A consumer whose `docs/failure-modes.md` is a directory: same containment.
- Assert the summary lists all conf entries, with a reason for each.
- Assert overall exit is non-zero when any consumer failed, and that the successful ones
  were still written.
- Keep every existing test passing; do not weaken one to fit.

## Constraints
Bash, `set -euo pipefail` retained — contain failures explicitly rather than by disabling
`set -e` globally. Temp repos only in tests, never a real consumer. No exit status read
through a pipe (CI-17).

## Model
`--harness codex --effort high`. Blast radius is 12 repositories.
