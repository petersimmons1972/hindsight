#!/usr/bin/env python3
"""Render the pinned L2 partition as an auditable recurrence report.

The report deliberately renders only the supplied partition.  It never invokes
the clustering engine: changing a renderer must not silently change the ground
truth it describes.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_CLUSTERS = Path(__file__).resolve().parent / "L2" / "clusters.jsonl"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "L2" / "recurrence-report.md"


class ReportError(ValueError):
    """An input cannot support an honest recurrence report."""


def _date(value: object, *, field: str, cluster_id: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReportError(f"{cluster_id}: {field} must be an ISO date or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ReportError(f"{cluster_id}: {field} is not an ISO date: {value!r}") from exc


def _normalise_cluster(raw: dict[str, Any], line_number: int) -> dict[str, Any]:
    required = ("cluster_id", "members", "source_repos", "first_seen", "last_seen", "label")
    missing = [field for field in required if field not in raw]
    if missing:
        raise ReportError(f"line {line_number}: cluster missing required fields {missing}")
    cluster_id = raw["cluster_id"]
    members = raw["members"]
    repos = raw["source_repos"]
    if not isinstance(cluster_id, str) or not cluster_id:
        raise ReportError(f"line {line_number}: cluster_id must be a non-empty string")
    if not isinstance(members, list) or not members or any(not isinstance(member, str) or not member for member in members):
        raise ReportError(f"{cluster_id}: members must be a non-empty list of non-empty strings")
    if len(set(members)) != len(members):
        raise ReportError(f"{cluster_id}: members contains duplicate IDs")
    if not isinstance(repos, list) or any(not isinstance(repo, str) or not repo for repo in repos):
        raise ReportError(f"{cluster_id}: source_repos must be a list of non-empty strings")
    if not isinstance(raw["label"], str) or not raw["label"].strip():
        raise ReportError(f"{cluster_id}: label must be a non-empty string")

    first = _date(raw["first_seen"], field="first_seen", cluster_id=cluster_id)
    last = _date(raw["last_seen"], field="last_seen", cluster_id=cluster_id)
    if (first is None) != (last is None):
        raise ReportError(f"{cluster_id}: first_seen and last_seen must both be dates or both be null")
    if first is not None and last is not None and last < first:
        raise ReportError(f"{cluster_id}: last_seen precedes first_seen")
    span_days = (last - first).days if first is not None and last is not None else None
    return {
        "cluster_id": cluster_id,
        "size": len(members),  # Derived evidence count; never trust serialized size.
        "members": members,
        "source_repos": sorted(set(repos)),
        "first_seen": raw["first_seen"],
        "last_seen": raw["last_seen"],
        "label": raw["label"],
        "span_days": span_days,
    }


def load_partition(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load exactly one pinned JSONL partition, rejecting any partial input."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReportError(f"cannot read clusters file {path}: {exc}") from exc
    if not lines:
        raise ReportError(f"clusters file {path} is empty")

    meta: dict[str, Any] | None = None
    clusters: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ReportError(f"{path}:{line_number}: blank JSONL line is not permitted")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReportError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise ReportError(f"{path}:{line_number}: JSONL record must be an object")
        if "_meta" in raw:
            if set(raw) != {"_meta"} or not isinstance(raw["_meta"], dict):
                raise ReportError(f"{path}:{line_number}: _meta record must contain only an object _meta")
            if meta is not None:
                raise ReportError(f"{path}:{line_number}: duplicate _meta record")
            meta = raw["_meta"]
            continue
        cluster = _normalise_cluster(raw, line_number)
        if cluster["cluster_id"] in seen_ids:
            raise ReportError(f"{path}:{line_number}: duplicate cluster_id {cluster['cluster_id']}")
        seen_ids.add(cluster["cluster_id"])
        clusters.append(cluster)
    if meta is None:
        raise ReportError(f"clusters file {path} has no _meta record")
    if not clusters:
        raise ReportError(f"clusters file {path} has no cluster records")
    return meta, sorted(clusters, key=lambda group: (-group["size"], -(group["span_days"] or -1), group["cluster_id"]))


def select_groups(groups: list[dict[str, Any]], min_size: int, top: int | None) -> list[dict[str, Any]]:
    selected = [group for group in groups if group["size"] >= min_size]
    return selected if top is None else selected[:top]


def render_text(groups: list[dict[str, Any]], all_groups: list[dict[str, Any]], entry_count: object) -> str:
    repeated = [group for group in all_groups if group["size"] > 1]
    top = all_groups[0]
    lines = [
        "Recurrence report",
        f"Corpus: {entry_count} entries; {len(all_groups)} clusters; {len(repeated)} recurring clusters.",
        f"Most repeated root cause: {top['label']} ({top['size']} occurrences).",
        "Limitation: this wording-based partition under-reports recurrence; it does not detect records that share an abstract cause shape but not wording (measured blind-paraphrase recall: 1/77).",
        "",
    ]
    for group in groups:
        dates = f"{group['first_seen']} to {group['last_seen']}" if group["first_seen"] else "dates unavailable"
        lines.extend((
            f"{group['cluster_id']}: {group['label']}",
            f"  {group['size']} times across {len(group['source_repos'])} repos ({', '.join(group['source_repos'])}); {dates}; span {group['span_days'] if group['span_days'] is not None else 'unknown'} days.",
            f"  Members: {', '.join(group['members'])}",
        ))
    return "\n".join(lines) + "\n"


def load_member_details() -> dict[str, dict[str, str]]:
    """Read L1 only for Markdown's evidence appendix, never for grouping."""
    records: dict[str, dict[str, str]] = {}
    for path in sorted((Path(__file__).resolve().parent / "L1").glob("*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                record = json.loads(line)
                identifier = record["id"]
                instance = record["instance"]
                source_path = record["source_path"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ReportError(f"cannot read member evidence at {path}:{line_number}") from exc
            if not all(isinstance(value, str) and value for value in (identifier, instance, source_path)):
                raise ReportError(f"invalid member evidence at {path}:{line_number}")
            records[identifier] = {"instance": instance, "source_path": source_path}
    return records


def render_markdown(groups: list[dict[str, Any]], all_groups: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    repeated = [group for group in all_groups if group["size"] >= 2]
    top = all_groups[0]
    lines = [
        "# Recurrence report", "", "## Summary", "",
        f"Corpus: **{meta.get('entry_count', 'unknown')}** entries; **{len(all_groups)}** clusters; **{len(repeated)}** clusters with more than one member.",
        f"Most repeated root cause: **{top['label']}** (**{top['size']}** occurrences).", "",
        "Limitation: this wording-based partition under-reports recurrence. It cannot group records that share only an abstract cause shape rather than wording (measured blind-paraphrase recall: 1 of 77). A singleton is therefore not evidence that a cause never recurred.", "",
        "## Recurrence table", "",
        "| Label | Count | Member IDs | Source repos | First seen | Last seen | Span (days) |",
        "| --- | ---: | --- | --- | --- | --- | ---: |",
    ]
    for group in repeated:
        if group not in groups:
            continue
        lines.append("| {label} | {size} | {members} | {repos} | {first} | {last} | {span} |".format(
            label=group["label"].replace("|", "\\|"), size=group["size"], members=", ".join(group["members"]),
            repos=", ".join(group["source_repos"]), first=group["first_seen"] or "unknown", last=group["last_seen"] or "unknown",
            span=group["span_days"] if group["span_days"] is not None else "unknown"))
    lines.extend(("", "## Per-cluster detail", ""))
    details = load_member_details()
    for group in [group for group in groups if group["size"] >= 2][:15]:
        lines.extend((f"### {group['cluster_id']}: {group['label']}", ""))
        for member in group["members"]:
            evidence = details.get(member)
            if evidence is None:
                raise ReportError(f"{group['cluster_id']}: no L1 evidence found for member {member}")
            lines.extend((f"- `{member}` — {evidence['instance']}", f"  Source: `{evidence['source_path']}`"))
        lines.append("")
    singleton_count = sum(group["size"] == 1 for group in all_groups)
    lines.extend(("## Singletons appendix", "", f"{singleton_count} singleton clusters. A singleton is not proof of non-recurrence, only of non-detection.", "", "## Provenance", "", f"Backend: `{meta.get('backend', 'unknown')}`; threshold: `{meta.get('threshold', 'unknown')}`; linkage: `{meta.get('linkage', 'unknown')}`; input entry count: `{meta.get('entry_count', 'unknown')}`.", ""))
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clusters", type=Path, default=DEFAULT_CLUSTERS)
    parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    parser.add_argument("--output", type=Path, help=f"write the selected format (default Markdown path: {DEFAULT_OUTPUT})")
    parser.add_argument("--min-size", type=int, default=1)
    parser.add_argument("--top", type=int)
    args = parser.parse_args()
    if args.min_size < 1:
        parser.error("--min-size must be at least 1")
    if args.top is not None and args.top < 1:
        parser.error("--top must be at least 1")
    return args


def main() -> int:
    args = parse_args()
    try:
        meta, groups = load_partition(args.clusters)
        selected = select_groups(groups, args.min_size, args.top)
        if args.format == "json":
            rendered = json.dumps(selected, indent=2) + "\n"
        elif args.format == "markdown":
            rendered = render_markdown(selected, groups, meta)
        else:
            rendered = render_text(selected, groups, meta.get("entry_count", "unknown"))
        if args.output is not None:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except (ReportError, OSError) as exc:
        print(f"recurrence report error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
