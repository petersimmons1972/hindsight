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

from pipeline.reconcile_l1 import ENUMERABLE, extracted, ground_truth_resolved, parse_catalog_rows


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

# ---- 3. fleet-main / fleet-orch backlog (hindsight#106) -----------------------
#
# fleet-main and fleet-orch have no generator at all -- their .jsonl files were
# hand-authored by a model pass in 2026-08 and never reconciled again (issue
# #106). `fleet/FAILURE-MODES.md` is FROZEN (2026-08-10, fleet PR #417), so this
# is a one-time backfill, not a recurring sync: once every enumerable ID from
# `reconcile_l1.ENUMERABLE`'s own ground-truth files is present, re-running this
# finds nothing new to add and is a no-op.
#
# The section body under each `### ID -- title` (or `## ID -- title`) heading
# uses three different bullet vocabularies across the three source files
# (Lie/Tell/Root cause/Countermeasure/Provenance; Symptom/Cause/Response/
# Catches it/Evidence; Where/Cause/Countermeasure with no Provenance at all).
# Rather than special-case each file, bullets are classified by what the label
# text itself says: a label naming "provenance" or "evidence" is metadata (date
# only, excluded from instance/check); a label naming "countermeasure",
# "response", "catches", or "fix" is the check; everything else (Lie, Tell,
# Root cause, Symptom, Cause, Where, ...) is folded into instance, in the order
# each bullet appears in the source. This is honest under all three vocabularies
# rather than fragile to any one of them.
_BULLET_RE = re.compile(r"^(?:-\s*)?\*\*([^*]+?):\*\*\s?(.*)$")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_META_LABELS = re.compile(r"provenance|evidence", re.IGNORECASE)
# The three source files use three vocabularies for the incident-description
# bullet(s): Lie/Tell/Root cause, Symptom/Cause, Where/Cause. Enumerated
# explicitly and kept short and closed, because everything NOT matched here
# defaults to `check` (see classification loop below) -- flagged by
# independent review: an earlier version defaulted the other way and folded
# verification-only bullets (`Direction matters`, `Test`) that this corpus
# also uses (fleet/orchestration/FAILURE-MODES.md ORC-21) into `instance`.
# Countermeasure/Response/etc. do not need their own list because "not an
# instance label and not a meta label" already means check.
_INSTANCE_LABELS = re.compile(r"^(lie|tell|root cause|symptom|cause|where)$", re.IGNORECASE)


def _heading_re() -> re.Pattern[str]:
    # Same ID grammar reconcile_l1.py's ENUMERABLE ground-truth regexes use
    # (`^#{2,4} +ID`), with the remainder of the line captured unanchored so a
    # `(old: FM-N)` cross-reference between the ID and the em-dash title (seen
    # in fleet/orchestration/FAILURE-MODES.md and fleet/CODING-INVARIANTS.md)
    # does not silently fail the whole-line match the way an end-anchored
    # dash-only pattern would.
    return re.compile(r"^#{2,4} +((?:OPS|CI|ORC|MDL|FM)-\d+[a-z]?)\s*(.*)$")


_TITLE_CLEAN_RE = re.compile(r"^\(old:[^)]*\)\s*(?:[—-]\s*)?")
_TITLE_DASH_RE = re.compile(r"^[—-]\s*")


def _clean_title(rest: str) -> str:
    rest = rest.strip()
    rest = _TITLE_CLEAN_RE.sub("", rest)
    rest = _TITLE_DASH_RE.sub("", rest)
    return rest.strip()


def parse_domain_sections(text: str) -> dict[str, dict[str, object]]:
    """Parse every `### ID -- title` section in one fleet-registry markdown file.

    Returns local id (e.g. "CI-18", no source-slug prefix) -> {title, instance,
    check, first_seen}. A section with no recognized instance-bearing bullet
    falls back to using its own heading title as the instance, so a record is
    never silently empty.
    """
    heading_re = _heading_re()
    lines = text.splitlines()
    heads: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            heads.append((i, m.group(1), _clean_title(m.group(2) or "")))

    sections: dict[str, dict[str, object]] = {}
    for idx, (start, local_id, title) in enumerate(heads):
        if local_id in sections:
            # Duplicate local-ID registration within one file (measured, e.g.
            # fleet/CODING-INVARIANTS.md registers "MDL-2" three times under
            # different `(old: FM-N)` cross-references) -- hindsight#106 flags
            # this as a genuine judgment call, not something to silently
            # overwrite or merge. Deterministic policy: keep the FIRST
            # occurrence (lowest line number), and say so on stderr so a
            # reviewer can check the call.
            print(
                f"    NOTE: duplicate heading for {local_id!r} at line "
                f"{start + 1} (keeping the earlier occurrence)",
                file=sys.stderr,
            )
            continue
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        body = lines[start + 1:end]

        bullets: dict[str, list[str]] = {}
        order: list[str] = []
        cur_label: str | None = None
        for line in body:
            bm = _BULLET_RE.match(line.strip())
            if bm:
                cur_label = bm.group(1).strip()
                text_part = bm.group(2).strip()
                bullets.setdefault(cur_label, [])
                order.append(cur_label)
                if text_part:
                    bullets[cur_label].append(text_part)
                continue
            if not line.strip():
                cur_label = None
                continue
            if cur_label is not None:
                bullets[cur_label].append(line.strip())

        instance_parts: list[str] = []
        check_parts: list[str] = []
        meta_parts: list[str] = []
        seen_labels: set[str] = set()
        for label in order:
            if label in seen_labels:
                continue
            seen_labels.add(label)
            joined = " ".join(bullets[label])
            if not joined:
                continue
            label_norm = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
            if _META_LABELS.search(label_norm):
                meta_parts.append(joined)
            elif _INSTANCE_LABELS.match(label_norm):
                instance_parts.append(joined)
            else:
                # Closed default: Countermeasure/Response/Catches it/Fix, plus
                # anything this parser has not seen a vocabulary for yet
                # (e.g. "Direction matters", "Test"), is check material --
                # verification/remediation content, never the incident
                # description. Measured wrong the other way on ORC-21.
                check_parts.append(joined)

        instance = " ".join(instance_parts) if instance_parts else title
        check = " ".join(check_parts) if check_parts else None
        meta_text = " ".join(meta_parts)
        date_m = _DATE_RE.search(meta_text)
        first_seen = date_m.group(1) if date_m else None

        sections[local_id] = {
            "title": title,
            "instance": instance,
            "check": check,
            "first_seen": first_seen,
        }
    return sections


