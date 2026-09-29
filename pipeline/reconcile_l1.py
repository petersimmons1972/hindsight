#!/usr/bin/env python3
"""Mechanically reconcile L1 extraction against ground truth.

Why this exists
---------------
The first L1 extraction pass reported success on every source, and was lossy:
fleet-main returned 78 of 102 entries, the queue schema 2 of 10. Nothing failed;
each agent reported a count that looked plausible on its own.

That is the registry's own headline failure mode -- a proxy (the agent's
self-reported count) trusted in place of the thing (actual coverage). So
coverage is not asked for, it is COMPUTED: ground-truth IDs are extracted from
each source by regex, and any ID absent from the JSONL is reported. Sources whose
entries are machine-enumerable are extracted mechanically outright -- no model in
the loop -- because their structure already encodes the answer.

Usage:  python3 reconcile_l1.py [--json] [--allow-partial] [--source SLUG ...]
        [--gate SLUG[,SLUG...] ...]
Exit 0 only when the gate is COMPLETE, or when its PARTIAL result is explicitly
waived. Without `--gate`, every selected source is gated.

`--source` narrows the run to named sources. It exists because the corpus is a
union of five sources, and a gate that reconciles ALL of
them is the wrong coupling for a caller that wrote ONE of them: an unrelated
sibling repo's backlog made `bin/add-failure-mode.sh` unable to add anything at
all (issue #73). Narrowing is never silent -- a scoped run prints exactly which
sources it did not look at, and an unknown slug is a hard error rather than an
empty scope that would certify nothing while exiting 0.

`--gate` is deliberately different: it still reports every selected source,
but narrows only the exit-status decision. This lets a canonical catalog write
prove that its own `homelab-canon` extract survived while continuing to expose
the separately tracked sibling-consumer sync backlog (hindsight#101).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

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
                      re.compile(r"^\|\s*(FM-\d{2,3})\s*\|")),
    "claude-codex-integration": ([P / "claude-codex/docs/integration-failure-modes.md"],
                                 re.compile(r"^#{2,4} +(FM-\d{2,3})")),
    "dispatch-schema": ([REPO / "pipeline/sources/dispatch-failure-class.sql"],
                              re.compile(r"'([a-z_]{4,})'")),
}


CATALOG_ROW_RE = re.compile(r"^\|\s*(FM-\d{2,3})\s*\|")
AUTO_CELLS = {"🤖", "Judgment", "Deterministic", "🤖 / Judgment"}


class CanonicalRow(NamedTuple):
    """The five semantic cells in one canonical catalog table row."""

    fm_id: str
    class_hint: str
    instance: str
    check: str | None
    auto: str
    line_number: int

    def l1_fields(self) -> dict[str, object]:
        return {
            "class_hint": self.class_hint,
            "instance": self.instance,
            "check": self.check,
            # The catalog is canonical.  In particular, the nine pipe-heavy
            # rows ending in 🤖 are machine-classified even though the old
            # split('|') extractor corrupted their L1 value to "judgment".
            "auto": "machine" if "🤖" in self.auto else "judgment",
        }


def _protected_pipe_positions(text: str) -> set[int]:
    """Pipes which are catalog prose, not Markdown cell boundaries.

    The historical table contains escaped pipelines, inline-code pipelines and
    quoted shell snippets.  Some predate consistent Markdown escaping, so the
    parser recognizes the grammar that is actually committed rather than
    pretending every literal ``|`` starts another schema cell.
    """
    protected: set[int] = set()
    for index, char in enumerate(text):
        if char != "|":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            protected.add(index)

    index = 0
    while index < len(text):
        if text[index] != "`":
            index += 1
            continue
        end_run = index
        while end_run < len(text) and text[end_run] == "`":
            end_run += 1
        delimiter = text[index:end_run]
        closing = text.find(delimiter, end_run)
        if closing < 0:
            index = end_run
            continue
        protected.update(
            position for position in range(end_run, closing) if text[position] == "|"
        )
        index = closing + len(delimiter)

    for quote in ("'", '"'):
        pattern = re.compile(
            rf"(?<![\w\\]){re.escape(quote)}(?=\S)"
            rf"[^\n{re.escape(quote)}]*?{re.escape(quote)}(?!\w)"
        )
        for match in pattern.finditer(text):
            protected.update(
                position
                for position in range(match.start(), match.end())
                if text[position] == "|"
            )
    return protected


def _semantic_separators(text: str) -> list[int]:
    protected = _protected_pipe_positions(text)
    return [
        index
        for index, char in enumerate(text)
        if char == "|"
        and index not in protected
        and index > 0
        and index + 1 < len(text)
        and text[index - 1].isspace()
        and text[index + 1].isspace()
    ]


def parse_catalog_row(line: str, line_number: int) -> CanonicalRow | None:
    """Parse the catalog's real five-cell grammar, including legacy four-cell rows.

    ID and class are the first two cells. A recognized terminal Auto? marker is
    removed from the right, then the final remaining semantic separator divides
    Concrete instance from Check. Choosing that schema boundary from the right
    lets old prose retain unescaped pipelines without truncating either cell.
    """
    if not CATALOG_ROW_RE.match(line):
        return None
    stripped = line.strip()
    if not stripped.endswith("|"):
        raise ValueError(f"catalog row {line_number} has no closing pipe")
    body = stripped[1:-1]
    separators = _semantic_separators(body)
    if len(separators) < 2:
        raise ValueError(f"catalog row {line_number} has no ID/class boundary")

    first, second = separators[:2]
    fm_id = body[:first].strip()
    class_hint = body[first + 1:second].strip()
    remainder = body[second + 1:]

    auto = ""
    remainder_separators = _semantic_separators(remainder)
    if remainder_separators:
        tail = remainder[remainder_separators[-1] + 1:].strip()
        if tail in AUTO_CELLS:
            auto = tail
            remainder = remainder[:remainder_separators[-1]]

    content_separators = _semantic_separators(remainder)
    if content_separators:
        boundary = content_separators[-1]
        instance = remainder[:boundary].strip()
        check = remainder[boundary + 1:].strip() or None
    else:
        instance = remainder.strip()
        check = None

    return CanonicalRow(
        fm_id=fm_id.strip(),
        class_hint=class_hint,
        instance=instance,
        check=check,
        auto=auto,
        line_number=line_number,
    )


def parse_catalog_rows(text: str) -> list[CanonicalRow]:
    rows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        row = parse_catalog_row(line, line_number)
        if row is not None:
            rows.append(row)
    return rows


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
        # the id field for snake_case and reported a false 0% on the queue schema --
        # a validator that fails ground truth is worse than no validator.
        blob = " ".join(str(d.get(k, "")) for k in
                        ("id", "source_anchor", "instance", "check"))
        # The trailing `(?![\w-])` matters: without it this is a substring search,
        # not an ID match. A record disambiguated as e.g. "CI-1-FM7" (two source
        # headings both literally named "CI-1" collided, so the corpus appended
        # the old FM number to tell them apart -- see fleet-orch's CI-1-FM5 and
        # CI-1-FM7) contains "CI-1" as a literal substring of its id AND of its
        # source_anchor ("CI-1 (old: FM-7)"), but neither record IS the standalone
        # entry "CI-1" -- that heading can be entirely missing from the JSONL while
        # this search still reports it "covered" because a longer, hyphen-suffixed
        # token happens to start with it (hindsight#179). Disallowing a following
        # word-char blocks the plain-concatenation case (FM-1 inside FM-10/FM-100);
        # disallowing a following hyphen blocks this compound-suffix case.
        found.update(re.findall(r"(?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?(?![\w-])", blob))
        found.update(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", blob))
    return found, n


def catalog_l1_text_divergence() -> list[str]:
    """Return canonical row IDs whose extracted text no longer agrees with L1.

    Coverage alone can say every FM ID survived while the text a consumer reads
    is stale.  Compare the fields ``extract_mechanical.py`` derives from each
    table row, so an error identifies the maintainer's exact re-extraction
    target rather than reporting an unusable aggregate digest mismatch.
    """
    catalog = REPO / "catalog" / "failure-modes.md"
    l1_path = L1 / "homelab-canon.jsonl"
    if not catalog.is_file() or not l1_path.is_file():
        return []

    canonical = {
        row.fm_id: row.l1_fields()
        for row in parse_catalog_rows(catalog.read_text(encoding="utf-8"))
    }

    extracted_rows: dict[str, dict[str, object]] = {}
    for raw in l1_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        row_id = record.get("id")
        if not isinstance(row_id, str) or not row_id.startswith("hc-FM-"):
            continue
        extracted_rows[row_id.removeprefix("hc-")] = record

    # Synthetic coverage fixtures intentionally use bare IDs.  Their purpose
    # is ID accounting, not extractor fidelity; a real canonical extract always
    # carries hc-FM-* identifiers.
    if not extracted_rows:
        return []

    divergent: list[str] = []
    for fm_id, expected in canonical.items():
        actual = extracted_rows.get(fm_id)
        if actual is not None and any(actual.get(field) != value for field, value in expected.items()):
            divergent.append(fm_id)
    return sorted(divergent)


def canonical_l1_primary_ids(slug: str) -> set[str]:
    """Return primary canonical IDs, excluding FM references in prose.

    Real extracts identify rows as ``hc-FM-*``. Tiny synthetic fixtures from
    the older coverage tests use bare ``FM-*`` IDs, so those remain supported
    only when no real canonical identifier is present at all.
    """
    if slug != "homelab-canon":
        return set()
    path = L1 / "homelab-canon.jsonl"
    if not path.is_file():
        return set()
    canonical: set[str] = set()
    fixture: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row_id = json.loads(raw).get("id")
        if not isinstance(row_id, str):
            continue
        if row_id.startswith("hc-FM-"):
            canonical.add(row_id.removeprefix("hc-"))
        elif re.fullmatch(r"FM-\d+[a-z]?", row_id):
            fixture.add(row_id)
    return canonical or fixture


def extra_canonical_l1_ids(slug: str, truth: set[str]) -> list[str]:
    """Return primary FM IDs which exist only in L1.

    The generic extractor also finds FM cross-references in prose, so surplus
    accounting must use the canonical record's primary ``hc-FM-*`` ID rather
    than that broad reference set.
    """
    return sorted(canonical_l1_primary_ids(slug) - truth)


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
    ap.add_argument(
        "--gate",
        action="append",
        metavar="SLUG[,SLUG...]",
        help="gate exit status on these comma-separated source slugs while "
             "continuing to report every selected source (repeatable)",
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

    gate_requested = []
    for value in args.gate or []:
        gate_requested.extend(value.split(","))
    if gate_requested:
        invalid_gates = sorted({slug for slug in gate_requested if slug not in ENUMERABLE})
        if invalid_gates:
            printable = ", ".join(repr(slug) for slug in invalid_gates)
            print(f"ERROR: unknown --gate: {printable}\n"
                  f"  known sources: {', '.join(ENUMERABLE)}", file=sys.stderr)
            return 2
        excluded_gates = sorted(set(gate_requested) - set(selected))
        if excluded_gates:
            print(f"ERROR: --gate names source(s) excluded by --source: "
                  f"{', '.join(excluded_gates)}", file=sys.stderr)
            return 2
        gated = [slug for slug in selected if slug in set(gate_requested)]
    else:
        gated = selected

    report, short = [], False
    n_resolved = 0
    for slug in selected:
        truth, resolved = ground_truth_resolved(slug)
        n_resolved += 1 if resolved else 0
        found, n_lines = extracted(slug)
        coverage_ids = (
            canonical_l1_primary_ids(slug) if slug == "homelab-canon" else found
        )
        missing = sorted(truth - coverage_ids)
        # An unresolved source scores None, never 100. Absence of a measurement
        # is not a perfect measurement.
        if not resolved:
            cov = None
        elif truth:
            cov = round((len(truth) - len(missing)) / len(truth) * 100, 1)
        else:
            cov = 100.0
        divergent = catalog_l1_text_divergence() if slug == "homelab-canon" else []
        extra = extra_canonical_l1_ids(slug, truth)
        if missing or divergent or extra:
            short = True
        report.append({"slug": slug, "ground_truth": len(truth), "jsonl_lines": n_lines,
                       "covered": len(truth) - len(missing), "coverage_pct": cov,
                       "resolved": resolved, "missing": missing, "extra": extra,
                       "divergent": divergent})
    n_unresolved = len(selected) - n_resolved
    n_missing = sum(len(r["missing"]) for r in report)
    n_divergent = sum(len(r["divergent"]) for r in report)
    if n_resolved == 0:
        verdict = "UNVERIFIED"
    elif short:
        verdict = "SHORT"
    elif n_unresolved:
        verdict = "PARTIAL"
    else:
        verdict = "COMPLETE"

    gated_report = [r for r in report if r["slug"] in gated]
    gated_unresolved = [r["slug"] for r in gated_report if not r["resolved"]]
    gated_short = [
        r["slug"] for r in gated_report
        if r["missing"] or r["extra"] or r["divergent"]
    ]
    if not any(r["resolved"] for r in gated_report):
        gate_verdict = "UNVERIFIED"
    elif gated_short:
        gate_verdict = "SHORT"
    elif gated_unresolved:
        gate_verdict = "PARTIAL"
    else:
        gate_verdict = "COMPLETE"

    gate_sources = ", ".join(gated)
    # Non-canonical-source SHORT results stay visible above as health evidence.
    # They are ongoing consumer-sync backlog, not a canonical-write blocker;
    # only `--gate` chooses which source(s) may determine this invocation's exit
    # status (hindsight#101).
    if gate_verdict == "COMPLETE":
        gate_message = f"GATE: COMPLETE across {gate_sources}; exit 0"
    elif gate_verdict == "SHORT":
        gate_message = (
            f"GATE: SHORT across {gate_sources}; blocking source(s): "
            f"{', '.join(gated_short)}"
        )
    elif gate_verdict == "PARTIAL":
        gate_message = (
            f"GATE: PARTIAL across {gate_sources}; blocking unresolved source(s): "
            f"{', '.join(gated_unresolved)}"
        )
    else:
        gate_message = (
            f"GATE: UNVERIFIED across {gate_sources}; blocking source(s): "
            f"{', '.join(gated_unresolved)}"
        )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'source':<28}{'truth':>6}{'lines':>7}{'cov':>7}  missing")
        for r in report:
            missing_ids = ", ".join(r["missing"][:6]) + (" ..." if len(r["missing"]) > 6 else "")
            divergent_ids = ", ".join(r["divergent"][:6]) + (" ..." if len(r["divergent"]) > 6 else "")
            extra_ids = ", ".join(r["extra"][:6]) + (" ..." if len(r["extra"]) > 6 else "")
            m = missing_ids
            if extra_ids:
                m = f"{m}; extra: {extra_ids}" if m else f"extra: {extra_ids}"
            if divergent_ids:
                m = f"{m}; divergent: {divergent_ids}" if m else f"divergent: {divergent_ids}"
            cov_s = "   n/a" if r["coverage_pct"] is None else f"{r['coverage_pct']:>6.1f}"
            flag = "" if r["resolved"] else "  [UNRESOLVED -- source not on disk, nothing compared]"
            print(f"{r['slug']:<28}{r['ground_truth']:>6}{r['jsonl_lines']:>7}"
                  f"{cov_s}%  {m}{flag}")
        print(f"\n{verdict}: {n_missing} enumerable entries unaccounted for; "
              f"{n_divergent} canonical row(s) text-divergent"
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
        print(f"\n{gate_message}")
    if skipped and args.json:
        # The scope narrowing must be visible in every output mode, or a JSON
        # consumer reads a COMPLETE that silently covered a subset.
        print(f"SCOPE: --source restricted this run to {len(selected)} of "
              f"{len(ENUMERABLE)} sources; NOT CHECKED: {', '.join(skipped)}.",
              file=sys.stderr)
    if args.json:
        print(gate_message, file=sys.stderr)
    if gate_verdict == "PARTIAL" and args.allow_partial:
        stream = sys.stderr if args.json else sys.stdout
        print(
            f"WAIVER: --allow-partial accepts this PARTIAL result; "
            f"{len(gated_unresolved)} unresolved source(s) were NOT checked.",
            file=stream,
        )
        return 0
    return 0 if gate_verdict == "COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
