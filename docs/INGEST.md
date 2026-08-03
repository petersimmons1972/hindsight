# Ingesting a failure mode

Use `bin/add-failure-mode.sh`; never assign an `FM-NNN` identifier or edit the
append-only ledger by hand.

Every add begins with a ranked corpus lookup. The result is advisory: the
header explicitly says the lookup does not determine duplication, and a
populated corpus with no candidates is a successful measurement. Missing,
empty, or unreadable corpus input is an operational error and stops the add.

After reviewing the candidates, record one of the two accepted decisions:

```bash
bin/add-failure-mode.sh -c A "failure description" --recurrence-of c-001
bin/add-failure-mode.sh -c A "failure description" --recurrence-of none
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

## `first_seen` and its provenance

Every L1 row carries a `first_seen` field (issue #32). It is dated one of two
ways, in priority order, by `pipeline/repair_first_seen.py`:

- **`git-anchor`** -- the row's `source_anchor` text was found, via
  `conf/source-roots.conf`, in the commit that first introduced it into the
  source repo's file (`git log --reverse -S<anchor>`, oldest match). This
  dates the moment the lesson entered its *source*.
- **`l1-ingest-fallback`** -- used only when the anchor lookup can't resolve
  (source root absent, path never existed, or the anchor text isn't literally
  present, e.g. a paraphrased or synthesized label). Falls back to the first
  commit, in this checkout, that introduced the row's own id into its
  `pipeline/L1/<source>.jsonl`. This dates when the entry entered *hindsight*,
  which can be considerably later than the source event -- never conflate the
  two provenances when reasoning about corpus timing.

A row that resolves under neither path is left with no `first_seen` and no
`first_seen_provenance` key -- an honest gap, never a fabricated date. Rows
that already carried `first_seen` before a repair run are left byte-for-byte
untouched and gain no provenance key.

Re-run with `python3 pipeline/repair_first_seen.py` after adding sources whose
roots weren't previously checked out; it only touches rows still missing
`first_seen`. On success it reports on stderr:

- three `date-repair:` count lines (`DATED-BY-ANCHOR`, `DATED-BY-FALLBACK`,
  `STILL-UNDATED`);
- a two-line fairness DIFFERENTIAL between the Arm B intervention-family
  clusters and the comparator-pool clusters, split by provenance
  (`pre-existing` / `git-anchor` / `l1-ingest-fallback` / `undated`), each
  with a `pre-dated` percentage -- report only, not a fix. This is measured
  **only** when the run's target is the real corpus directory
  (`pipeline/L1` under `--self-dir`); any other `--l1` target prints
  `DIFFERENTIAL: NOT MEASURED (target is not the corpus)` rather than a
  number computed from whatever happens to be in an unrelated directory;
- a `WARNING:` line, naming the share, whenever more than half of the rows
  dated *this run* used `l1-ingest-fallback` -- that share is an ingest-time
  date, not a recovered logging date, and must not be silently averaged into
  a "first_seen" that reads as one.

On the real corpus, only ~10% of previously-undated rows recovered a true
git-anchor date (24 of 242); the other ~90% (218) fall back to when the row
entered *hindsight*, which clusters at corpus-construction time. The
`first_seen` denominator is therefore mostly ingest-dated, not source-dated
-- an honest outcome of ruling R-c, not a defect, but state it loudly
wherever these dates are consumed.

If any input file fails to read (missing, empty, or malformed JSON), the tool
prints the `ERROR:` and a single `date-repair: NOT MEASURED` line in place of
the three counts and the DIFFERENTIAL -- never a zero count, which would be
indistinguishable from a genuine all-zero successful run -- and exits
non-zero.
