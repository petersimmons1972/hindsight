"""Contract tests for the L1 schema validator.

The validator is deliberately exercised against temporary JSONL files here so
each malformed-record rule is proven independently of the checked-in corpus.

The last section covers the CLI layer -- the counts printed and the exit code
returned by `main`. That is the only part of this gate CI reads, and a validator
that announces a violation and then exits 0 is worse than no validator.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from pipeline import validate_l1
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


def test_rejects_padded_placeholder_instance(tmp_path: Path) -> None:
    """Whitespace must not smuggle a placeholder past the check."""
    report = validate(tmp_path, VALID_RECORD | {"instance": "  TODO  "})

    assert report.error_count == 1
    assert "instance must be non-empty and not a placeholder" in report.errors[0]


def test_rejects_null_auto(tmp_path: Path) -> None:
    """A present-but-null `auto` is a stated value, and it is not a permitted one."""
    report = validate(tmp_path, VALID_RECORD | {"auto": None})

    assert report.error_count == 1
    assert "auto must be exactly 'machine' or 'judgment'" in report.errors[0]


def test_rejects_non_string_id(tmp_path: Path) -> None:
    report = validate(tmp_path, VALID_RECORD | {"id": 12345})

    assert report.error_count == 1
    assert "id must be a string" in report.errors[0]


def test_rejects_empty_enforcement_object(tmp_path: Path) -> None:
    """`{}` is not `null`: an empty object must still owe file and kind.

    Per this repo's non-negotiables an honest null is a correct answer, but an
    empty mechanism reads as covered while enforcing nothing.
    """
    report = validate(tmp_path, VALID_RECORD | {"enforcement": {}})

    assert report.error_count == 2
    assert any("enforcement missing required key 'file'" in e for e in report.errors)
    assert any("enforcement missing required key 'kind'" in e for e in report.errors)


def test_rejects_non_string_enforcement_file(tmp_path: Path) -> None:
    record = VALID_RECORD | {"enforcement": {"file": 123, "kind": "test"}}

    report = validate(tmp_path, record)

    assert report.error_count == 1
    assert "enforcement.file must be a string" in report.errors[0]


def test_rejects_non_string_first_seen(tmp_path: Path) -> None:
    report = validate(tmp_path, VALID_RECORD | {"first_seen": 20260801})

    assert report.error_count == 1
    assert "first_seen must be null or a real YYYY-MM-DD date" in report.errors[0]


def test_rejects_date_shaped_string_that_is_not_canonical_iso(tmp_path: Path) -> None:
    """`20260801` parses on Python >= 3.11; the round-trip check is what rejects it."""
    report = validate(tmp_path, VALID_RECORD | {"first_seen": "20260801"})

    assert report.error_count == 1
    assert "first_seen must be null or a real YYYY-MM-DD date" in report.errors[0]


def test_rejects_non_object_record(tmp_path: Path) -> None:
    """A JSON array is well-formed JSON and still not a record."""
    report = validate(tmp_path, "[1, 2, 3]\n")

    assert report.error_count == 1
    assert "fixture.jsonl:1: record must be a JSON object" in report.errors[0]
    assert report.file_counts == {tmp_path / "fixture.jsonl": 1}


def test_blank_line_is_counted_and_rejected(tmp_path: Path) -> None:
    """A blank line is a malformed record, not an absent one."""
    report = validate(tmp_path, "\n")

    assert report.error_count == 1
    assert "fixture.jsonl:1: invalid JSON" in report.errors[0]
    assert report.file_counts == {tmp_path / "fixture.jsonl": 1}


def test_unreadable_file_is_an_error_not_an_empty_pass(tmp_path: Path) -> None:
    """"I could not read this file" must never render as "it is fine"."""
    unreadable = tmp_path / "unreadable.jsonl"
    unreadable.mkdir()

    report = validate_files([unreadable])

    assert report.error_count == 1
    assert "unable to read file" in report.errors[0]
    assert report.file_counts == {unreadable: 0}


def test_real_corpus_passes() -> None:
    root = Path(__file__).resolve().parents[2]

    report = validate_files(sorted((root / "pipeline" / "L1").glob("*.jsonl")))

    assert report.error_count == 0, "\n".join(report.errors)


# --- CLI layer: the counts printed and the exit code CI reads ----------------

SCRIPT = Path(validate_l1.__file__).resolve()


def build_corpus(tmp_path: Path, files: dict[str, str]) -> Path:
    """Copy the validator beside a synthetic L1 directory and return the script."""
    package = tmp_path / "pipeline"
    (package / "L1").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, package / "validate_l1.py")
    for name, text in files.items():
        (package / "L1" / name).write_text(text, encoding="utf-8")
    return package / "validate_l1.py"


def run_cli(script: Path) -> subprocess.CompletedProcess:
    # -B: never reuse bytecode; exit status read directly, never through a pipe.
    return subprocess.run(
        [sys.executable, "-B", str(script)], capture_output=True, text=True
    )


def jsonl(*records: dict[str, object]) -> str:
    return "".join(json.dumps(r) + "\n" for r in records)


def test_cli_counts_every_file_and_exits_0_on_a_valid_corpus(tmp_path: Path) -> None:
    script = build_corpus(
        tmp_path,
        {
            "a.jsonl": jsonl(VALID_RECORD, VALID_RECORD | {"id": "fixture-2"}),
            "z.jsonl": jsonl(VALID_RECORD | {"id": "fixture-3"}),
        },
    )

    result = run_cli(script)

    assert result.returncode == 0, result.stderr
    assert "TOTAL: 3 records across 2 files" in result.stdout
    assert "VALID: no schema violations" in result.stdout


def test_cli_exits_1_on_a_single_violation_in_a_later_file(tmp_path: Path) -> None:
    """One bad record, in a file that is not the first, must still fail the gate."""
    script = build_corpus(
        tmp_path,
        {
            "a.jsonl": jsonl(VALID_RECORD, VALID_RECORD | {"id": "fixture-2"}),
            "z.jsonl": jsonl(VALID_RECORD | {"id": "fixture-3", "auto": "automatic"}),
        },
    )

    result = run_cli(script)

    assert result.returncode == 1
    assert "TOTAL: 3 records across 2 files" in result.stdout
    assert "VALID: no schema violations" not in result.stdout
    assert "INVALID: 1 violation(s)" in result.stderr
    assert "auto must be exactly 'machine' or 'judgment'" in result.stderr


def test_main_reads_the_whole_checked_in_corpus(capsys) -> None:
    """`main` must reach every corpus file -- a glob that matches none reads VALID."""
    root = SCRIPT.parent
    files = sorted((root / "L1").glob("*.jsonl"))
    records = sum(len(f.read_text(encoding="utf-8").splitlines()) for f in files)
    assert len(files) >= 14 and records >= 400, "corpus fixture itself went vacuous"

    status = validate_l1.main()
    out = capsys.readouterr().out

    assert status == 0
    assert f"TOTAL: {records} records across {len(files)} files" in out
