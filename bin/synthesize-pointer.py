#!/usr/bin/env python3
"""synthesize-pointer.py — build the small curated pointer files from
catalog/criticality.jsonl.

Read-only over criticality.jsonl, catalog/failure-modes.md, and
pipeline/L2/clusters.jsonl. Writes ONLY docs/POINTER.md (CRITICAL tier) and
docs/HIGH.md (HIGH tier).

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
CLUSTERS = REPO_ROOT / "pipeline" / "L2" / "clusters.jsonl"
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


def load_cluster_map() -> tuple[dict[str, str], dict[str, str]]:
    """Return (fm_id -> cluster_id, cluster_id -> representative_fm_id)."""
    fm_to_cluster: dict[str, str] = {}
    cluster_rep: dict[str, str] = {}
    if not CLUSTERS.exists():
        return fm_to_cluster, cluster_rep
    for line in CLUSTERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cluster_id = row.get("cluster_id")
        if not isinstance(cluster_id, str):
            continue
        for member in row.get("members", []):
            if isinstance(member, str) and member.startswith("hc-FM-"):
                fm_to_cluster[member[len("hc-"):]] = cluster_id
        rep = row.get("representative")
        if isinstance(rep, str) and rep.startswith("hc-FM-"):
            cluster_rep[cluster_id] = rep[len("hc-"):]
    return fm_to_cluster, cluster_rep


def dedup_family(entries: list[dict], fm_to_cluster: dict[str, str], cluster_rep: dict[str, str]) -> list[dict]:
    """Collapse entries that share a cluster to one representative (issue #113)."""
    by_cluster: dict[str, list[dict]] = {}
    singles: list[dict] = []
    for e in entries:
        cluster_id = fm_to_cluster.get(e["fm_id"])
        if cluster_id is None:
            singles.append(e)
        else:
            by_cluster.setdefault(cluster_id, []).append(e)

    kept = list(singles)
    for cluster_id, members in by_cluster.items():
        if len(members) == 1:
            kept.append(members[0])
            continue
        rep_id = cluster_rep.get(cluster_id)
        chosen = next((m for m in members if m["fm_id"] == rep_id), None)
        if chosen is None:
            chosen = min(members, key=lambda m: int(m["fm_id"].split("-")[1]))
        kept.append(chosen)
    return kept


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
    fm_to_cluster, cluster_rep = load_cluster_map()

    critical = [r for r in latest.values() if r["tier"] == "CRITICAL"]
    high = [r for r in latest.values() if r["tier"] == "HIGH"]

    critical = dedup_family(critical, fm_to_cluster, cluster_rep)
    high = dedup_family(high, fm_to_cluster, cluster_rep)

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
