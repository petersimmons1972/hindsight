# Ingesting a failure mode

Use `bin/add-failure-mode.sh`; never assign an `FM-NNN` identifier or edit the
append-only ledger by hand.

Every add begins with a ranked corpus lookup. The result is advisory: the
header explicitly says the lookup does not determine duplication, and a
populated corpus with no candidates is a successful measurement. Missing,
empty, or unreadable corpus input is an operational error and stops the add.

After reviewing the candidates, record a recurrence decision and a disposition
(`mechanize`, `brief-inject`, or `advisory`). `--disposition` is required.
`--recurrence-of c-NNN` names a cluster id and force-promotes the disposition
to `mechanize` regardless of the flag; `--recurrence-of none` does not.

```bash
bin/add-failure-mode.sh -c A "failure description" --disposition advisory --recurrence-of c-001
bin/add-failure-mode.sh -c A "failure description" --disposition advisory --recurrence-of none
```

Omitting `--recurrence-of`, or passing anything except `c-NNN` or `none`, exits
without changing the catalog or ledger. Similarity never rejects an entry and
there is no threshold or override flag.

Before writing, the command prints an `UNDO:` command backed by a journal in
the system temporary directory. Running that command restores the catalog,
ledger, mechanically extracted L1 files, and L2 cluster artifact to their
pre-add state. Restore first validates the complete manifest and stages a
recovery copy of every current target. If applying any journal entry fails, it
compensates across the whole target set so catalog, ledger, L1, and L2 cannot be
left in a mixed state. Recovery copies are retained and named if either apply
or compensation reports an error.

Canonical ingest requires the sibling repositories used by extraction and
reconciliation (`fleet`, `fleet-dispatch`, and `claude-codex`) beside the
`hindsight` checkout. The command resolves catalog aliases before deciding
whether this is a canonical run and checks every required sibling source before
creating an undo journal or writing. A standalone checkout therefore fails
loudly with the missing paths and leaves the catalog and ledger untouched.

For `--recurrence-of c-NNN`, the ID must already exist in
`pipeline/L2/clusters.jsonl` (or the `CLUSTERS` environment override). A
well-formed but unknown cluster ID is an error and does not write.

For the canonical catalog, one invocation completes the full loop in order:

1. append the catalog row and ledger ID;
2. run the mechanical L1 extractor;
3. regenerate L2 with the repository's configured default backend;
4. run reconciliation and require its successful exit.

When the catalog or ledger changes, the repository pre-commit hook runs the
same guard, extraction, L2, and reconciliation sequence so partial ingest state
cannot be committed. If regeneration changes a required derived artifact, the
hook exits nonzero and requires these exact files to be reviewed and staged:

```bash
git add pipeline/L1/homelab-canon.jsonl \
  pipeline/L1/fleet-dispatch-schema.jsonl \
  pipeline/L2/clusters.jsonl
```

Retry the commit after staging them. Other commits run the guard without
rewriting derived artifacts.
