"""Contract tests for the L1 schema validator.

The validator is deliberately exercised against temporary JSONL files here so
each malformed-record rule is proven independently of the checked-in corpus.
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.validate_l1 import validate_files


VALID_RECORD = {
    "id": "fixture-1",
    "source_path": "docs/source.md",
    "instance": "A concrete failure happened.",
    "auto": "machine",
    "enforcement": None,
    "first_seen": "2026-08-01",
}


def write_jsonl(path: Path, *records: object) -> Path:
    path.write_text(
        "".join(
            record if isinstance(record, str) else json.dumps(record) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return path


def validate(tmp_path: Path, *records: object):
    return validate_files([write_jsonl(tmp_path / "fixture.jsonl", *records)])


def test_valid_fixture_passes(tmp_path: Path) -> None:
    report = validate(tmp_path, VALID_RECORD)

    assert report.error_count == 0
    assert report.file_counts == {tmp_path / "fixture.jsonl": 1}


def test_rejects_malformed_json_with_location_and_rule(tmp_path: Path) -> None:
    report = validate(tmp_path, "{not json}\n")

    assert report.error_count == 1
    assert "fixture.jsonl:1: invalid JSON" in report.errors[0]


def test_rejects_each_missing_required_key(tmp_path: Path) -> None:
    records = []
    for index, key in enumerate(("id", "source_path", "instance", "auto"), start=1):
        record = VALID_RECORD | {"id": f"fixture-{index}"}
        del record[key]
        records.append(record)

    report = validate(tmp_path, *records)

    assert report.error_count == 4
    for key in ("id", "source_path", "instance", "auto"):
        assert any(f"missing required key '{key}'" in error for error in report.errors)


def test_rejects_invalid_auto(tmp_path: Path) -> None:
    record = VALID_RECORD | {"auto": "automatic"}

    report = validate(tmp_path, record)

    assert report.error_count == 1
    assert "auto must be exactly 'machine' or 'judgment'" in report.errors[0]


def test_rejects_malformed_enforcement(tmp_path: Path) -> None:
    records = [
        VALID_RECORD | {"enforcement": "test"},
        VALID_RECORD | {"id": "fixture-2", "enforcement": {"file": "x"}},
        VALID_RECORD | {"id": "fixture-3", "enforcement": {"file": "x", "kind": "other"}},
    ]

    report = validate(tmp_path, *records)

    assert report.error_count == 3
    assert any("enforcement must be null or an object" in error for error in report.errors)
    assert any("enforcement missing required key 'kind'" in error for error in report.errors)
    assert any("enforcement.kind must be one of" in error for error in report.errors)


def test_rejects_invalid_dates(tmp_path: Path) -> None:
    records = [
        VALID_RECORD | {"first_seen": "2026-02-30"},
        VALID_RECORD | {"id": "fixture-2", "first_seen": "01-08-2026"},
    ]

    report = validate(tmp_path, *records)

    assert report.error_count == 2
    assert all("first_seen must be null or a real YYYY-MM-DD date" in error for error in report.errors)


def test_rejects_duplicate_id_across_source_files(tmp_path: Path) -> None:
    first = write_jsonl(tmp_path / "first.jsonl", VALID_RECORD)
    second = write_jsonl(tmp_path / "second.jsonl", VALID_RECORD)

    report = validate_files([first, second])

    assert report.error_count == 1
    assert "duplicate id 'fixture-1'" in report.errors[0]
    assert "first.jsonl:1" in report.errors[0]
    assert "second.jsonl:1" in report.errors[0]


def test_rejects_placeholder_instances(tmp_path: Path) -> None:
    records = [
        VALID_RECORD | {"instance": value, "id": f"fixture-{index}"}
        for index, value in enumerate(("TODO", "N/A", "unknown", ""), start=1)
    ]

    report = validate(tmp_path, *records)

    assert report.error_count == 4
    assert all("instance must be non-empty and not a placeholder" in error for error in report.errors)


def test_real_corpus_passes() -> None:
    root = Path(__file__).resolve().parents[2]

    report = validate_files(sorted((root / "pipeline" / "L1").glob("*.jsonl")))

    assert report.error_count == 0, "\n".join(report.errors)
