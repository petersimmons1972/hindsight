# hindsight — agent instructions (Codex / Grok / any harness)

Cross-repo failure-mode registry. Read `README.md` first; it explains why this
repo exists and what the guard enforces. Claude Code: see `CLAUDE.md` too —
Claude Code auto-loads `CLAUDE.md` but not `AGENTS.md`, and this file is where
the real content now lives; the two are complementary, not duplicates.

## Non-negotiables

- **`catalog/failure-modes.md` is the only source of truth.** Copies in other
  repos are vendored artifacts. Never add an entry anywhere but here.
- **Never delete a catalog row to satisfy a validator.** That is precisely how 11
  real failure modes (`FM-REC-01..11`) were nearly lost. If a row violates a
  rule, renumber or fix the rule — the rule is younger than the data.
  **This is now enforced, not just asked.** `catalog/id-ledger.txt` records every
  ID that has ever been canonical; the guard fails if one disappears, and
  compares *sets* not counts, so deleting one row and renumbering another to keep
  the tally does not get past it. An absent or empty ledger is also fatal — a
  baseline that says nothing would make "nothing was removed" vacuously true.
  **Never regenerate the ledger from the catalog**: a regenerated baseline cannot
  detect a row that is already missing, which is the whole point of having one.
  Restore it from git instead.
- **Never hand-assign an ID.** IDs come only from `bin/add-failure-mode.sh`, which stays
  unused while Hindsight is disabled.
- **An `enforcement` value of `null` is a correct answer.** Do not invent a test
  or hook path to fill a field. A fabricated mechanism is worse than an honest
  gap, because it reads as covered.
