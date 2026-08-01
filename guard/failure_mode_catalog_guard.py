#!/usr/bin/env python3
"""Validate the canonical failure-mode catalog."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROW_RE = re.compile(r"^\| (FM-(\d{2,3})) \|")
# Legacy schemes are only a defect when used as a ROW ID. The same strings
# appear legitimately as provenance annotations inside the bug-class column
# (e.g. "Container Runtime - Design (FM-RC-01)") and must not be flagged.
HISTORICAL_SCHEME_RE = re.compile(r"^\| *FM-(RC|REC)-\d+ *\|")


@dataclass(frozen=True)
class CatalogRow:
    fm_id: str
    number: int
    line: int


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "catalog" / "failure-modes.md"


def parse_rows(text: str) -> list[CatalogRow]:
    rows: list[CatalogRow] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = ROW_RE.match(line)
        if not match:
            continue
        rows.append(
            CatalogRow(
                fm_id=match.group(1),
                number=int(match.group(2)),
                line=line_number,
            )
        )
    return rows


def validate_catalog(text: str, rows: list[CatalogRow]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        errors.append("no canonical FM rows found")
        return errors, warnings

    duplicate_lines: dict[str, list[int]] = {}
    for row in rows:
        duplicate_lines.setdefault(row.fm_id, []).append(row.line)
    for fm_id, lines in sorted(duplicate_lines.items()):
        if len(lines) > 1:
            errors.append(
                f"duplicate canonical ID {fm_id} on lines {', '.join(map(str, lines))}"
            )

    for previous, current in zip(rows, rows[1:]):
        if current.number < previous.number:
            warnings.append(
                f"catalog rows out of order: {previous.fm_id} (line {previous.line}) "
                f"precedes {current.fm_id} (line {current.line})"
            )

    for line_number, line in enumerate(text.splitlines(), start=1):
        match = HISTORICAL_SCHEME_RE.search(line)
        if match:
            errors.append(
                f"historical alias scheme {match.group(0)} appears in canonical catalog on line {line_number}"
            )

    return errors, warnings


def next_id(rows: list[CatalogRow]) -> str:
    next_number = max(row.number for row in rows) + 1
    return f"FM-{next_number:02d}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", nargs="?", type=Path, default=default_catalog_path())
    parser.add_argument(
        "--next-id",
        action="store_true",
        help="print the next canonical FM ID instead of the validation summary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog_path: Path = args.catalog

    try:
        text = catalog_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    rows = parse_rows(text)
    errors, warnings = validate_catalog(text, rows)
    for warning in warnings:
        print(f"failure-mode-catalog: warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"failure-mode-catalog: {error}", file=sys.stderr)
        return 1

    if args.next_id:
        print(next_id(rows))
    else:
        print(
            f"failure-mode-catalog: OK ({len(rows)} canonical IDs, next {next_id(rows)})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
