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
from pathlib import Path

P = Path("/home/psimmons/projects")
OUT = P / "hindsight/pipeline/L1"
OUT.mkdir(parents=True, exist_ok=True)


def emit(slug: str, records: list[dict]) -> None:
    (OUT / f"{slug}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    print(f"  {slug:<26} {len(records):>4} entries")


# ---- 1. the canonical catalog (markdown table) --------------------------------
cat = P / "hindsight/catalog/failure-modes.md"
row_re = re.compile(r"^\| (FM-\d{2,3}) \|")
records = []
for n, line in enumerate(cat.read_text(encoding="utf-8").splitlines(), 1):
    if not row_re.match(line):
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    # Not every row has all 5 columns -- the rescued FM-135..145 rows carry 4
    # (they predate the Auto? column). An earlier version `continue`d past short
    # rows and silently dropped 14 entries, including the ones just recovered.
    # Never skip a row you matched: pad it, and fail loud on anything unusable.
    if len(cells) < 4:
        raise SystemExit(f"ABORT: unparseable catalog row at line {n}: {line[:120]}")
    cells += [""] * (5 - len(cells))
    fm, klass, instance, check, auto = cells[:5]
    records.append({
        "id": f"hc-{fm}",
        "source_path": "hindsight/catalog/failure-modes.md",
        "source_anchor": f"line {n}",
        "class_hint": klass,
        "instance": instance,
        "check": check or None,
        "enforcement": None,          # the column is prose, not a path: honest null
        "auto": "machine" if "🤖" in auto else "judgment",
        "first_seen": None,
    })
emit("homelab-canon", records)

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
