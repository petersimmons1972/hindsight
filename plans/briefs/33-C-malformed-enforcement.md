Reclassify the 2 malformed enforcement values and reconcile the floor. Issue #33, packet C.

THE TWO ROWS:
  pipeline/L1/engram-go.jsonl  -- eng-taxo-scorer_disagrees
  pipeline/L1/fleet-orch.jsonl -- fleet-orch-OPS-12
Plus conf/known-phantoms.conf and conf/enforcement-floor.conf.

These carry enforcement values that are malformed rather than merely stale -- they do not name a
resolvable mechanism at all. They are NOT genuine phantoms (a phantom claims a real-shaped mechanism
that does not exist); they are structurally invalid claims. Classify them as such and say so in the
ledger evidence, so a later reader can tell the two apart.

For each: set `enforcement: null` and record the row in conf/known-phantoms.conf with the exact
malformed value as evidence, or repair it to a real mechanism if one genuinely exists. NEVER invent
a path. NEVER delete the row.

MANDATORY: re-baseline `conf/enforcement-floor.conf` in the same commit -- this packet changes the
enforcement-bearing count by construction, and the floor test asserts equality, not `>=`.

Also reconcile the floor against whatever packets 33-A and 20-1 already landed; state the arithmetic
explicitly in your output (old floor, rows added, rows removed, new floor) rather than just writing
the new number.

VERIFY: the full baselines; `--verify-enforcement` before and after with DEBT-FLOOR quoted for both;
and confirm the phantom ledger is exactly bijective with the measured phantom set (no
known-but-not-measured entries padding the allowlist, no measured-but-not-known entries).

Your FINAL line must be exactly: VERDICT: CONFIRMED_GOOD  or  VERDICT: DEFECTIVE
