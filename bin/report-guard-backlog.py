#!/usr/bin/env python3
"""Surface the open guard backlog: disposition=mechanize and enforcement=null.

A mechanized failure mode costs zero tokens forever once a real guard exists.
This report is the list of filings that asked for that and still have no
enforcement mechanism. It is a read-only join of catalog/criticality.jsonl
(disposition) and pipeline/L1 (enforcement).

Pre-O2 criticality rows have no ``disposition`` field. That absence is not an
error and is not treated as mechanize: there is no retrofit campaign. Those
rows are skipped.

Environment / flags never write catalog/ or pipeline/L1. Tests pass fixture
paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CRITICALITY = REPO_ROOT / "catalog" / "criticality.jsonl"
DEFAULT_L1 = REPO_ROOT / "pipeline" / "L1"


class ReportError(ValueError):
    """An input cannot support an honest backlog report."""


def _l1_paths(source: Path) -> list[Path]:
    if source.is_dir():
        return sorted(path for path in source.glob("*.jsonl") if path.is_file())
    if source.is_file():
        return [source]
    raise ReportError(f"L1 path does not exist: {source}")


def _normalise_fm_id(record_id: object) -> str | None:
    if not isinstance(record_id, str) or not record_id:
        return None
    if record_id.startswith("hc-FM-"):
        return record_id[len("hc-") :]
    if record_id.startswith("FM-"):
        return record_id
    return None


def _is_unenforced(value: object) -> bool:
    """JSON null or a missing field is the open-backlog state.

    A present enforcement object (file + kind) is a claimed mechanism and is
    not the backlog, even if a later verifier would call that claim a phantom.
    """
    return value is None


def load_dispositions(path: Path) -> dict[str, dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReportError(f"cannot read criticality file {path}: {exc}") from exc

    latest: dict[str, dict] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReportError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise ReportError(f"{path}:{line_number}: JSONL record must be an object")
        fm_id = raw.get("fm_id")
        if not isinstance(fm_id, str) or not fm_id:
            raise ReportError(f"{path}:{line_number}: fm_id must be a non-empty string")
        latest[fm_id] = raw
    return latest


def load_enforcement(paths: list[Path]) -> dict[str, object]:
    """Map FM-NNN -> last-seen enforcement value. Unmatched L1 ids are ignored."""
    enforcement: dict[str, object] = {}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ReportError(f"cannot read L1 file {path}: {exc}") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReportError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(raw, dict):
                raise ReportError(f"{path}:{line_number}: JSONL record must be an object")
            fm_id = _normalise_fm_id(raw.get("id"))
            if fm_id is None:
                continue
            enforcement[fm_id] = raw.get("enforcement")
    return enforcement


def select_backlog(dispositions: dict[str, dict], enforcement: dict[str, object]) -> list[str]:
    backlog: list[str] = []
    for fm_id, row in dispositions.items():
        if row.get("disposition") != "mechanize":
            continue
        if fm_id not in enforcement or _is_unenforced(enforcement[fm_id]):
            backlog.append(fm_id)
    return sorted(backlog, key=lambda item: int(item.split("-", 1)[1]) if item.split("-", 1)[-1].isdigit() else item)


def render(backlog: list[str]) -> str:
    lines = [
        "# Open guard backlog",
        "# Failure modes with disposition=mechanize and enforcement=null",
        "",
    ]
    lines.extend(backlog)
    if backlog:
        lines.append("")
    lines.append(f"guard-backlog: {len(backlog)} mechanize entries with enforcement=null")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List FMs filed mechanize whose L1 enforcement is still null.",
    )
    parser.add_argument(
        "--criticality",
        type=Path,
        default=DEFAULT_CRITICALITY,
        help="criticality JSONL (default: catalog/criticality.jsonl)",
    )
    parser.add_argument(
        "--l1",
        type=Path,
        default=DEFAULT_L1,
        help="L1 JSONL file or directory of *.jsonl (default: pipeline/L1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the report here instead of stdout",
    )
    args = parser.parse_args(argv)

    try:
        dispositions = load_dispositions(args.criticality)
        enforcement = load_enforcement(_l1_paths(args.l1))
        text = render(select_backlog(dispositions, enforcement))
    except ReportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
