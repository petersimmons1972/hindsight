# C6 — Vendor / sync to consumers

## Context

`conf/consumers.conf` lists the 12 repos that should receive the failure-mode floor.
Seven of them (fleet, claude-codex, codex, spark, duramind, kubernetes, generals) held
failure-mode artifacts while being outside the sync mechanism entirely — which is how
the canonical standard forked into two diverging copies in the first place. Distribution
is what stops that recurring.

## Files
- **Rework** `bin/sync-failure-modes.sh` (currently inherited from homelab-config and
  written for a 5-repo world with different paths).
- **Create** `bin/tests/test_sync.sh`.

## Behaviour
For each `<abs-path>:<remote-fragment>` in `conf/consumers.conf`:
1. Verify the path exists and is a git repo. Skip-with-loud-warning if not.
2. **Verify the repo's `origin` remote matches the expected fragment. On mismatch,
   REFUSE that repo** — do not write. Writing the fleet floor into an unexpected repo is
   the kind of blast-radius mistake that is hard to undo.
3. Vendor the canonical catalog to a well-known path in the consumer, with a
   `GENERATED — DO NOT EDIT, canonical source is hindsight` header.
4. Never commit or push in the consumer repo. Write files only; leave the diff for a
   human or a later dispatch.

**`--dry-run` is the DEFAULT.** Writing requires an explicit `--apply`. Report a clear
per-repo table: would-write / up-to-date / refused-mismatch / skipped-not-a-repo.

Note: `infrastructure` currently has no `origin` remote — it must land in
`skipped`/`refused`, not crash the run, and the summary must say so.

## Acceptance (TDD)
Gate: `bash bin/tests/test_sync.sh`
- Build throwaway git repos in a temp dir; assert dry-run writes nothing at all.
- `--apply` writes the expected file with the GENERATED header.
- A repo whose origin does not match its conf fragment is REFUSED and unwritten.
- A path that is not a git repo is skipped with a warning, run continues, exit 0.
- Re-running `--apply` is idempotent (no spurious diff).
- Nothing is ever committed or pushed in a consumer repo — assert the consumer's
  git status and HEAD are unchanged after `--apply`.

## Constraints
Bash, `set -euo pipefail`. No network in tests — local temp repos only. Never read an
exit status through a pipe.

## Out of scope
Actually running the sync against the real 12 repos (coordinator does that in Wave 5).
Decommissioning claude-codex's mirror.

## Model
`--harness codex --effort medium`.
