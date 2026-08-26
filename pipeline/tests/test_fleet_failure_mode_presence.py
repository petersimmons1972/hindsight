"""Contracts for the fleet L1 refresh and canonical-presence watchdog."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline import check_fleet_canonical_presence, extract_fleet_l1


def _write_source(path: Path, heading: str, *, lie: str, countermeasure: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"## {heading}\n"
        f"- **Lie:** {lie}\n"
        f"- **Countermeasure:** {countermeasure}\n",
        encoding="utf-8",
    )


def test_refresh_appends_a_structured_record_for_an_unaccounted_source_heading(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fleet" / "FAILURE-MODES.md"
    l1 = tmp_path / "L1" / "fleet-main.jsonl"
    _write_source(
        source,
        "CI-18 — baseline passes",
        lie="a green baseline proves the fix",
        countermeasure="run the unfixed baseline too",
    )

    assert extract_fleet_l1.refresh_one(source, l1, "fleet") == 1

    record = json.loads(l1.read_text(encoding="utf-8"))
    assert record == {
        "id": "fleet-CI-18",
        "source_path": "fleet/FAILURE-MODES.md",
        "source_anchor": "CI-18 — baseline passes",
        "instance": "a green baseline proves the fix",
        "check": "run the unfixed baseline too",
        "enforcement": None,
        "auto": "judgment",
        "first_seen": None,
        "canonical_status": "unreviewed",
    }


def test_presence_checker_fails_loudly_for_a_source_mode_absent_from_catalog(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "fleet" / "FAILURE-MODES.md"
    l1 = tmp_path / "L1" / "fleet-main.jsonl"
    catalog = tmp_path / "catalog.md"
    _write_source(source, "CI-18 — baseline passes", lie="bad", countermeasure="good")
    l1.parent.mkdir(parents=True)
    l1.write_text(json.dumps({"id": "fleet-CI-18", "canonical_status": "unreviewed"}) + "\n", encoding="utf-8")
    catalog.write_text("| FM-001 | unrelated |\n", encoding="utf-8")

    status = check_fleet_canonical_presence.check_sources(
        [("fleet-main", source, l1)], catalog
    )

    assert status == 1
    out = capsys.readouterr().out
    assert "CANONICAL-SHORT: 1" in out
    assert "fleet-main:CI-18 L1=COVERED CATALOG=ABSENT" in out


def test_presence_checker_accepts_an_exact_catalog_title_match(tmp_path: Path, capsys) -> None:
    source = tmp_path / "fleet" / "FAILURE-MODES.md"
    l1 = tmp_path / "L1" / "fleet-main.jsonl"
    catalog = tmp_path / "catalog.md"
    _write_source(source, "CI-18 — baseline passes", lie="bad", countermeasure="good")
    l1.parent.mkdir(parents=True)
    l1.write_text(json.dumps({"id": "fleet-CI-18", "canonical_status": "unreviewed"}) + "\n", encoding="utf-8")
    catalog.write_text("| FM-001 | class | baseline passes | check |\n", encoding="utf-8")

    status = check_fleet_canonical_presence.check_sources(
        [("fleet-main", source, l1)], catalog
    )

    assert status == 0
    assert "CANONICAL-COMPLETE: 0" in capsys.readouterr().out
