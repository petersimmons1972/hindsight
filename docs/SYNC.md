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

Each consumer receives a namespaced copy only when the resolved destination is
the *exact* expected path under that consumer's resolved root:
`docs/vendor/hindsight/failure-modes.md`. This is intentionally stricter than
ordinary containment: an ancestor symlink is refused even when it happens to
resolve inside the consumer. An existing target without the Hindsight ownership
marker is refused rather than overwritten.

After that identity check, writes and restores use a descriptor-relative helper:
it opens the verified consumer tree without following links, creates a temporary
file relative to the verified parent directory descriptor, sets the recorded
mode, fsyncs it, and renames it relative to that same descriptor. It therefore
does not re-walk the target path by name after validation.

Before its first write, an apply run creates an undo journal and prints its
path on stderr. It records each consumer's resolved target, state (`absent`,
`untracked`, `tracked+hash`, `tracked+link`, `directory`, or `invalid`), backup
path where one is safe to create, and prior mode. Refused entries are recorded
as such, not claimed to have a restorable prior state. `--undo` rechecks that
each recorded target still has the exact expected identity under its recorded
consumer root; it refuses non-zero if a later path swap makes that false.
Regular-file restores preserve the recorded mode. Apply refuses symbolic links,
hardlinked files, directories, FIFOs, devices, sockets, and any target that
fails the strict identity check.

Restore the recorded target entries with:

```bash
bash bin/sync-failure-modes.sh --undo /tmp/hindsight-sync-undo.XXXXXX/journal.tsv
```