def extract_fleet_domain(slug: str, id_prefix: str) -> int:
    """Append missing enumerable entries for a fleet-registry L1 source.

    Ground truth comes from `reconcile_l1.ENUMERABLE[slug]` -- the exact same
    files and regex `reconcile_l1.py` uses to compute the missing-entry count,
    so this can never silently drift from what the gate measures. "Missing"
    also matches `reconcile_l1.py` exactly: `truth - extracted(slug)[0]`, the
    same loose substring-based coverage check `main()` uses (a record's `id`,
    `source_anchor`, `instance`, and `check` are all searched). This is
    deliberate, not merely convenient: `reconcile_l1.extracted()` was measured
    to already count some IDs as covered by substring luck (an existing record
    such as `fleet-orch-CI-1-FM7` satisfies a regex search for `CI-1` even
    though no record actually carries a standalone `CI-1` entry) -- see the
    FM filed alongside this change. Backfilling those "already covered" IDs
    too would silently widen this PR beyond hindsight#106's named scope (51
    fleet-main + 3 fleet-orch = 54) into inventing a dedup/collision policy the
    issue explicitly reserved for a separate decision. So this only adds what
    `reconcile_l1.py` itself calls missing today, keeping this change's shape
    identical to the issue's own measurement.

    Existing records are never rewritten or reordered; entries are only
    appended. Idempotent: once ground truth is fully covered, a second run
    appends nothing.
    """
    files, _rx = ENUMERABLE[slug]
    path = OUT / f"{slug}.jsonl"

    truth, resolved = ground_truth_resolved(slug)
    if not resolved:
        print(f"  {slug:<26} SKIPPED (no configured source file on disk)")
        return 0

    sections: dict[str, dict[str, object]] = {}
    source_of: dict[str, Path] = {}
    for f in files:
        if not f.exists():
            continue
        parsed = parse_domain_sections(f.read_text(encoding="utf-8", errors="replace"))
        for local_id, sec in parsed.items():
            if local_id not in sections:
                sections[local_id] = sec
                source_of[local_id] = f
            else:
                # Cross-file collision within one slug's source set (measured:
                # "CI-1" is registered separately in both
                # fleet/orchestration/FAILURE-MODES.md and
                # fleet/CODING-INVARIANTS.md, under different content).
                # Same disclosed, deterministic policy as the same-file case:
                # keep whichever file was listed first in ENUMERABLE.
                print(
                    f"    NOTE: {local_id!r} also registered in {f} "
                    f"(keeping the entry from {source_of[local_id]})",
                    file=sys.stderr,
                )

    found, _n_lines = extracted(slug)
    missing = sorted(truth - found)
    new_records: list[dict[str, object]] = []
    unresolved_ids: list[str] = []
    for local_id in missing:
        sec = sections.get(local_id)
        if sec is None:
            unresolved_ids.append(local_id)
            continue
        src = source_of[local_id]
        new_records.append({
            "id": f"{id_prefix}{local_id}",
            "source_path": str(src.relative_to(P)),
            "source_anchor": f"{local_id} — {sec['title']}" if sec["title"] else local_id,
            "instance": sec["instance"],
            "check": sec["check"],
            # Unlike homelab-canon's Auto? table column, these markdown headings
            # encode no machine/manual signal at all for this classification --
            # a defensible mechanical default, same rationale as `enforcement:
            # None` above: honest rather than fabricated.
            "enforcement": None,
            "auto": "judgment",
            "first_seen": sec["first_seen"],
        })

    if unresolved_ids:
        print(
            f"  {slug:<26} WARNING: {len(unresolved_ids)} ground-truth id(s) had "
            f"no parseable section: {', '.join(unresolved_ids)}",
            file=sys.stderr,
        )

    if new_records:
        with path.open("a", encoding="utf-8") as fh:
            for r in new_records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    note = f" ({len(unresolved_ids)} unresolved)" if unresolved_ids else ""
    print(f"  {slug:<26} {len(new_records):>4} entries appended{note}")
    return len(new_records)


extract_fleet_domain("fleet-main", "fleet-")
extract_fleet_domain("fleet-orch", "fleet-orch-")
