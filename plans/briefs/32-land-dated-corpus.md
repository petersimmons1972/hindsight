Land issue #32: the dated L1 corpus, with the withdrawn instrument's reporting removed.

STATE, MEASURED — do not re-derive it. Local branch `feat/32-repair-first-seen` (5 commits, clean
tree, tip `b93494e` "Make repair_first_seen statistics unpointable") is NOT abandoned. The campaign
record called it defective; it is essentially done and its suite is green (210 tests). The nine
earlier defect instances were all one class — statistics computed about data whose identity was never
established — and were resolved by making those statistics unpointable.

WHAT REMAINS. The three-arm recurrence-trend instrument was WITHDRAWN by founder ruling 2026-08-03
(`docs/DECISIONS.md` rows 22-26, "mechanize first, measure later"). `pipeline/repair_first_seen.py`
still emits instrument-specific reporting (the DIFFERENTIAL / WARNING output) that now has no
consumer. Delete that reporting — roughly 50 lines — and keep the dating itself.

DO:
 1. Rebase `feat/32-repair-first-seen` onto current origin/main and resolve any conflicts.
 2. Remove ONLY the instrument-specific reporting. The date repair, its provenance flag, and the
    loud fallback count stay. A row dated by ingest-date fallback must remain distinguishable from
    an organically dated row -- that distinction is the whole point and roughly 90% of repaired rows
    are ingest-dated.
 3. Keep printing the fallback count on every run (R4: fail loud, two zeros distinguishable).
 4. `--input /dev/null` must still exit non-zero naming the empty input.

DO NOT re-open the withdrawn instrument, add arms, add a PREREG, or compute recurrence trends.

If dating changes any row's `enforcement` value (it should not), re-baseline
`conf/enforcement-floor.conf` in the same commit -- see plans/AUTOMATION-QUEUE.md.

VERIFY, paste each: the full pytest and bats baselines from plans/AUTOMATION-QUEUE.md;
`python3 pipeline/reconcile_l1.py` (report COMPLETE or PARTIAL and which); the dated-row count, which
must RISE from the 242-undated starting point; and the fallback count printed on a normal run.

FILES: pipeline/repair_first_seen.py, its tests, and the L1 rows it dates. Nothing else.

Your FINAL line must be exactly: VERDICT: CONFIRMED_GOOD  or  VERDICT: DEFECTIVE
