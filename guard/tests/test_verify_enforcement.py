"""Contract tests for the L1 enforcement-existence verifier."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "guard" / "failure_mode_catalog_guard.py"
SPEC = importlib.util.spec_from_file_location("failure_mode_catalog_guard", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_records(l1_dir: Path, source: str, *records: dict[object, object]) -> None:
    (l1_dir / f"{source}.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def run_verifier(monkeypatch: pytest.MonkeyPatch, l1_dir: Path, projects: Path) -> int:
    monkeypatch.setattr(MODULE, "default_l1_dir", lambda: l1_dir)
    monkeypatch.setattr(MODULE, "default_projects_dir", lambda: projects)
    return MODULE.main(["--verify-enforcement"])


def machine_record(enforcement: dict[str, str] | None) -> dict[str, object]:
    return {"id": "example", "auto": "machine", "enforcement": enforcement}


def test_nonexistent_machine_enforcement_is_fatal_and_names_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    write_records(l1_dir, "sample", machine_record({"file": "missing/control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects) == 1
    assert "missing/control.py" in capsys.readouterr().err


def test_existing_machine_enforcement_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    write_records(l1_dir, "sample", machine_record({"file": "repo/control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects) == 0


def test_unbacked_machine_entry_warns_but_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    write_records(l1_dir, "sample", machine_record(None))

    assert run_verifier(monkeypatch, l1_dir, projects) == 0
    assert "WARNING" in capsys.readouterr().err


def test_unbacked_judgment_entry_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    write_records(l1_dir, "sample", {"id": "example", "auto": "judgment", "enforcement": None})

    assert run_verifier(monkeypatch, l1_dir, projects) == 0
    assert "WARNING" not in capsys.readouterr().err


def test_real_corpus_reports_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert MODULE.main(["--verify-enforcement"]) in {0, 1}
    output = capsys.readouterr().err
    assert "summary" in output.lower()
    assert "machine" in output.lower()
