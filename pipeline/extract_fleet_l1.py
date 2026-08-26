#!/usr/bin/env python3
"""Refresh enumerable fleet failure modes into L1 without inventing a canon row.

The source registries use headings plus labelled prose.  Their local identifiers
are not globally unique (for example, CI-18 names different source records), so
L1 IDs retain a source namespace.  Newly recovered records are explicitly
``canonical_status: unreviewed``: this is a provenance fact, not an implicit
decision to import them into the canonical catalog.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PARENT = REPO.parent
L1 = REPO / "pipeline" / "L1"
HEADING = re.compile(r"^#{2,4} +((?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?)\s*(?:—\s*(.*))?$")
LABELLED = re.compile(r"^- \*\*(Lie|Countermeasure):\*\*\s*(.*)$", re.M)
LOCAL_ID = re.compile(r"(?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?")


@dataclass(frozen=True)
class SourceMode:
    local_id: str
    title: str
    lie: str
    countermeasure: str


def _collapse(text: str) -> str:
    return " ".join(text.split())


def parse_source(path: Path) -> list[SourceMode]:
    """Parse heading-delimited source records and retain their actionable prose."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    modes: list[SourceMode] = []
    for index, line in enumerate(lines):
        match = HEADING.match(line)
        if not match:
            continue
        end = next(
            (later for later in range(index + 1, len(lines)) if HEADING.match(lines[later])),
            len(lines),
        )
        fields = {name: _collapse(value) for name, value in LABELLED.findall("\n".join(lines[index + 1:end]))}
        local_id = match.group(1)
        title = (match.group(2) or local_id).strip()
        modes.append(SourceMode(local_id, title, fields.get("Lie", title), fields.get("Countermeasure", "")))
    return modes


def _existing_local_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            found.update(LOCAL_ID.findall(line))
    return found


def refresh_one(source: Path, l1_path: Path, namespace: str, source_path: str | None = None) -> int:
    """Append source records that L1 does not already represent; return their count."""
    existing = _existing_local_ids(l1_path)
    relative_source = source_path or f"{source.parent.name}/{source.name}"
    additions = []
    for mode in parse_source(source):
        if mode.local_id in existing:
            continue
        additions.append({
            "id": f"{namespace}-{mode.local_id}",
            "source_path": relative_source,
            "source_anchor": f"{mode.local_id} — {mode.title}",
            "instance": mode.lie,
            "check": mode.countermeasure or None,
            "enforcement": None,
            "auto": "judgment",
            "first_seen": None,
            "canonical_status": "unreviewed",
        })
        existing.add(mode.local_id)
    if additions:
        l1_path.parent.mkdir(parents=True, exist_ok=True)
        with l1_path.open("a", encoding="utf-8") as handle:
            for record in additions:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(additions)


SOURCES = (
    ("fleet-main", PARENT / "fleet" / "FAILURE-MODES.md", L1 / "fleet-main.jsonl", "fleet", "fleet/FAILURE-MODES.md"),
    ("fleet-orch", PARENT / "fleet" / "orchestration" / "FAILURE-MODES.md", L1 / "fleet-orch.jsonl", "fleet-orch", "fleet/orchestration/FAILURE-MODES.md"),
    ("fleet-orch", PARENT / "fleet" / "CODING-INVARIANTS.md", L1 / "fleet-orch.jsonl", "fleet-orch", "fleet/CODING-INVARIANTS.md"),
    ("fleet-orch", PARENT / "fleet" / "CODING-FAILURE-MODES.md", L1 / "fleet-orch.jsonl", "fleet-orch", "fleet/CODING-FAILURE-MODES.md"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="append missing records to committed L1 files")
    args = parser.parse_args()
    missing = []
    for slug, source, l1_path, namespace, source_path in SOURCES:
        count = len(set(mode.local_id for mode in parse_source(source)) - _existing_local_ids(l1_path))
        missing.append((slug, source_path, count, source, l1_path, namespace))
    if not args.write:
        for slug, source_path, count, *_ in missing:
            if count:
                print(f"SHORT: {slug} has {count} source IDs absent from {source_path}'s L1 extract")
        return 1 if any(count for _, _, count, *_ in missing) else 0
    total = 0
    for slug, source_path, _count, source, l1_path, namespace in missing:
        added = refresh_one(source, l1_path, namespace, source_path)
        total += added
        print(f"REFRESHED: {slug} {source_path}: {added} records appended")
    print(f"REFRESHED TOTAL: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
