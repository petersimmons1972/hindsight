# docs/ — superseded-doc index

Maintained by A3 (parallel-2026-08-24 leaf, per `research-probes/r9/FINDINGS.md`'s doc-claim
falsity measurement). A3 supersedes in place — it never deletes. Each row below points from a
doc carrying a stale, checkable claim to what is now authoritative. The doc itself still has a
`SUPERSEDED` header (first 8 lines) with the same information.

| Superseded doc | What was false | Replacement / authority |
|---|---|---|
| `docs/POINTER.md` | FM-361 claims catalog-guard's CI is "persistently red on main" | `gh-run-list--branch-main(catalog-guard-green)` |

Scoped: only FM-361 within `docs/POINTER.md` is superseded — the rest of that pointer file is
unaffected.

See `safety/a3/SUPERSEDED.tsv` (in `ops-plans/parallel-2026-08-24`) for the full manifest with
`pre_sha` recoverability anchors.
