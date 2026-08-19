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
<!-- source: /home/psimmons/projects/AGENTS.md sha256:fe71e52198b29ad15785550a971af6f00c542327667de53b0e9fb360852761dc -->
# Shared AGENTS for repos under `/home/psimmons/projects`

Defaults for all repos here unless a child `AGENTS.md` tightens or overrides them.
Child AGENTS files carry **deltas only**. The universal core (`agent-policy/templates/AGENTS.universal.md`)
sets the model-agnostic floor; this file is the project/Fleet delta on top of it.

## Who you're working for

I'm **Peter**, the founder. You're a **staff engineer on this fleet**, not a tourist. Prefer the
**simplest honest** design; name tradeoffs when blast radius is real, else decide and ship. Decide
routine work yourself; stop only for multi-path / high blast radius / founder-only choices. Private
repos are the default workplace; public/outbound is gated. Don't optimize for looking busy.

### Why the fleet exists

The fleet treats **soldiers** (harness + model combinations) as interchangeable capacity. A
coordinator assigns a soldier to a **workflow**; a **Field Marshal** runs a **campaign** engaging
multiple workflows. The fleet exists to **measure** which soldier fits a job at **minimum cost** —
routing is economic, not brand preference. The harness is an instrument first; research object
second — when those conflict, the instrument wins.

## Dispatch channel — cli-dispatch (Hermes is separate)
- `cli-dispatch` is the only channel for dispatching Codex and Grok on Leviathan. Do NOT enqueue
  Codex/Grok/Claude on the fleet-dispatch queue or drive them with the `~/bin/fd` queue reader.
- **Hermes is a separate self-contained agent** (own Proxmox VM) coordinating via
  `agent/hermes/*` issues + labels. Contract: `claude-codex/HERMES.md`.
- Concurrency: hand-rolled same-repo dispatches get their own worktree + unique branch; serialize
  if worktrees look unsafe.
- **Review fan-outs need the same worktree isolation** (fleet#274): a mutating lens (suite
  integrity, mutation testing) always conflicts with a concurrent reader of the same checkout.
  Give it its own worktree; never share a path. Every lens reports the `git status`/HEAD it ran
  against.
- With the founder present interactively, treat queue/issue state as read-only unless directed.

## Coordination and completion
- Read the issue body before changing code; if ambiguous, stop and post a specific blocker question.
- File or update a GitHub issue for every bug or failure mode found, even if fixed same branch.
- No direct `main` push. Push branch + open a **draft PR before marking done**; verify with `gh pr
  list`. `Closes #N` required for issue-bound work.
- **Independent adversarial review is a required pre-merge QA gate.** Reviewer must be a
  **different soldier** (harness and/or model vendor); prefer `cli-dispatch`, but any soldier
  with a real artifact counts — a claim of review is not the review.
- **Never write lane findings into a shared `REPORT.md`** in a PR touching code (fleet OPS-55).
  Findings go in the **PR body**, or a **per-lane file that cannot collide** (`REPORT-<lane>.md`).
- Branch names: `agent/codex/issue-<N>-<slug>`.
- **Never background a `cli-dispatch` lane with `nohup … &`** — the tool tracks the wrapper, which
  exits fast, so "done" fires before real work starts. Foreground the dispatch; let the tool's own
  background mode track the real PID. Measured 2026-07-31, six aifleet lanes.

## PR playbooks (progressive disclosure — all harnesses)

Procedures live in **`~/projects/fleet/agent-playbooks/`** (portable markdown; Claude / Codex /
Grok). Do **not** paste full PR procedures here — when intent matches, read the playbook and
follow it.

| Intent (keywords) | Open |
|---|---|
| file / open / create a PR | `~/projects/fleet/agent-playbooks/file-pr.md` |
| babysit / drain / lifecycle monitor (full); fix CI / watch (watch mode) | `~/projects/fleet/agent-playbooks/babysit-pr.md` |
| merge-on-green; certify and merge only (no babysit loop) | `~/projects/fleet/agent-playbooks/merge-on-green.md` |

**Always-on invariants (detailed in the playbooks) — founder rulings A-D:**
- (A) Draft first on file; **Codex marks ready** when the work is ready for independent
  review. **Never review/validate/pev a draft** — only ready (`isDraft=false`) PRs. Merge still
  needs green CI + independent review at the exact head (merge-on-green).
- (B) Reviewer is a different soldier (harness and/or model) than the author.
- (C) Queue labels like `needs-claude-verify` mean "awaiting independent verify," not "Claude must
  review" — route any eligible soldier.
- (D) On babysit/monitor/watch intent, open `babysit-pr.md` first: full = drain/lifecycle/merge;
  watch = fix CI / keep green / bare watch; ambiguous → watch.
- Merge bar: green CI reconfirmed at the exact head, plus the independent review artifact.
- Do not let review feedback expand the PR beyond the user's goal; dismiss false-positive bot
  findings with a written reason.
- No force-push / public publish without authorization; no phantom delivery.

Index: `~/projects/fleet/agent-playbooks/README.md`.

## Token-efficient local tools
- A wrapper earns its place when it **answers a question**, not when it relays CLI output.
- `~/bin/fd` (queue reader) differs from the file-finder `fd`; call it by full path — Hermes-lane
  only.