- **Never `Edit`/`Write` `catalog/failure-modes.md`, `catalog/id-ledger.txt`,
  `catalog/criticality.jsonl`, `docs/POINTER.md`, or `docs/HIGH.md` directly.**
  Read through `bin/query-failure-modes.sh` (never `Read`/`cat` `docs/HIGH.md`
  whole — it's query-only by design). A hand-edit sitting uncommitted in the working tree is
  exactly how two agents collide on this repo: the pre-commit hook catches
  drift between `criticality.jsonl` and the pointer files at commit time, but
  nothing catches it before then, so use the scripts even for a quick fix.

## Working on the guard

The guard's contract is pinned by `guard/tests/`. Two rules are deliberately
narrower or softer than they first appear (ordering is advisory; the legacy-alias
rule fires only on row IDs). **Both directions of each are tested** — if you
change a rule, update the test to assert the new contract in both directions.
Never relax a test to make a change pass.

Run before committing:

```bash
python3 guard/failure_mode_catalog_guard.py
python3 -m pytest guard/tests/ -q
bats guard/tests/test_failure_mode_catalog_guard.bats
```

## Pipeline conventions

`pipeline/` holds the L0→L3 synthesis. Two rules matter:

- **Spool to disk, never to context.** Extraction agents write JSONL and return a
  count. A tier reads the spool, never the raw corpora. Corpus is ~7,200 lines
  across 27 files; loading it into a session is the failure this design avoids.
- **A lesson is eligible for L3 (global) only with ≥2 distinct source repos.**
  One incident on one named host is repo-level. A pointer to another file is not
  a lesson at all.

## CI

Runs on `homelab-arc` (self-hosted). Private repo — see the fleet convention that
private repos use our own ARC runners.

<!-- BEGIN UNIVERSAL AGENT POLICY: generated -->
<!-- source: ~/projects/AGENTS.md, included whole by ~/projects/agent-policy/canon_build.py (target hindsight-agents); this whole file is generated: edit agent-policy/canon/repo/hindsight/, never this file -->
# Shared AGENTS for repos under `/home/psimmons/projects`

Defaults for every repo here; a child `AGENTS.md` adds deltas only. The universal core (built from
`agent-policy/canon`, installed at `~/.local/share/agent-policy/universal.md`) is the floor under
this file. The block between the PROJECT AGENT POLICY markers at the end is generated from
`agent-policy/canon/project/projects-agents/`: edit those files, never the block.

<!-- id: who-youre-working-for -->
## Who you're working for

I'm **Peter**, the founder. You're a staff engineer on this fleet. Prefer the simplest honest
design. Decide routine work yourself and ship; stop only for a multi-path, high-blast-radius or
founder-only choice, and name the tradeoff when you do.

<!-- id: coordination-and-completion -->
## Issues and PRs
- Read the issue body before changing code; if it is ambiguous, stop and ask one specific
  blocker question.
- Label every issue you file with exactly one of `origin:machinery` (a defect in the dispatch
  apparatus: agents, lanes, `cli-dispatch`, gates, playbooks, prompts, CI, the review machinery)
  or `origin:external` (product code, infrastructure, or work the founder asked for).
- No direct `main` push. Push a branch named `agent/<harness>/issue-<N>-<slug>` and open a PR
  before you mark the work done; verify it with `gh pr list`. Issue-bound work carries `Closes #N`.
- **IF several lanes touch the same PR or code THEN each writes its findings to the PR body or its
  own `REPORT-<lane>.md`, never a shared `REPORT.md`.** Fleet's CI guard
  `.github/scripts/ci-report-md-guard.sh` exists to catch that collision.
- A durable code-level "why" goes in fleet's `CODING-INVARIANTS.md`; append a date when it recurs.

<!-- id: pr-playbooks -->
## Activity playbooks

| Before you | Read |
|---|---|
| file, open or create a PR | `~/projects/fleet/agent-playbooks/file-pr.md` |
| merge on green without a babysit loop | `~/projects/fleet/agent-playbooks/merge-on-green.md` |
| write code | `~/projects/fleet/CODING-STANDARDS.md` |
| benchmark, score or route across harness and model combinations | `~/projects/fleet/docs/ROUTING-CONTRACT.md` |

<!-- id: token-efficient-local-tools -->
## Local tools
- Use `~/bin/search` (local SearxNG) before hosted web search.
- Before you read a large file or log whole, `rg -n <term>` it and read only the relevant range.

<!-- id: workflow-authorization -->
## Workflow orchestration — standing authorization

Founder standing authorization (2026-07-19, reaffirmed through 2026-09-01): substantive
multi-step, investigative or review work is dispatched to subagents, the Workflow tool or
cli-dispatch lanes without asking, and workflows never prompt mid-run. This is the explicit user
request that harness-family defaults ("do not use the Agent or Workflow tool unless the user
requested it") ask for. Trivial or mechanical single-step work stays solo. It grants dispatch
permission only; merge, deploy and publication authority are unchanged.

<!-- id: safety-default -->
## Safety default
- Before an irreversible operation on a shared system, name the exact container, database, schema
  or volume when you ask the founder to confirm it.
- **Manifest First:** no runtime-only container/pod changes; update the manifest and verify the
  change survives recreation.

<!-- BEGIN PROJECT AGENT POLICY: generated -->
<!-- id: github-auth -->
## GitHub auth
Before you use `gh` or the GitHub API, read `~/projects/agent-policy/playbooks/github-auth.md`.

<!-- id: teardown -->
## Teardown
When your work on a PR or task ends, read `~/projects/agent-policy/playbooks/teardown.md`.

<!-- id: standing-authorizations -->
## Standing authorizations
Standing authorization (founder, 2026-09-22; amended 2026-09-25 and
2026-10-13): in fleet, apart from the ledger-harvest pull requests GOV-000070
covers or the agent-worker PRs a fleet repo-scope standing authorization covers,
an agent may merge a pull request only via `cli-dispatch land`, never
with `--force-no-review`, `--allow-no-checks` or `--allow-unverified-checks`,
and only when CI is green at the PR head and a merge-gating review from a
vendor other than the author posted PASS for that head. CI is green there when,
in the rollup `land` selects, every check concluded SUCCESS, required or not,
apart from a COMPLETED+SKIPPED job `land`'s classifier admits as outside the
diff, which never counts as a pass or as evidence, and at least one
substantive check with Actions run identity, or a legacy StatusContext,
concluded SUCCESS, whether or not required checks are configured. `land`
drops a check from that rollup only for a strictly newer, fully completed run
of the same workflow and event cohort, ranked by server-owned run identity,
holding a check of exactly the same name: a newer run not yet complete drops
nothing and reads pending, a check without a name or run identity is never
dropped, and a retained failure is red whatever its path. This includes
changes to fleet `MERGE-PATH.md` and `REVIEW-RULES.md` and the regenerated
policy files that follow from them. No panel is required. It covers no merge
into petersimmons1972/agent-policy: the founder merges canon changes.

<!-- id: pull-requests -->
## Pull requests
- **Risk and blast radius in every PR** (founder, 2026-10-28). Every PR body carries these lines:
  - `Risk: low|medium|high`, with a one-line reason.
    - low: tests, docs, or new code nothing calls yet.
    - medium: changes behaviour that lanes, CI or users run, and a revert undoes it.
    - high: touches the merge gate, required CI checks, credentials or auth, ledger or other
      data, or publication; or a revert cannot fully undo it.
  - `Blast radius:` what runs this code and who is hurt, and how badly, if it is wrong.
  - `Rollback:` how to undo it, e.g. `git revert <merge>`. Say `cannot-rollback` and give
    the manual steps when a revert is not enough.
  - `Sensitive areas:` any of auth, secrets, merge gate, CI gates, data, migrations,
    publication, dependencies; or `none`.
  Review depth and other rules may be tuned to these levels.
<!-- END PROJECT AGENT POLICY -->
<!-- END UNIVERSAL AGENT POLICY -->
