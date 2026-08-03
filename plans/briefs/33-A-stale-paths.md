Repair the 5 stale enforcement paths. Issue #33, packet A.

PRECONDITION: packet `20-1-decoy-disposition` MUST have landed. Two of these repairs point at
`bin/health-check.sh`, where a 6-byte decoy file sits; repointing before the decoy is dispositioned
silently shrinks the phantom ledger. Verify it landed before starting.

THE FIVE ROWS:
  pipeline/L1/fleet-main.jsonl       -- fleet-OPS-19, fleet-OPS-20
  pipeline/L1/homelab-lessons.jsonl  -- hc-les-08, hc-les-10
  pipeline/L1/engram-go.jsonl        -- eng-patternB
Plus conf/known-phantoms.conf, and conf/enforcement-floor.conf if the count moves.

eng-patternB NEEDS MORE THAN A PATH FIX. Its enforcement is
`{"file": "score.go", "kind": "lint"}` -- a bare filename that resolves nowhere, declared as a lint
mechanism when it is a Go SOURCE file. The real file is `internal/search/score.go` in engram-go
(the referenced `func CompositeScoreWithWeights` is at :475, while the L1 instance text says
score.go:252 -- additional drift). Repairing only the path leaves a source file masquerading as an
enforcement mechanism. Fix the `kind` too, or set `enforcement: null` and record it as debt --
an honest null is a CORRECT answer.

DO NOT TRUST `--verify-enforcement` TO FIND YOUR WORK FOR YOU. Resolve every enforcement row
yourself. (Issue #31 widened the gate past `auto: machine`, but the tool checks path EXISTENCE only
-- a resolving path is necessary, not sufficient evidence that it enforces the claimed lesson.)

For each row, either (a) repair the path to a mechanism that genuinely enforces the claimed lesson,
or (b) set `enforcement: null` and record it in conf/known-phantoms.conf with evidence. NEVER invent
a path to fill the field. NEVER delete the row.

MANDATORY: re-baseline `conf/enforcement-floor.conf`. This packet WILL move the enforcement-bearing
count, and `test_committed_floor_has_no_slack_against_the_committed_corpus` asserts equality.

VERIFY: the full baselines; `--verify-enforcement` before and after with DEBT-FLOOR and
PHANTOMS-MEASURED quoted for both; and a per-row account of what each of the 5 became and why.

Your FINAL line must be exactly: VERDICT: CONFIRMED_GOOD  or  VERDICT: DEFECTIVE