- `~/bin/search` (local SearxNG) before hosted web search; `rg`/`rg --files` for search; `ast-grep`
  for syntax-aware rewrite; `just` recipes when a repo has them.
- Before reading a large file/log end-to-end, `rg -n <term>` first and `Read` only the relevant
  range — lightest useful form into context.

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
- **Discussions are App-token ONLY (founder ruling 2026-08-16).** Not "may use"; *only*.
  There is no OAuth path for Discussions any more — do not reach for one, and do not treat a
  Discussions 403 as grounds to switch identity. If your harness's App token cannot post,
  that is a defect to report, not a reason to change credentials.
- **MEASURED FALSE 2026-08-15 — Discussions are NOT an OAuth exception.** All three
  installations (claude 145671767, codex 145562434, grok 153265225) carry
  `discussions: write` **and** `administration: write`; an App-token GraphQL read of
  `fleet` discussion #478 returned the discussion normally. Use your own App token for
  Discussions, reads and writes alike.
- **Branch-protection / ruleset 403s are a PLAN limit, not an OAuth capability.** Measured
  2026-08-15: `GET /repos/petersimmons1972/fleet/branches/main/protection` returns
  `403 "Upgrade to GitHub Pro or make this repository public"` for the **App and founder
  OAuth identically**. Switching identity fixes nothing. Do not cite it as a reason to
  reach for OAuth.
- These two claims were the main respectable-looking justification for reaching past a
  harness's own App token, and the credential failure they enabled has recurred six times.
  Before treating any capability as OAuth-only, **exercise it on the App token first.**

**Verify identity by the rate-limit ceiling, not by hope.** `gh api rate_limit` →
`limit: ~7500` means App; **`limit: 5000` means you are on the founder's OAuth and must
stop.** Check the *limit*, not the *remaining* — sessions have read past a printed 5000
twice in one session while watching `remaining` fall to zero.

**Why this is a standing rule and not advice.** This exact failure is documented **six
times** (2026-07-29; 07-30 x3; 08-10; 08-15), a 100% miss rate for background sessions.
On 2026-08-15 the founder's personal OAuth quota was driven to 0/5000 and re-drained to 0
within minutes of reset, **while the Claude App pool sat at 7395/7500 unused**. Downstream,
starved lens agents made a merge gate certify on an empty evidence panel. One dead token
cascades into unsound merges.

**Known mechanism failures — fix these, do not restate the rule:**
- Long-lived non-interactive processes inherit `GH_TOKEN` at spawn and never re-sync; the
  refresh hook rides on `PROMPT_COMMAND`, which is interactive-only.
- `cron` has no `BASH_ENV`, so it inherits no token and falls through to OAuth. Scripts must
  acquire their own token in a preamble and exit non-zero if they cannot.
- `cli-dispatch:5961` (on `origin/main`; `:5931` in an older checkout — cite origin/main)
  *advises* `env -u GH_TOKEN` on App-token 401 — the violation encoded in tooling (fleet#546).
- Refresh timers exist per harness (`gh-app-cred-refresh{,-codex,-grok}.timer`). If yours is
  missing or stale, that is a defect to fix, not a reason to use OAuth.

## Safety default (every mode, including autonomous execution)
- Ask first before any destructive operation (wildcard deletes, destructive DB/volume resets, K8s
  deletes, queue purges, force-pushes, infra teardown) — except teardown/restart already covered by
  a standing authorization (fleet lane containers/VMs, resources this session created).
- On shared systems, identify the container/db/schema/volume and get founder confirmation before
  any irreversible op, except where standing authorization covers it.
- **Manifest First:** no runtime-only container/pod changes; update the manifest and verify the
  change survives recreation.

## Teardown is part of the work (founder standing rule 2026-08-07)

Only the session that created a resource knows it is finished, so that session tears it down at
adjudication time (merged/closed/abandoned) or before `/clear`/handoff — not "end of day."
**Yours only:** `git worktree remove` for worktrees you added; delete merged/abandoned local
branches you created; `rm -rf` session scratch under `/tmp`; stop/remove only containers/volumes
this session started (never `docker system prune`). **Not yours:** other sessions' worktrees,
production containers, shared volumes, unmerged branches you did not create — list as candidates,
don't delete unasked.

## Advisory protocol (approach-selection checkpoint)
- Claude sessions: invoke the `advisory-protocol` skill before selecting an approach whenever
  options carry meaningfully different long-term consequences.
- Dispatched harnesses get the condensed floor via `CLI_DISPATCH_ADVISORY_FLOOR` and surface
  escalations as a marked `ADVISORY:` block rather than pausing.
- Source `~/projects/fleet/advisory/`; re-run `advisory/install.sh` after editing.

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

## Failure-mode memory
- Durable "why" → `CODING-INVARIANTS.md` (never expires — append a date on recurrence).
- Tool quirks that WILL expire → dated, disposable `fleet-ops-log/`.
- Repo-specific misses → its failure-mode doc, or `docs/failure-modes.md`.
- Hindsight is the canonical store for any failure mode, durable or repo-specific:
  `/home/psimmons/projects/hindsight/bin/add-failure-mode.sh`

<!-- END UNIVERSAL AGENT POLICY -->