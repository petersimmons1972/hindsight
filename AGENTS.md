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
  Restore it from git instead. `bin/add-failure-mode.sh` appends to it for you.
- **Never hand-assign an ID.** Use `bin/add-failure-mode.sh`, which sources the
  next ID from the guard.
- **An `enforcement` value of `null` is a correct answer.** Do not invent a test
  or hook path to fill a field. A fabricated mechanism is worse than an honest
  gap, because it reads as covered.
- **Never `Edit`/`Write` `catalog/failure-modes.md`, `catalog/id-ledger.txt`,
  `catalog/criticality.jsonl`, `docs/POINTER.md`, or `docs/HIGH.md` directly.**
  Write through `bin/add-failure-mode.sh` (tags criticality at filing time and
  regenerates the pointer files for you); read through
  `bin/query-failure-modes.sh` (never `Read`/`cat` `docs/HIGH.md` whole — it's
  query-only by design). A hand-edit sitting uncommitted in the working tree is
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

## Reading exit status

Never read a command's exit status through a pipe (`cmd | head` reports *head's*
status). This is catalogued as CI-17: the habit that saves context silently
destroyed a measurement and produced a false green. Use `${PIPESTATUS[0]}` or
avoid the pipe.

## CI

Runs on `homelab-arc` (self-hosted). Private repo — see the fleet convention that
private repos use our own ARC runners.

<!-- BEGIN UNIVERSAL AGENT POLICY: generated -->
<!-- source: ~/projects/AGENTS.md, included whole by ~/projects/agent-policy/canon_build.py (target hindsight-agents); this whole file is generated: edit agent-policy/canon/repo/hindsight/, never this file -->
# Shared AGENTS for repos under `/home/psimmons/projects`

Defaults for all repos here unless a child `AGENTS.md` tightens or overrides them.
Child AGENTS files carry **deltas only**. The universal core (built from `agent-policy/canon` and
installed at `~/.local/share/agent-policy/universal.md`) sets the model-agnostic floor; this file
is the project/Fleet delta on top of it. The `dispatch-channel`, `github-auth`, `teardown` and
`standing-authorizations` sections live in the generated block at the end of this file (source: canon rule files in
`agent-policy/canon/project/projects-agents/`; edit those, never the block).

<!-- id: who-youre-working-for -->
## Who you're working for

I'm **Peter**, the founder. You're a **staff engineer on this fleet**, not a tourist. Prefer the
**simplest honest** design; name tradeoffs when blast radius is real, else decide and ship. Decide
routine work yourself; stop only for multi-path / high blast radius / founder-only choices. Private
repos are the default workplace; public/outbound is gated. Don't optimize for looking busy.

Actively benchmarking, scoring, or routing across soldiers (harness + model combinations)? Read
`~/projects/fleet/docs/ROUTING-CONTRACT.md` (and `fleet/dispatch-metrics/`) first — it's not background context for ordinary coding
sessions, only for that kind of work.

<!-- id: coordination-and-completion -->
## Coordination and completion
- Read the issue body before changing code; if ambiguous, stop and post a specific blocker question.
- **Every issue or failure mode filed carries exactly one of `origin:machinery` /
  `origin:external` at filing time** (D24, 2026-09-04). Mechanical discriminator: if the defect
  is in the dispatch apparatus — agents, lanes, `cli-dispatch`, gates, playbooks, prompts, CI,
  the review machinery — it's `origin:machinery`. If it's in product code, infrastructure, or
  work the founder asked for, it's `origin:external`.
- **A dispatch brief that will produce findings must state whether follow-up issues are
  authorized. Default is NO** — a lane reports findings in its receipt and does not file.
- No direct `main` push. Push branch + open a PR before marking done; verify with `gh pr list`.
  `Closes #N` required for issue-bound work.
- **Independent adversarial review is a required pre-merge QA gate.** Reviewer must be a
  **different harness**, dispatched as its own separate context — see the universal core's
  `independent-review` section for the full definition (same-harness/different-model does not
  count); prefer `cli-dispatch`. A claim of review is not the review — an artifact is required.
