# C3 — Duplicate-cause guard

## Context

This packet is the reason the repository exists.

Today `guard/failure_mode_catalog_guard.py` validates that catalog IDs are unique and
well-formed. It has **zero semantic awareness** of what an entry says. A person can
rediscover a known failure, write it up in fresh words, file it as a new ID, and the
guard passes it clean. That is exactly how "trust the completion signal" was logged
seven separate times: nothing in the system could say *we already know this*.

You are building the check that says it.

## Files

- **Modify** `guard/failure_mode_catalog_guard.py` — add the new modes.
- **Create** `guard/tests/test_duplicate_cause.py`.
- **Extend** `guard/tests/test_failure_mode_catalog_guard.bats` if the hook path changes.
- **Reuse, do not duplicate**, the backend/similarity code from `pipeline/cluster.py`
  (packet C1). Import it. A second copy of similarity logic in this repo would recreate
  the divergence the repo was founded to end.

## Behaviour

New flag `--check-duplicate-cause [--entry-text "<text>" | --entry-file <path>]`:

1. Embed the proposed entry using the same backend selection as C1.
2. Compare against `pipeline/L2/clusters.jsonl`.
3. On a match above threshold, **exit non-zero** and print, to stderr:

```
FM-GUARD: proposed entry matches existing cluster
  cosine 0.91 -> fleet-OPS-11, fleet-OPS-21, fleet-OPS-28 (completion-signal)
  This root cause has been logged 7 times.
Commit REJECTED.
Override: add --force-new-cause="<why this differs>"
```

The message must name the matching member IDs and the cluster's recurrence count. A
rejection that does not tell you *what* it matched is a rejection people learn to
bypass rather than read.

4. `--force-new-cause="<justification>"` overrides the rejection, exits 0, and **records
   the justification durably** — append to `pipeline/L2/forced-causes.jsonl` with the
   proposed text, the cluster it matched, the similarity score, the justification, and
   a timestamp taken from the system clock at call time.

The override must never be silently discarded. A forced split that leaves no trace is
indistinguishable from the guard not having run, and will resurface in the next
recurrence report as an unexplained duplicate.

5. Wire `--check-duplicate-cause` into `.githooks/pre-commit` so it runs on staged
   catalog additions. Existing guard behaviour (uniqueness fatal, ordering advisory,
   legacy-scheme on row IDs) must be preserved exactly — its contract tests already pin
   both directions and must continue to pass untouched.

## Acceptance (TDD)

Gate: `python3 -m pytest guard/tests/ -q && bats guard/tests/*.bats`

Required assertions — **both directions of the rule, per the repo's own
`lesson-a-fix-can-invert-the-error`**:

1. **True positive** — take a real entry from `pipeline/L1/`, reword it substantially
   (different vocabulary, same root cause), and assert the guard REJECTS it and names
   the correct cluster. Draw the source entry from a family in
   `pipeline/tests/fixtures/recurrence_ground_truth.json` so the expected cluster is
   known independently of your implementation.
2. **True negative** — a genuinely novel failure mode, unrelated to anything in the
   corpus, must be ACCEPTED. A guard that rejects everything is not a guard; it is an
   outage, and it will be disabled within a day.
3. **Override works** — `--force-new-cause` on a matching entry exits 0.
4. **Override is recorded** — after an override, `forced-causes.jsonl` contains the
   justification, the matched cluster, and the score. Assert on the file contents, not
   on the exit code.
5. **Override requires a reason** — `--force-new-cause` with an empty or whitespace-only
   justification is rejected. An override that accepts `""` is not an override, it is an
   off switch.
6. **Existing contract intact** — the current 7 pytest and 2 bats tests still pass
   unchanged.

Write test 2 with real care. The failure mode of this packet is a guard tuned so tight
that it blocks legitimate new entries — which produces exactly one outcome: someone
disables it, and the registry silently reverts to being a diary.

## Constraints

- Threshold must be configurable and its default justified in the docstring with the
  measured numbers you used to pick it.
- The guard must work when the HTTP embedding backend is unreachable (CI case). Falling
  back is fine; failing *open* is not. If no backend is available at all, exit non-zero
  with a clear message rather than passing the entry through unchecked.
- Never edit `pipeline/tests/fixtures/`.

## Out of scope

- Clustering itself (C1) and the report (C2).
- Enforcement verification (C4).

## Model

`--harness codex --effort high`. Cross-vendor adversarial review is mandatory for this
packet; the reviewer will be told by name to find both inversions.
