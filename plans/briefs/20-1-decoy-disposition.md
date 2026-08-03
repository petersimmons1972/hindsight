Dispose of two decoy files before they corrupt the phantom ledger. Issue #20, packet 1.

THE HAZARD, MEASURED. Two 6-byte, non-executable files containing the literal string `decoy`, both
stamped 2026-08-01 22:06:46, sit at claimed enforcement paths:
    /home/psimmons/bin/health-check.sh
    /home/psimmons/.git/hooks/pre-commit
They are leftover attack-round fixtures. `/home/psimmons/.git` is not a valid repo, so that hook
could never fire. hindsight's guard currently classifies both as phantom via its source-root
CONTAINMENT check -- NOT via absence. A path-existence check already passes on them.

WHY THIS IS URGENT AND COMES FIRST. Packet `33-A-stale-paths` repoints hc-les-08 and hc-les-10 to
`bin/health-check.sh` -- the same path as the first decoy. Combined with the widened enforcement gate
(issue #31, landed), that flips these from "phantom" to "resolving" and SILENTLY SHRINKS the phantom
ledger. A debt ledger that shrinks because a decoy satisfied a path check is the exact fleet#152
defect the floor exists to catch, arriving through the front door.

DO:
 1. Determine and record each file's true disposition. DO NOT DELETE either file in this packet --
    they sit outside any repo, in the founder's home directory, and deleting them is not yours to
    decide. Document them.
 2. Add each to `conf/known-phantoms.conf` with evidence: size, mode, content, mtime, and the fact
    that `/home/psimmons/.git` is not a valid repository. Record the disposition as a decoy fixture,
    not as unfixed debt to be repaired.
 3. Make the guard distinguish "path exists" from "path is a plausible mechanism" for these, OR
    document explicitly in `docs/` why a 6-byte non-executable file passes the existence check and
    what that means for the ledger's trustworthiness. Existence is necessary, not sufficient --
    the guard already says so in its SCOPE line; make that concrete here.
 4. Add a test that a non-executable stub at a claimed `kind: test` or `kind: hook` path does NOT
    count as enforcement.

If you change any enforcement value or add ledger rows that alter the enforcement-bearing count,
re-baseline `conf/enforcement-floor.conf` in the same commit.

VERIFY: the full baselines; and demonstrate the before/after classification of both decoy paths with
actual command output, not description.

Your FINAL line must be exactly: VERDICT: CONFIRMED_GOOD  or  VERDICT: DEFECTIVE
