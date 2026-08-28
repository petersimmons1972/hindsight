# hindsight — CRITICAL pointer

Curated from `catalog/criticality.jsonl` by `bin/synthesize-pointer.py`. Do not edit by hand -- edit criticality.jsonl and re-run the script.

27 CRITICAL failure modes (irreversible/destructive blast radius if repeated). Safe to load at session start.

- **FM-21** [BROAD] Destructive DB/API methods must enforce their own guard (require explicit force flag or confirmation token at the method boundary)
- **FM-25** [BROAD] Never TRUNCATE a shared-project table; use scoped DELETE or dump/restore only the target project rows
- **FM-96** [BROAD] Never use `-v`/`-sv`/`--verbose` against authenticated endpoints in agent briefs; prefer `xh` with `--no-auth-header` or equivalent header suppression. On occurrence: immediately redact the transcript entry, rotate the affected token via the fleet-dispatch token-rotation runbook, and confirm no copy persists in Engram or log archives. Deterministic grep check: scan agent transcripts for `Authorization: Bearer` and `Bearer [A-Za-z0-9+/=-]{20,}` patterns before archiving.
- **FM-103** [BROAD] Treat `ATTACH_TOKENS` as crown-jewel config: (1) always read the current value, apply a structured merge tool (e.g. `jq` merge), and JSON-validate (`jq . >/dev/null`) before writing; (2) retain the previous value in a rollback variable for the duration of the rotation window; (3) after write, verify the new token works on a canary request before the old token is invalidated; (4) enforce supervised edits only — no raw `kubectl edit`. Cross-ref FM-86 (ESO-managed secret write path).
- **FM-146** [BROAD] A destructive multi-target command must have NO implicit default target: --apply without an explicit --config refuses, and an unrecognized argument aborts instead of falling through to defaults.
- **FM-176** [BROAD] A test may read a document; a destructive script may not. Deriving paths at runtime from a document turns a static command into a program with whole-repo blast radius
- **FM-185** [BROAD] Any overwrite of an unversioned file must be temp-write plus atomic rename plus fsync; a truncate-and-write that fails leaves the target destroyed while the exit code says nothing was written
- **FM-222** [BROAD] When specifying a fix for a swallowed or ignored error, state the post-condition on the ARTIFACT -- the file, the row count, the bytes on disk, the instruction the operator receives -- never the internal step imagined to produce it. 'Record the failure into state, which the caller already drains' is satisfiable, faithfully and correctly, by code that records the damage and then proceeds to cause it. 'After any run in which a repair failed, the count of valid parseable rows in the file must be at least its pre-run count' is not. The asymmetry is that a bookkeeping instruction is satisfied by an observation, while a post-condition is satisfied only by an outcome. A second, sharper form of the same error: an ABORT path is frequently load-bearing precisely BECAUSE it does nothing. Repairing the abort so it reports properly can convert a data-preserving refusal into a data-destroying continue, which is strictly worse than the swallowed error it was written to fix. For any repair to an abort, ask what aborting used to protect and whether the new path still protects it
- **FM-266** [BROAD] git reset --soft <remote-ref> to reconcile one diverged file, followed by a narrow git add of just that file, can silently stage and commit unrelated deletions from a stale index against the new HEAD
- **FM-277** [NARROW] Never interpolate a credential variable with ${VAR:-fallback} in a liveness check; the :- form expands to the SECRET when set. Use ${VAR:+set}, and treat any command that names a token variable as a publishing action
- **FM-284** [NARROW] A shared safety function (destination_deliver) wired for only one of two production callers, leaving the other silently unverified
- **FM-285** [NARROW] MERGE-only-if-every-lens-PASS gate is vacuously true when filter(Boolean) leaves zero lenses
- **FM-288** [NARROW] Workflow acceptance results are self-reported by the agent, never executed by the harness
- **FM-289** [NARROW] Verifier accepted a PASS verdict contradicted by adjacent evidence in the same payload
- **FM-292** [NARROW] Harness credential inherited at spawn, never re-synced (6th recurrence; recurrence of hc-FM-232)
- **FM-300** [NARROW] An acceptance runner that strips a background-guard shim from PATH must re-arm the guard for the ITEM command, or genuinely backgrounded work escapes refusal and reports exit 0
- **FM-301** [NARROW] A review lane's GitHub identity must match its harness, and it must fail closed rather than borrow an ambient token, or cross-vendor independence becomes unverifiable
- **FM-313** [NARROW] Consistency check SKIPS when its lookup key is absent, so the very edit it polices disarms it
- **FM-318** [NARROW] Restore verified against a snapshot taken FROM the modified thing, proving stability and mistaken for pristineness
- **FM-326** [NARROW] The campaign abort detector was run concurrently with other test suites, so it manufactured the emergency it exists to detect
- **FM-328** [NARROW] Coordinator ran the acceptance gate against lane commit b1f1ea6, saw pass, then squash-and-force-pushed 7c5177b built from an older tree, reverting the verified fix -- nothing compared the scored tree to the shipped tree
- **FM-361** [NARROW] catalog-guard's bin/tests/*.bats step is persistently red on main — needs sibling-repo checkout
- **FM-396** [NARROW] A safety argument that enumerates only what an ATTACKER can do to an invariant is incomplete: enumerate what your own code paths do to it, and name the code that could violate it.
- **FM-422** [NARROW] git reflog expire --all destroys the STASH reflog; never run it to tidy a repo
- **FM-430** [NARROW] A single agent that both implements a fix and authors its own acceptance test converges on a proof it can satisfy, not the property being guarded
- **FM-444** [NARROW] CLASS: guards assert text exists instead of that behavior happens
- **FM-533** [NARROW] A git command that changes a checkout (checkout -f, fetch <ref>:refs/heads/<x>, reset) must be issued as a single compound with an explicit 'cd <scratch>' in the SAME command and a post-condition assert on 'git rev-parse --show-toplevel', because the harness resets shell cwd between Bash calls and a scratch-intended command silently lands on the founder's live checkout.

For HIGH-tier entries (real but too numerous to preload), use `bin/query-failure-modes.sh <keyword>` -- do not open docs/HIGH.md directly.
