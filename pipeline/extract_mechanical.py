#!/usr/bin/env python3
"""Deterministic L1 extraction for machine-enumerable sources.

The first pass sent a model at these and lost data: the catalog agent produced
nothing at all, and fleet-dispatch returned 2 of 10 enum classes. Both sources
are fully structured -- a markdown table and a SQL CHECK constraint -- so their
content is recoverable by parsing. A model adds nothing here except the
opportunity to silently drop rows.

Rule this encodes: if the structure already determines the answer, do not ask a
model for it. Reserve model extraction for genuinely unstructured prose.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Resolve from this file, never from a fixed home directory. reconcile_l1.py
# shipped with `/home/psimmons/projects` baked in, resolved zero sources on CI,
# and printed COMPLETE anyway (plan row V12). This module had the identical
# defect: on any checkout not at that exact path it silently wrote its L1 output
# into someone else's tree, or nowhere useful at all.
REPO = Path(__file__).resolve().parents[1]
P = REPO.parent
OUT = REPO / "pipeline/L1"
OUT.mkdir(parents=True, exist_ok=True)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.reconcile_l1 import parse_catalog_rows


def emit(slug: str, records: list[dict], preserve_prefix: str | None = None) -> None:
    """Write records, PRESERVING any existing entry this extractor cannot produce.

    The catalog parser only sees `| FM-NNN |` table rows. Narrative content (case
    studies, standalone bullets) has no table row and was recovered by a model
    pass. A plain overwrite silently dropped those 4 entries on every re-run --
    the same silent-drop defect this pipeline exists to catch. Anything whose id
    does not match this extractor's own prefix is carried forward untouched.
    """
    path = OUT / f"{slug}.jsonl"
    carried: list[dict] = []
    if preserve_prefix and path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if not str(rec.get("id", "")).startswith(preserve_prefix):
                carried.append(rec)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records + carried)
    )
    note = f" (+{len(carried)} preserved)" if carried else ""
    print(f"  {slug:<26} {len(records):>4} entries{note}")


# ---- 1. the canonical catalog (markdown table) --------------------------------
cat = REPO / "catalog/failure-modes.md"
records = []
for row in parse_catalog_rows(cat.read_text(encoding="utf-8")):
    records.append({
        "id": f"hc-{row.fm_id}",
        "source_path": "hindsight/catalog/failure-modes.md",
        "source_anchor": f"line {row.line_number}",
        "class_hint": row.class_hint,
        "instance": row.instance,
        "check": row.check,
        "enforcement": None,          # the column is prose, not a path: honest null
        "auto": row.l1_fields()["auto"],
        "first_seen": None,
    })
emit("homelab-canon", records, preserve_prefix="hc-FM-")

# ---- 2. fleet-dispatch failure_class enum (SQL CHECK constraint) --------------
sql = P / "fleet-dispatch/migrations/0017_failure_class.sql"
text = sql.read_text(encoding="utf-8")
values = re.findall(r"'([a-z][a-z_]{3,})'", text)
seen, ordered = set(), []
for v in values:
    if v not in seen:
        seen.add(v)
        ordered.append(v)
records = [{
    "id": f"fd-{v}",
    "source_path": "fleet-dispatch/migrations/0017_failure_class.sql",
    "source_anchor": f"failure_class enum value '{v}'",
    "class_hint": "dispatch failure class",
    "instance": f"Dispatch runs terminate with failure_class='{v}'; the schema "
                f"enumerates this as a distinct, DB-enforced failure category.",
    "check": "CHECK constraint on failure_class restricts values to this enum",
    "enforcement": {"file": "fleet-dispatch/migrations/0017_failure_class.sql",
                    "kind": "schema"},
    "auto": "machine",
    "first_seen": None,
} for v in ordered]
emit("fleet-dispatch-schema", records)