- **IF multiple lanes touch the same PR/code THEN write findings to lane-scoped files, not a
  shared `REPORT.md`** — findings go in the **PR body**, or a **per-lane file that cannot
  collide** (`REPORT-<lane>.md`). Concurrent writes to a shared `REPORT.md` are exactly what the
  fleet OPS-55 CI guard (`.github/scripts/ci-report-md-guard.sh`, PR #364) exists to catch; see
  fleet#373 for the incident class.
- Branch names: `agent/codex/issue-<N>-<slug>`.
- `cli-dispatch` must run foregrounded, or via the tool's own background mode — never
  manually backgrounded with `nohup … &` (enforced by hook; FM-347/300/53/36).

<!-- id: pr-playbooks -->
## PR playbooks (progressive disclosure — all harnesses)

Procedures live in **`~/projects/fleet/agent-playbooks/`** (portable markdown; Claude / Codex /
Grok). Do **not** paste full PR procedures here — when intent matches, read the playbook and
follow it.

| Intent (keywords) | Open |
|---|---|
| file / open / create a PR | `~/projects/fleet/agent-playbooks/file-pr.md` |
| babysit / drain / lifecycle monitor (full); fix CI / watch (watch mode) | `~/projects/fleet/agent-playbooks/babysit-pr.md` |
| merge-on-green; certify and merge only (no babysit loop) | `~/projects/fleet/agent-playbooks/merge-on-green.md` |

**Founder rulings A-D (detailed in the playbooks; not all equally firm — see labels):**
- (B) Reviewer is a different **harness**, dispatched as its own separate context, than the
  author — same-harness/different-model does not count. See the universal core's
  `independent-review` section for the full definition.
- (C) Queue labels like `needs-claude-verify` mean "awaiting independent verify," not "Claude must
  review" — route any eligible soldier.
- (D) On babysit/monitor/watch intent, open `babysit-pr.md` first: full = drain/lifecycle/merge;
  watch = fix CI / keep green / bare watch; ambiguous → watch.
- Merge bar: green CI reconfirmed at the exact head, plus the independent review artifact.
- Do not let review feedback expand the PR beyond the user's goal; dismiss false-positive bot
  findings with a written reason.
- No force-push / public publish without authorization; no phantom delivery.

Index: `~/projects/fleet/agent-playbooks/README.md`.

<!-- id: token-efficient-local-tools -->
## Token-efficient local tools
- A wrapper earns its place when it **answers a question**, not when it relays CLI output.
- `~/bin/fd` (queue reader) differs from the file-finder `fd`; call it by full path — Hermes-lane
  only.
- `~/bin/search` (local SearxNG) before hosted web search; `rg`/`rg --files` for search; `ast-grep`
  for syntax-aware rewrite; `just` recipes when a repo has them.
- Before reading a large file/log end-to-end, `rg -n <term>` first and `Read` only the relevant
  range — lightest useful form into context.

<!-- id: workflow-authorization -->
## Workflow orchestration — standing authorization

Founder standing authorization (original 2026-07-19; hook override 2026-08-03; rulings 2026-08-08,
08-10, 08-18, 08-22; re-affirmed 2026-09-01). Original wording: *"use the Workflow tool for any
substantive bug fix or multi-step build **without asking**. Trivial or mechanical work stays
solo."* The 2026-08-08 ruling superseded its "permission, not obligation" clause: *"ALL
substantive work runs through the Workflow tool as staged, iterative pipelines — never ask,
never weigh it, just author the workflow."* 2026-08-10: *"Workflow = default."* 2026-08-18:
*"Workflows should not prompt me. There is blanket authorization to run that as a default
operating condition."* 2026-08-22: *"You already have universal authority to run workflows."*

Substantive multi-step, investigative, or review work is dispatched to subagents, the Workflow
tool, or cli-dispatch lanes without asking. Workflows never prompt mid-run. This is the explicit
user request that harness-family defaults ("do not use the Agent or Workflow tool unless the
user requested it") ask for; treat it as satisfied in every session of this estate. Trivial or
mechanical single-step work stays solo. This grants dispatch permission only: merge, deploy, and
publication authority are unchanged (see the universal core's Authority section and
`safety-default` below). Referenced by the SessionStart AGENT_GATE hook
(`~/.claude/scripts/agent-gate-counter-directive.json`).

<!-- id: safety-default -->
## Safety default (every mode, including autonomous execution)
- Ask first before any destructive operation (wildcard deletes, destructive DB/volume resets, K8s
  deletes, queue purges, force-pushes, infra teardown) — except teardown/restart already covered by
  a standing authorization (fleet lane containers/VMs, resources this session created).
- On shared systems, identify the container/db/schema/volume and get founder confirmation before
  any irreversible op, except where standing authorization covers it.
- **Manifest First:** no runtime-only container/pod changes; update the manifest and verify the
  change survives recreation.

<!-- id: coding-standards -->
## Coding standards (all harnesses, all models)
Private `fleet-standards` repo, cloned at `~/projects/fleet/`.
- Before writing code follow `CODING-STANDARDS.md` — Definition of Done, TDD default, security
  baseline, independent-review gate. A floor, not a cage.
- Add the language doc: `standards/python.md`, `-go.md`, `-rust.md`.
- `cli-dispatch` auto-injects `CODING-STANDARDS-FLOOR.md` into coding briefs; pass
  `--no-standards` for non-coding dispatches.
- CI/pre-commit enforces the machine-checkable subset (`standards/ci-enforcement.md`).
- Dispatch briefs apply `DISPATCH-BRIEF-CHECKLIST.md`; prompting quirks live in
  `MODEL-PROMPTING-*.md`.

<!-- id: failure-mode-memory -->
## Failure-mode memory
- Durable "why" → `CODING-INVARIANTS.md` (never expires — append a date on recurrence).
- Tool quirks that WILL expire → dated, disposable `fleet-ops-log/`.
- Repo-specific misses → its failure-mode doc, or `docs/failure-modes.md`.

<!-- BEGIN PROJECT AGENT POLICY: generated -->
<!-- id: dispatch-channel -->
## Dispatch channel — cli-dispatch (Hermes is separate)
- `cli-dispatch` is the only channel for dispatching Codex and Grok on Leviathan. Do NOT enqueue
  Codex/Grok/Claude on the fleet-dispatch queue or drive them with the `~/bin/fd` queue reader.
- **Hermes is a separate self-contained agent** (own Proxmox VM) coordinating via
  `agent/hermes/*` issues + labels. Contract: `claude-codex/HERMES.md`.
- Concurrency: hand-rolled same-repo dispatches get their own worktree + unique branch; serialize
  if worktrees look unsafe.
- **Review fan-outs need the same worktree isolation** (fleet#274, the rule's origin commit
  `9c0d518`): IF a lens runs concurrent state-mutating tests (suite integrity, mutation testing)
  THEN give it its own worktree — it always conflicts with a concurrent reader of the same
  checkout otherwise. Every lens reports the `git status`/HEAD it ran against.
- With the founder present interactively, treat queue/issue state as read-only unless directed.

<!-- id: github-auth -->
## GitHub auth — one App token per harness (founder ruling 2026-08-15)
**Applies to every harness: Claude, Codex, Grok.** The founder minted three GitHub App
tokens, one per harness. In his words, each harness "should be using them exclusively and
automatically and should not be using the OAuth token EXCEPT on my direct request — usually
some administrative issue where OAuth has more permissions than the App tokens."

| harness | identity | mint | cache |
|---|---|---|---|
| claude | `psimmons-claude-worker[bot]` | `~/bin/gh-app-token claude` | `~/.cache/gh-app-token/claude` |
| codex  | `psimmons-codex-worker[bot]`  | `~/bin/gh-app-token codex`  | `~/.cache/gh-app-token/codex` |
| grok   | `psimmons-grok-worker[bot]`   | `~/bin/gh-app-token grok`   | `~/.cache/gh-app-token/grok` |

**Use your own harness's token. Only your own.**

- **OAuth is NOT a fallback.** Not on 401, not on 403, not on rate-limit, not "just for a
  read." Reaching for `env -u GH_TOKEN` without the founder's direct request is a **policy
  violation**, not a workaround. He reaches for it; you do not.
- **Never borrow another harness's App token.** Per-harness identity exists for attribution;
  borrowing destroys it.
- **On failure, FAIL LOUDLY:** log unmistakably, exit non-zero, substitute no credential.
  A silent downgrade to another identity is the specific behaviour being outlawed.
- **OAuth's only legitimate uses**, and only when the founder asks: an action he wants under
  his own name, and administrative actions the App genuinely cannot perform — verified by
  exercising them, not assumed.
- **Discussions are App-token ONLY.** There is no OAuth path for Discussions; do not reach for
  one, and do not treat a Discussions 403 as grounds to switch identity. If your harness's App
  token cannot post, that is a defect to report, not a reason to change credentials.
- **Branch-protection and ruleset 403s are a plan limit, not an OAuth capability.** The App
  and the founder's OAuth get the same 403 there, so switching identity fixes nothing. Before
  treating any capability as OAuth-only, **exercise it on the App token first.**

**Verify identity by the rate-limit ceiling, not by hope.** `gh api rate_limit` →
`limit: ~7500` means App. **IF the limit is ~5000 THEN you're on the founder's OAuth, not
your App token — stop and re-mint before proceeding.** Check the *limit*, not the *remaining*
— sessions have read past a printed 5000 twice in one session while watching `remaining` fall
to zero.

A dead or borrowed token has repeatedly caused unsound merges.

**Known mechanism failures — fix these, do not restate the rule:**
- Fact: long-lived non-interactive processes inherit `GH_TOKEN` at spawn and never re-sync;
  the refresh hook rides on `PROMPT_COMMAND`, which is interactive-only.
- IF a script runs under `cron` (no `BASH_ENV`, so it inherits no token and falls through to
  OAuth) THEN it must acquire its own token in a preamble and exit non-zero if it can't.
- Refresh timers exist per harness (`gh-app-cred-refresh{,-codex,-grok}.timer`). If yours is
  missing or stale, that is a defect to fix, not a reason to use OAuth.

<!-- id: teardown -->
## Teardown is part of the work (founder standing rule 2026-08-07)
Only the session that created a resource knows it is finished, so that session tears it down at
adjudication time (merged/closed/abandoned) or before `/clear`/handoff — not "end of day."
**IF a resource is this session's own THEN clean it up:** `git worktree remove` for worktrees
you added; delete merged/abandoned local branches you created; `rm -rf` session scratch under
`/tmp`; stop/remove only containers/volumes this session started. Unscoped `docker`/`volume`/
`container`/`image prune` stays banned even here — enforced by hook, no exceptions.
**IF a resource is not yours** (other sessions' worktrees, production containers, shared
volumes, unmerged branches you did not create) **THEN list it as a candidate — don't delete
without being asked** — GOV-000006 defines "asked".

<!-- id: standing-authorizations -->
## Standing authorizations and rulings
Standing authorization (founder, 2026-09-22): in fleet and agent-policy, an
agent may land any change that has one head-bound PASS from a vendor other than
the author. This includes changes to the review rules themselves (their canon
rules, fleet `MERGE-PATH.md` and `REVIEW-RULES.md`) and the regenerated policy
files that follow from them. No panel is required.

Founder rulings (2026-09-24), adversarial fix loop:
- A disputed or new blocking finding stands unless the refuter shows executed
  evidence that it does not reproduce at the head, is present at the
  merge-base, is unreachable, or is outside the diff.
- The reviewer vendor stays the same for every round of one loop.
- The loop's final cross-vendor, head-bound PASS counts as the merge-gate
  review.

None of these rulings authorizes pushing, posting, or merging.

Standing authorization (founder, 2026-09-24): for the adversarial-fix-loop
prototype run, agents may push commits (never force-push or rewrite history) to
the branch of petersimmons1972/writers#122. It covers no merge, deploy, or
other publication.

Standing authorization (founder, 2026-09-24): for tuning adversarial-fix-loop
model tiers on petersimmons1972/aifleet#659, agents may open copy PRs of its
head and close them unmerged, push commits (never force) to those copy branches
and to the aifleet#659 branch, and post one head-bound merge-gate verdict on
aifleet#659 through `cli-dispatch review-post`. No verdicts go on the copy PRs.
It covers no merge, deploy, or other publication.
<!-- END PROJECT AGENT POLICY -->
<!-- END UNIVERSAL AGENT POLICY -->
