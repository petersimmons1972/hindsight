Reclassify the homelab genuine phantoms. Issue #33, packet B2.

THE THREE ROWS:
  pipeline/L1/homelab-incidents.jsonl -- hc-inc-007, hc-inc-008
  pipeline/L1/homelab-lessons.jsonl   -- hc-les-11
Plus conf/known-phantoms.conf and conf/enforcement-floor.conf.

These claim mechanisms that were never built or were removed. They are genuine phantoms: the claim is
real-shaped, the mechanism is absent.

This packet is INDEPENDENT of the claude-codex families (ccx-FM-001/021/023), which belong to issues
#38/#39 and are ruling-blocked. Do not touch any ccx-* row.

For each row: set `enforcement: null` and record it in conf/known-phantoms.conf with evidence of
absence (the command you ran showing the path does not exist, and in which repo you looked). NEVER
invent a path to fill the field -- an honest null is the CORRECT answer. NEVER delete the row.

MANDATORY: re-baseline `conf/enforcement-floor.conf` in the same commit; this packet changes the
enforcement-bearing count and the floor test asserts equality.

VERIFY: the full baselines; `--verify-enforcement` before and after with DEBT-FLOOR and
PHANTOMS-MEASURED quoted for both; and for each of the 3 rows, the actual command output proving the
claimed mechanism is absent.

Your FINAL line must be exactly: VERDICT: CONFIRMED_GOOD  or  VERDICT: DEFECTIVE
