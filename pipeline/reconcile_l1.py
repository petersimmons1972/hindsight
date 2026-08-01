#!/usr/bin/env python3
"""Mechanically reconcile L1 extraction against ground truth.

Why this exists
---------------
The first L1 extraction pass reported success on every source, and was lossy:
fleet-main returned 78 of 102 entries, fleet-dispatch 2 of 10. Nothing failed;
each agent reported a count that looked plausible on its own.

That is the registry's own headline failure mode -- a proxy (the agent's
self-reported count) trusted in place of the thing (actual coverage). So
coverage is not asked for, it is COMPUTED: ground-truth IDs are extracted from
each source by regex, and any ID absent from the JSONL is reported. Sources whose
entries are machine-enumerable are extracted mechanically outright -- no model in
the loop -- because their structure already encodes the answer.

Usage:  python3 reconcile_l1.py [--json]
Exit 1 if any enumerable source is short.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

P = Path("/home/psimmons/projects")
L1 = P / "hindsight/pipeline/L1"

# source slug -> (file(s), regex capturing the ground-truth local ID)
ENUMERABLE = {
    "fleet-main": ([P / "fleet/FAILURE-MODES.md"],
                   re.compile(r"^#{2,4} +((?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?)")),
    "fleet-orch": ([P / "fleet/orchestration/FAILURE-MODES.md",
                    P / "fleet/CODING-INVARIANTS.md",
                    P / "fleet/CODING-FAILURE-MODES.md"],
                   re.compile(r"^#{2,4} +((?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?)")),
    "homelab-canon": ([P / "hindsight/catalog/failure-modes.md"],
                      re.compile(r"^\| (FM-\d{2,3}) \|")),
    "claude-codex-integration": ([P / "claude-codex/docs/integration-failure-modes.md"],
                                 re.compile(r"^#{2,4} +(FM-\d{2,3})")),
    "fleet-dispatch-schema": ([P / "fleet-dispatch/migrations/0017_failure_class.sql"],
                              re.compile(r"'([a-z_]{4,})'")),
}


def ground_truth(slug: str) -> set[str]:
    files, rx = ENUMERABLE[slug]
    ids: set[str] = set()
    for f in files:
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = rx.match(line) if rx.pattern.startswith("^") else None
            if m:
                ids.add(m.group(1))
            elif not rx.pattern.startswith("^"):
                ids.update(rx.findall(line))
    return ids


def extracted(slug: str) -> tuple[set[str], int]:
    f = L1 / f"{slug}.jsonl"
    if not f.exists():
        return set(), 0
    found: set[str] = set()
    n = 0
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        n += 1
        d = json.loads(line)
        # Search the WHOLE record, not just `id`. An earlier version searched only
        # the id field for snake_case and reported a false 0% on fleet-dispatch --
        # a validator that fails ground truth is worse than no validator.
        blob = " ".join(str(d.get(k, "")) for k in
                        ("id", "source_anchor", "instance", "check"))
        found.update(re.findall(r"(?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?", blob))
        found.update(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", blob))
    return found, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report, short = [], False
    for slug in ENUMERABLE:
        truth = ground_truth(slug)
        found, n_lines = extracted(slug)
        missing = sorted(truth - found)
        cov = (len(truth) - len(missing)) / len(truth) * 100 if truth else 100.0
        if missing:
            short = True
        report.append({"slug": slug, "ground_truth": len(truth), "jsonl_lines": n_lines,
                       "covered": len(truth) - len(missing), "coverage_pct": round(cov, 1),
                       "missing": missing})

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'source':<28}{'truth':>6}{'lines':>7}{'cov':>7}  missing")
        for r in report:
            m = ", ".join(r["missing"][:6]) + (" ..." if len(r["missing"]) > 6 else "")
            print(f"{r['slug']:<28}{r['ground_truth']:>6}{r['jsonl_lines']:>7}"
                  f"{r['coverage_pct']:>6.1f}%  {m}")
        n_missing = sum(len(r["missing"]) for r in report)
        print(f"\n{'SHORT' if short else 'COMPLETE'}: {n_missing} enumerable entries unaccounted for")
        print(
            "\nSCOPE LIMIT -- read this before trusting the word COMPLETE:\n"
            "  This checks only entries with a machine-detectable ID. Narrative content\n"
            "  (case studies, standalone bullets, prose lessons) carries no ID, so it is\n"
            "  invisible here and a shortfall in it CANNOT be detected by this tool.\n"
            "  This is not hypothetical: the mechanical catalog extractor missed 4 such\n"
            "  entries (2 case studies, 2 standalone bullets) while this script reported\n"
            "  100% coverage. They were recovered only because a model pass saw them.\n"
            "  COMPLETE means 'no enumerable entry is missing', never 'nothing is missing'."
        )
    return 1 if short else 0


if __name__ == "__main__":
    sys.exit(main())
