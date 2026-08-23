# hindsight

The cross-repo failure-mode registry. One catalog, one guard, one distribution
channel — for every repo in the fleet.

## Why this repo exists

Failure modes were catalogued in ~15 repos in ~9 incompatible schemas, and the
canonical standard had **forked into two diverging copies** (homelab-config and
claude-codex). It forked because neither repo was its natural owner: one is a
homelab-infra repo, the other an integration repo. A fleet-wide governance
artifact sat awkwardly in both, so both kept a copy and drifted.

Picking a winner between them would have fixed the symptom and left the cause.
This repo is the neutral owner, so the fork pressure is gone and the dependency
direction is right: twelve repos consume from here; this repo depends on none of
them.

## The problem it is built to solve

Writing a failure mode down does not stop it recurring. Measured across the
fleet corpus:

| Root cause | Times independently re-logged |
|---|---|
| Trust the completion/exit signal | ≥7 in three weeks |
| Shared mutable checkout corrupts concurrent agents | 7 |
| Fail-silent gate (error ≡ reject) | 4 |
| Dedup identity-key | 3, on the same file |

The catalog grew; the failure rate did not drop. The registry was a diary, not a
gate — nothing could tell you the corpus *already knew* something. Closing that
hole is this repo's actual job.

The catalog demonstrates the problem on itself: **FM-32** documents "non-unique
failure-mode catalog IDs" and even specifies the check that would catch it. It
was never implemented, and a duplicate `FM-28` sat in the catalog until
2026-08-01. Worse, the check as written (`grep -oP 'FM-\d+' | sort | uniq -d`)
matches cross-references in prose and reports ~36 false positives — had anyone
implemented it verbatim, it would have been disabled as noise.

## Layout

```
catalog/failure-modes.md   canonical catalog — 145 rows, the only source of truth
guard/                     the guard + its contract tests
bin/                       add-failure-mode, sync, render tooling
conf/consumers.conf        the 12 repos that receive the floor
pipeline/                  L0 manifest → L1 extraction → L2 clusters → L3 invariants
```

## Guard contract

`guard/failure_mode_catalog_guard.py` runs from `.githooks/pre-commit` and CI.

| Rule | Severity | Rationale |
|---|---|---|
| Duplicate canonical ID | **error** | The load-bearing invariant. Ambiguous IDs break every cross-reference. |
| Legacy scheme (`FM-RC-*`, `FM-REC-*`) **as a row ID** | **error** | Non-canonical identity. |
| Legacy scheme as a *provenance annotation* | allowed | `Container Runtime — Design (FM-RC-01)` is a breadcrumb, not a defect. |
| Rows out of numeric order | warning | Cosmetic. The catalog is multi-section and curated; fatal enforcement would force a destructive re-sort or block every append. A guard that makes you damage the document gets disabled. |

Install once per clone: `bin/install-hooks.sh`

The installer stores the literal local value `core.hooksPath=.githooks` in the
shared repository config. Git resolves that relative path from whichever
worktree is active, so a linked worktree runs the hook version checked out in
that worktree rather than a possibly stale hook from a sibling checkout. Both
hooks also fail loudly if an absolute path later selects a sibling's copy.

This is a breaking change in the hook trust model: the active branch controls the hook bytes
and can modify or delete them. These hooks are an accident tripwire, not a security or merge gate.
`--no-verify`, an uninstalled clone, a deliberately altered hook, and a new worktree created from an older revision
that lacks `.githooks/` all remain bypasses. Authoritative enforcement belongs outside
branch-controlled hooks, such as required CI and the merge gate.

Because `core.hooksPath` is shared clone configuration, the installer first
requires every currently registered worktree to contain executable, non-symlink
hooks and the worktree verifier. Its final operation is Git's atomic config
write; it performs no fallible work after that write. Re-run the installer after
adding a worktree so the inventory is checked again. A worktree added later from
an older revision can otherwise lack the branch-controlled tripwire entirely.

## Adding an entry

Use `bin/add-failure-mode.sh` (or `.py`); do not hand-edit IDs. The next ID comes
from `guard/failure_mode_catalog_guard.py --next-id`.

## Provenance note

Rows `FM-135..FM-145` were previously `FM-REC-01..11`. They carried a
non-canonical ID scheme, and the claude-codex fork resolved that by **deleting
them** — 11 real reconciler failure modes (lease ABA, TOCTOU reap, silent
403-release) lost. They were recovered from the homelab-config copy on
2026-08-01 and renumbered with their original IDs preserved as annotations.
`guard/tests/` pins them so it cannot happen twice.

## Status

Phase 0 (canon consolidation) complete. Phases 1–6 — extraction, mechanical
recurrence measurement, family and global synthesis, enforcement conversion, and
the duplicate-root-cause check — are tracked in the project plan.
