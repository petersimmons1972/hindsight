Define the embedding snapshot format and decouple clustering from the HTTP backend. Issue #30,
packet 1 of 5. This packet lands NO CI wiring -- it only makes offline replay possible.

WHY. CI cannot verify that the committed L2 artifacts were regenerated equivalently, because
re-clustering calls a nondeterministic live embedding service. The accepted design is controlled
capture of L1/code/config/backend provenance plus an ID-keyed embedding snapshot, then CI-only
offline replay and canonical L2 comparison. **CI must NEVER call the HTTP embedding backend.**

DO:
 1. Define `pipeline/L2/embedding-snapshot.json`: L1 id -> vector, plus backend and model identity
    (name, version/revision, dimensionality) so a snapshot taken against a different backend is
    detectably different rather than silently substituted. Document the schema.
 2. Refactor `pipeline/cluster.py` to accept a PRE-COMPUTED matrix instead of calling the backend
    itself. The live path must keep working unchanged; this is a seam, not a rewrite.
 3. Tests, both directions: clustering from a snapshot reproduces the same partition as clustering
    from the equivalent live vectors; and a snapshot whose backend identity does not match the
    declared one is REJECTED loudly rather than used.
 4. A snapshot missing an L1 id present in the corpus, or carrying an id absent from it, must fail
    loudly and name the ids -- never silently cluster a subset. Zero overlap must ALARM, not pass.

DO NOT: wire anything into `.github/workflows/`, write the capture task, or write the replay
comparator -- those are packets 30-2, 30-3 and 30-4.

hindsight uses clearwatch as the dedup ENGINE only: no Qdrant, no sentence-transformers, no sklearn.

VERIFY: the full baselines; and demonstrate with actual output that clustering from a snapshot and
from live vectors agree, and that a mismatched-backend snapshot is refused.

Your FINAL line must be exactly: VERDICT: CONFIRMED_GOOD  or  VERDICT: DEFECTIVE
