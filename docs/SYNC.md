# Syncing the failure-mode catalog

`bin/sync-failure-modes.sh` distributes the canonical
`catalog/failure-modes.md` to an explicit list of consumer repositories.  It
never has a default consumer list: this prevents a typo from targeting the
fleet.

Create a consumer file from
`bin/failure-modes-projects.conf.example`, with one absolute repository path
per line. Blank lines and `#` comments are ignored.

The default is a safe dry-run:

```bash
bash bin/sync-failure-modes.sh --consumers /tmp/consumers.conf
```

To write, add `--apply`; use it only after reviewing the dry-run and only with
disposable fixtures during development:

```bash
bash bin/sync-failure-modes.sh --apply --consumers /tmp/consumers.conf
```

Each consumer receives a namespaced copy at
`docs/vendor/hindsight/failure-modes.md`, never at a bare `docs/` path.  An
existing target without the Hindsight ownership marker is refused rather than
overwritten.

Before its first write, an apply run creates an undo journal and prints its
path on stderr. The journal records every target's prior state (`absent`,
`untracked`, or `tracked+hash`) and keeps a backup for existing files. Restore
the exact prior target contents with:

```bash
bash bin/sync-failure-modes.sh --undo /tmp/hindsight-sync-undo.XXXXXX/journal.tsv
```
