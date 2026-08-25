# REVIEW: hindsight PR#135 (FM-386..390 post-freeze batch)

Reviewer: Grok (grok-build lane, separate harness), read-only, two rounds.
Adjudicated by the coordinator (bg job 92e4a093, 2026-08-20 late).

Round 1 (at 0b08d43): FAIL — three findings, ALL CONFIRMED against artifacts:
FM-388 miscited c-132 (the declared-vs-live cluster) instead of c-133; the old
FM-389 bundled two already-catalogued modes (c-004 network-off, c-094 stdin
hang) and contradicted FM-68's mitigation; the L2 regen silently dropped FM-305
from HIGH.md (pre-existing post-cap representative-selection side effect).

Rework: undo journals rolled back the two challenged filings; re-filed as
FM-388 (recurrence c-133), FM-389 (recurrence c-004), FM-390 (recurrence c-094,
FM-68-aligned); FM-305 drop disclosed and filed as hindsight#136; single atomic
commit ba37eb6 (force-with-lease on this session's own branch).

Round 2 delta (at ba37eb6): PASS, confidence HIGH — tags exact (none, none,
c-133, c-004, c-094) with cluster membership spot-checked in L2; FM-390 text
agrees with FM-68; pins exact 703/278; atomicity rev-list count 1; guard OK
next FM-391, ledger +5/0. Residuals accepted by the coordinator: the commit
text says "filed this session" without naming hindsight#136 (the PR body and
this artifact name it); hc-FM-388's emergent L2 cluster is c-220 while its
recurrence_of tag records the human lineage decision c-133 — tag and clustering
answer different questions.

Coordinator host verification at ba37eb6: pytest guard+pipeline 545 passed;
replay_l2 PASS 703 entries / 278 clusters; catalog guard OK.
