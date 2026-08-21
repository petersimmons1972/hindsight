"""hindsight#116 — open guard backlog report.

The report answers one question: which failure modes were filed with
disposition ``mechanize`` and still have ``enforcement: null``. That is the
open guard backlog. Existing criticality rows with no ``disposition`` field
are pre-O2 records; they are skipped, not errors, and they are not the
backlog (no retrofit campaign).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "bin" / "report-guard-backlog.py"


def run_report(*args: str, criticality: Path | None = None, l1: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(REPORT), *args]
    if criticality is not None:
        cmd.extend(["--criticality", str(criticality)])
    if l1 is not None:
        cmd.extend(["--l1", str(l1)])
    return subprocess.run(
        cmd,
        cwd=str(REPO),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def write_jsonl(path: Path, *records: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_lists_mechanize_null_and_excludes_mechanize_enforced(tmp_path: Path) -> None:
    criticality = write_jsonl(
        tmp_path / "criticality.jsonl",
        {"fm_id": "FM-001", "disposition": "mechanize"},
        {"fm_id": "FM-002", "disposition": "mechanize"},
    )
    l1 = write_jsonl(
        tmp_path / "l1" / "records.jsonl",
        {
            "id": "hc-FM-001",
            "enforcement": None,
            "instance": "open guard",
            "source_path": "fixture",
            "auto": "judgment",
        },
        {
            "id": "hc-FM-002",
            "enforcement": {"file": "guard/test_enforced.py", "kind": "test"},
            "instance": "already guarded",
            "source_path": "fixture",
            "auto": "machine",
        },
    )

    result = run_report(criticality=criticality, l1=l1.parent)

    assert result.returncode == 0, result.stdout
    assert "FM-001" in result.stdout
    assert "FM-002" not in result.stdout


def test_missing_disposition_is_not_an_error_and_is_not_the_backlog(tmp_path: Path) -> None:
    """Pre-O2 rows have no disposition. Readers must not break, and must not
    invent a retrofit by treating absence as mechanize."""
    criticality = write_jsonl(
        tmp_path / "criticality.jsonl",
        {"fm_id": "FM-010", "tier": "HIGH", "generality": "NARROW"},
        {"fm_id": "FM-011", "disposition": "mechanize"},
    )
    l1 = write_jsonl(
        tmp_path / "l1" / "canon.jsonl",
        {
            "id": "FM-010",
            "enforcement": None,
            "instance": "legacy unenforced",
            "source_path": "fixture",
            "auto": "judgment",
        },
        {
            "id": "FM-011",
            "enforcement": None,
            "instance": "new unenforced mechanize",
            "source_path": "fixture",
            "auto": "judgment",
        },
    )

    result = run_report(criticality=criticality, l1=l1)

    assert result.returncode == 0, result.stdout
    assert "FM-011" in result.stdout
    assert "FM-010" not in result.stdout


def test_advisory_and_brief_inject_are_excluded_even_when_unenforced(tmp_path: Path) -> None:
    criticality = write_jsonl(
        tmp_path / "criticality.jsonl",
        {"fm_id": "FM-020", "disposition": "advisory"},
        {"fm_id": "FM-021", "disposition": "brief-inject"},
        {"fm_id": "FM-022", "disposition": "mechanize"},
    )
    l1 = write_jsonl(
        tmp_path / "l1.jsonl",
        {"id": "hc-FM-020", "enforcement": None, "instance": "a", "source_path": "f", "auto": "judgment"},
        {"id": "hc-FM-021", "enforcement": None, "instance": "b", "source_path": "f", "auto": "judgment"},
        {"id": "hc-FM-022", "enforcement": None, "instance": "c", "source_path": "f", "auto": "judgment"},
    )

    result = run_report(criticality=criticality, l1=l1)

    assert result.returncode == 0, result.stdout
    assert "FM-022" in result.stdout
    assert "FM-020" not in result.stdout
    assert "FM-021" not in result.stdout


def test_mechanize_with_no_l1_row_is_unenforced_backlog(tmp_path: Path) -> None:
    criticality = write_jsonl(
        tmp_path / "criticality.jsonl",
        {"fm_id": "FM-030", "disposition": "mechanize"},
    )
    l1 = write_jsonl(tmp_path / "l1.jsonl")

    result = run_report(criticality=criticality, l1=l1)

    assert result.returncode == 0, result.stdout
    assert "FM-030" in result.stdout


def test_malformed_criticality_fails_loudly(tmp_path: Path) -> None:
    criticality = tmp_path / "criticality.jsonl"
    criticality.write_text("{not json\n", encoding="utf-8")
    l1 = write_jsonl(tmp_path / "l1.jsonl")

    result = run_report(criticality=criticality, l1=l1)

    assert result.returncode != 0
    assert "criticality" in result.stdout.lower() or "json" in result.stdout.lower()
