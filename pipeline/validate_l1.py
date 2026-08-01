#!/usr/bin/env python3
"""Reject malformed L1 records before downstream synthesis can lose them.

The L1 corpus comes from independent extraction paths. Coverage reconciliation
can prove that expected entries exist, but cannot prove that each entry remains
usable. This validator makes malformed data an immediate, located failure
instead of a downstream crash or a silent omission.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


REQUIRED_KEYS = ("id", "source_path", "instance", "auto")
AUTO_VALUES = {"machine", "judgment"}
ENFORCEMENT_KINDS = {"test", "hook", "ci", "lint", "schema"}
PLACEHOLDER_INSTANCES = {"todo", "n/a", "unknown"}


@dataclass
class ValidationReport:
    """The counts and fully located problems found while reading L1 files."""

    file_counts: dict[Path, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return sum(self.file_counts.values())

    @property
    def error_count(self) -> int:
        return len(self.errors)


def validate_files(paths: Iterable[Path]) -> ValidationReport:
    """Validate all JSONL records in *paths* without stopping at the first error."""
    report = ValidationReport()
    seen_ids: dict[str, tuple[Path, int]] = {}

    for path in paths:
        count = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            report.errors.append(f"{path}: unable to read file: {exc}")
            report.file_counts[path] = count
            continue

        for line_number, line in enumerate(lines, start=1):
            count += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                report.errors.append(f"{path}:{line_number}: invalid JSON: {exc.msg}")
                continue

            if not isinstance(record, dict):
                report.errors.append(f"{path}:{line_number}: record must be a JSON object")
                continue

            validate_record(record, path, line_number, seen_ids, report.errors)
        report.file_counts[path] = count

    return report


def validate_record(
    record: dict[object, object],
    path: Path,
    line_number: int,
    seen_ids: dict[str, tuple[Path, int]],
    errors: list[str],
) -> None:
    """Append every rule violation for one decoded record."""
    location = f"{path}:{line_number}"
    for key in REQUIRED_KEYS:
        if key not in record:
            errors.append(f"{location}: missing required key '{key}'")

    auto = record.get("auto")
    if "auto" in record and auto not in AUTO_VALUES:
        errors.append(f"{location}: auto must be exactly 'machine' or 'judgment'")

    instance = record.get("instance")
    if "instance" in record and (
        not isinstance(instance, str)
        or not instance.strip()
        or instance.strip().lower() in PLACEHOLDER_INSTANCES
    ):
        errors.append(f"{location}: instance must be non-empty and not a placeholder")

    if "enforcement" in record:
        validate_enforcement(record["enforcement"], location, errors)
    if "first_seen" in record:
        validate_first_seen(record["first_seen"], location, errors)

    record_id = record.get("id")
    if "id" in record:
        if not isinstance(record_id, str):
            errors.append(f"{location}: id must be a string")
        elif record_id in seen_ids:
            first_path, first_line = seen_ids[record_id]
            errors.append(
                f"{location}: duplicate id '{record_id}' also appears at "
                f"{first_path}:{first_line}"
            )
        else:
            seen_ids[record_id] = (path, line_number)


def validate_enforcement(value: object, location: str, errors: list[str]) -> None:
    """Check the nested enforcement contract while preserving honest nulls."""
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{location}: enforcement must be null or an object")
        return
    for key in ("file", "kind"):
        if key not in value:
            errors.append(f"{location}: enforcement missing required key '{key}'")
    if "file" in value and not isinstance(value["file"], str):
        errors.append(f"{location}: enforcement.file must be a string")
    kind = value.get("kind")
    if "kind" in value and kind not in ENFORCEMENT_KINDS:
        permitted = ", ".join(sorted(ENFORCEMENT_KINDS))
        errors.append(f"{location}: enforcement.kind must be one of {permitted}")


def validate_first_seen(value: object, location: str, errors: list[str]) -> None:
    """Require an ISO calendar date, not merely a date-shaped string."""
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(f"{location}: first_seen must be null or a real YYYY-MM-DD date")
        return
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value:
        errors.append(f"{location}: first_seen must be null or a real YYYY-MM-DD date")


def main() -> int:
    """Validate the checked-in corpus and print counts even when it is invalid."""
    root = Path(__file__).resolve().parent
    files = sorted((root / "L1").glob("*.jsonl"))
    report = validate_files(files)

    for path, count in report.file_counts.items():
        print(f"{path.relative_to(root)}: {count} records")
    print(f"TOTAL: {report.total_count} records across {len(report.file_counts)} files")
    if report.errors:
        print(f"INVALID: {report.error_count} violation(s)", file=sys.stderr)
        for error in report.errors:
            print(error, file=sys.stderr)
        return 1
    print("VALID: no schema violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
