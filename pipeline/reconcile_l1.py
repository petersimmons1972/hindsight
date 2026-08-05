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

Usage:  python3 reconcile_l1.py [--json] [--allow-partial] [--source SLUG ...]
Exit 0 only for COMPLETE, or for PARTIAL when explicitly waived.

`--source` narrows the run to named sources. It exists because the corpus is a
union of five independently-owned sources, and a gate that reconciles ALL of
them is the wrong coupling for a caller that wrote ONE of them: an unrelated
sibling repo's backlog made `bin/add-failure-mode.sh` unable to add anything at
all (issue #73). Narrowing is never silent -- a scoped run prints exactly which
sources it did not look at, and an unknown slug is a hard error rather than an
empty scope that would certify nothing while exiting 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# This repo, derived from THIS FILE -- never from a hardcoded home directory.
# It was `P / "hindsight/..."`, so on any host that is not the author's
# workstation the tool could not find its own catalog or its own corpus. On CI
# that meant all five sources failed to resolve, and the `else 100.0` fail-open
# turned "nothing was compared" into COMPLETE, exit 0.
REPO = Path(__file__).resolve().parents[1]
L1 = REPO / "pipeline/L1"

# Sibling repos, which genuinely live outside this checkout. These are expected
# to be absent on CI, and are now reported UNRESOLVED rather than scored 100%.
P = REPO.parent

# source slug -> (file(s), regex capturing the ground-truth local ID)
ENUMERABLE = {
    "fleet-main": ([P / "fleet/FAILURE-MODES.md"],
                   re.compile(r"^#{2,4} +((?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?)")),
    "fleet-orch": ([P / "fleet/orchestration/FAILURE-MODES.md",
                    P / "fleet/CODING-INVARIANTS.md",
                    P / "fleet/CODING-FAILURE-MODES.md"],
                   re.compile(r"^#{2,4} +((?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?)")),
    "homelab-canon": ([REPO / "catalog/failure-modes.md"],
                      re.compile(r"^\| (FM-\d{2,3}) \|")),
    "claude-codex-integration": ([P / "claude-codex/docs/integration-failure-modes.md"],
                                 re.compile(r"^#{2,4} +(FM-\d{2,3})")),
    "fleet-dispatch-schema": ([P / "fleet-dispatch/migrations/0017_failure_class.sql"],
                              re.compile(r"'([a-z_]{4,})'")),
}


def ground_truth(slug: str) -> set[str]:
    ids, _resolved = ground_truth_resolved(slug)
    return ids


def ground_truth_resolved(slug: str) -> tuple[set[str], bool]:
    """Ground-truth IDs, plus whether ANY configured source file was present.

    The second value exists because an EMPTY id set is ambiguous: it means
    either "this source genuinely lists nothing" or "this source is not on
    disk". Collapsing those was a live fail-open -- on a CI runner none of the
    source repos exist, every truth set came back empty, coverage fell to the
    `else 100.0` branch, and the gate printed COMPLETE having verified nothing.
    """
    files, rx = ENUMERABLE[slug]
    ids: set[str] = set()
    resolved = False
    for f in files:
        if not f.exists():
            continue
        resolved = True
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = rx.match(line) if rx.pattern.startswith("^") else None
            if m:
                ids.add(m.group(1))
            elif not rx.pattern.startswith("^"):
                ids.update(rx.findall(line))
    return ids, resolved


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
    ap.add_argument(
        "--allow-partial",
        action="store_true",
        help="accept PARTIAL after printing how many sources were not checked",
    )
    ap.add_argument(
        "--source",
        action="append",
        metavar="SLUG",
        help="restrict the run to this source (repeatable). The verdict then "
             "covers only the named sources, and the scope is printed.",
    )
    args = ap.parse_args()

    selected = list(ENUMERABLE)
    if args.source:
        unknown = sorted(set(args.source) - set(ENUMERABLE))
        if unknown:
            # An unknown slug must never degrade to "checked nothing, exit 0".
            print(f"ERROR: unknown --source: {', '.join(unknown)}\n"
                  f"  known sources: {', '.join(ENUMERABLE)}", file=sys.stderr)
            return 2
        selected = [s for s in ENUMERABLE if s in set(args.source)]
    skipped = [s for s in ENUMERABLE if s not in selected]

    report, short = [], False
    n_resolved = 0
    for slug in selected:
        truth, resolved = ground_truth_resolved(slug)
        n_resolved += 1 if resolved else 0
        found, n_lines = extracted(slug)
        missing = sorted(truth - found)
        # An unresolved source scores None, never 100. Absence of a measurement
        # is not a perfect measurement.
        if not resolved:
            cov = None
        elif truth:
            cov = round((len(truth) - len(missing)) / len(truth) * 100, 1)
        else:
            cov = 100.0
        if missing:
            short = True
        report.append({"slug": slug, "ground_truth": len(truth), "jsonl_lines": n_lines,
                       "covered": len(truth) - len(missing), "coverage_pct": cov,
                       "resolved": resolved, "missing": missing})
    n_unresolved = len(selected) - n_resolved
    n_missing = sum(len(r["missing"]) for r in report)
    if n_resolved == 0:
        verdict = "UNVERIFIED"
    elif short:
        verdict = "SHORT"
    elif n_unresolved:
        verdict = "PARTIAL"
    else:
        verdict = "COMPLETE"

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'source':<28}{'truth':>6}{'lines':>7}{'cov':>7}  missing")
        for r in report:
            m = ", ".join(r["missing"][:6]) + (" ..." if len(r["missing"]) > 6 else "")
            cov_s = "   n/a" if r["coverage_pct"] is None else f"{r['coverage_pct']:>6.1f}"
            flag = "" if r["resolved"] else "  [UNRESOLVED -- source not on disk, nothing compared]"
            print(f"{r['slug']:<28}{r['ground_truth']:>6}{r['jsonl_lines']:>7}"
                  f"{cov_s}%  {m}{flag}")
        print(f"\n{verdict}: {n_missing} enumerable entries unaccounted for"
              f" ({n_resolved}/{len(selected)} sources resolved)")
        if skipped:
            print(f"  SCOPE: --source restricted this run to {len(selected)} of "
                  f"{len(ENUMERABLE)} sources.\n"
                  f"  NOT CHECKED by this run: {', '.join(skipped)}.\n"
                  "  This verdict says nothing about them, in either direction.")
        if verdict == "UNVERIFIED":
            print("  NOTHING WAS CHECKED: no configured source resolved on this host.\n"
                  "  This is a refusal, not a pass -- an empty ground truth cannot\n"
                  "  certify a corpus.")
        elif verdict == "PARTIAL":
            print(f"  {n_unresolved} source(s) were not on disk and were NOT checked.\n"
                  "  This run certifies only the resolved sources, and says so rather\n"
                  "  than calling itself COMPLETE.")
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
    if skipped and args.json:
        # The scope narrowing must be visible in every output mode, or a JSON
        # consumer reads a COMPLETE that silently covered a subset.
        print(f"SCOPE: --source restricted this run to {len(selected)} of "
              f"{len(ENUMERABLE)} sources; NOT CHECKED: {', '.join(skipped)}.",
              file=sys.stderr)
    if verdict == "PARTIAL" and args.allow_partial:
        stream = sys.stderr if args.json else sys.stdout
        print(
            f"WAIVER: --allow-partial accepts this PARTIAL result; "
            f"{n_unresolved} unresolved source(s) were NOT checked.",
            file=stream,
        )
        return 0
    return 0 if verdict == "COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
