#!/usr/bin/env python3
"""synthesize-pointer.py — build the small curated pointer files from
catalog/criticality.jsonl.

Read-only over criticality.jsonl and catalog/failure-modes.md. Writes ONLY
docs/POINTER.md (CRITICAL tier) and docs/HIGH.md (HIGH tier).

Two files, not one, because the two tiers are consumed differently:
  - POINTER.md is small by construction (CRITICAL is rare) and is meant to be
    loaded at session start.
  - HIGH.md is real signal but too large to preload safely -- it is meant to
    be reached ONLY through bin/query-failure-modes.sh, never opened whole.

Deterministic: re-running on unchanged input produces byte-identical output.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CRITICALITY = REPO_ROOT / "catalog" / "criticality.jsonl"
CATALOG = REPO_ROOT / "catalog" / "failure-modes.md"
POINTER_OUT = REPO_ROOT / "docs" / "POINTER.md"
HIGH_OUT = REPO_ROOT / "docs" / "HIGH.md"

ROW_RE = re.compile(r"^\|\s*(FM-\d+)\s*\|(.*)\|\s*([^|]*)\|\s*([^|]*)\|\s*$")


def load_checks() -> dict[str, str]:
    """Map fm_id -> the catalog row's 'Check that catches it' text."""
    checks: dict[str, str] = {}
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| FM-"):
            continue
        fields = [f.strip() for f in line.strip().strip("|").split("|")]
        if len(fields) < 4:
            continue
        fm_id = fields[0]
        check = fields[-2]
        checks[fm_id] = check
    return checks


def render(entries: list[dict], checks: dict[str, str]) -> list[str]:
    def sort_key(e: dict) -> tuple:
        generality_rank = 0 if e["generality"] == "BROAD" else 1
        return (generality_rank, int(e["fm_id"].split("-")[1]))

    lines = []
    for e in sorted(entries, key=sort_key):
        check = checks.get(e["fm_id"], "(check text not found in catalog)")
        lines.append(f"- **{e['fm_id']}** [{e['generality']}] {check}")
    return lines


def main() -> int:
    if not CRITICALITY.exists():
        print(f"ERROR: {CRITICALITY} not found", file=sys.stderr)
        return 1

    latest: dict[str, dict] = {}
    for line in CRITICALITY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        # A later line for the same fm_id supersedes an earlier one (re-triage).
        latest[row["fm_id"]] = row

    checks = load_checks()
    critical = [r for r in latest.values() if r["tier"] == "CRITICAL"]
    high = [r for r in latest.values() if r["tier"] == "HIGH"]
    # Clusters aid discovery, but a tiered pointer is a retrieval contract:
    # collapsing it to cluster representatives can make a real HIGH/CRITICAL
    # row unreachable.  Keep every current tiered row visible.

    POINTER_OUT.parent.mkdir(parents=True, exist_ok=True)
    HIGH_OUT.parent.mkdir(parents=True, exist_ok=True)

    pointer_lines = [
        "# hindsight — CRITICAL pointer",
        "",
        "Curated from `catalog/criticality.jsonl` by `bin/synthesize-pointer.py`. "
        "Do not edit by hand -- edit criticality.jsonl and re-run the script.",
        "",
        f"{len(critical)} CRITICAL failure modes (irreversible/destructive blast radius if repeated). "
        "Safe to load at session start.",
        "",
        *render(critical, checks),
        "",
        "For HIGH-tier entries (real but too numerous to preload), use "
        "`bin/query-failure-modes.sh <keyword>` -- do not open docs/HIGH.md directly.",
        "",
    ]
    POINTER_OUT.write_text("\n".join(pointer_lines), encoding="utf-8")

    high_lines = [
        "# hindsight — HIGH pointer (QUERY ONLY -- do not load this file whole)",
        "",
        "Curated from `catalog/criticality.jsonl` by `bin/synthesize-pointer.py`. "
        "Do not edit by hand -- edit criticality.jsonl and re-run the script.",
        "",
        f"{len(high)} HIGH-tier failure modes (correctness/trust failures, non-destructive, "
        "or mechanizable-but-not-yet-mechanized). This file is intentionally NOT referenced "
        "from MEMORY.md and should never be Read/cat'd whole -- reach it only through "
        "`bin/query-failure-modes.sh <keyword>`, which greps this file and caps output at "
        "10 matching lines.",
        "",
        *render(high, checks),
        "",
    ]
    HIGH_OUT.write_text("\n".join(high_lines), encoding="utf-8")

    print(f"POINTER.md: {len(critical)} CRITICAL entries")
    print(f"HIGH.md: {len(high)} HIGH entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
