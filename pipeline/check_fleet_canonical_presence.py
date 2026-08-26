#!/usr/bin/env python3
"""Fail loudly for refreshed fleet records that have no exact catalog title.

This is intentionally a watchdog, not an importer.  A literal title mismatch
is a review queue: it proves no exact canonical entry was found, but does not
claim that a differently worded canonical row is semantically distinct.
"""
from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from pipeline import extract_fleet_l1
else:  # Direct invocation: Python puts pipeline/, not the repo root, on sys.path.
    import extract_fleet_l1


REPO = Path(__file__).resolve().parents[1]
PARENT = REPO.parent
SOURCES = (
    ("fleet-main", PARENT / "fleet" / "FAILURE-MODES.md", REPO / "pipeline/L1/fleet-main.jsonl"),
    ("fleet-orch", PARENT / "fleet" / "orchestration/FAILURE-MODES.md", REPO / "pipeline/L1/fleet-orch.jsonl"),
    ("fleet-orch", PARENT / "fleet" / "CODING-INVARIANTS.md", REPO / "pipeline/L1/fleet-orch.jsonl"),
    ("fleet-orch", PARENT / "fleet" / "CODING-FAILURE-MODES.md", REPO / "pipeline/L1/fleet-orch.jsonl"),
)


def _unreviewed_l1_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    records = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {str(record.get("id", "")) for record in records if record.get("canonical_status") == "unreviewed"}


def check_sources(sources: list[tuple[str, Path, Path]] | tuple[tuple[str, Path, Path], ...], catalog: Path) -> int:
    catalog_text = catalog.read_text(encoding="utf-8").casefold()
    failures = 0
    for slug, source, l1_path in sources:
        ids = _unreviewed_l1_ids(l1_path)
        namespace = "fleet" if slug == "fleet-main" else "fleet-orch"
        for mode in extract_fleet_l1.parse_source(source):
            record_id = f"{namespace}-{mode.local_id}"
            # Only the records introduced to resolve #106 carry an explicit
            # canonical-review obligation. Older L1 history has no such claim.
            if record_id not in ids:
                continue
            if mode.title.casefold() in catalog_text:
                continue
            print(f"{slug}:{mode.local_id} L1=COVERED CATALOG=ABSENT title={mode.title!r}")
            failures += 1
    print(f"CANONICAL-{'SHORT' if failures else 'COMPLETE'}: {failures}")
    return 1 if failures else 0


def main() -> int:
    return check_sources(SOURCES, REPO / "catalog/failure-modes.md")


if __name__ == "__main__":
    raise SystemExit(main())
