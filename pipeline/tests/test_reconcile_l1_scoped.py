"""Hermetic contract tests for source-scoped L1 reconciliation.

The fixture deliberately keeps one source short and another source unresolved.
That makes a scoped result distinguishable from the all-source result without
consulting any sibling checkout on the test host.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RECONCILER = ROOT / "pipeline" / "reconcile_l1.py"
CANONICAL = "homelab-canon"
SHORT = "fleet-orch"
UNRESOLVED = "claude-codex-integration"
ALL_SOURCES = {
    "fleet-main",
    "fleet-orch",
    "homelab-canon",
    "claude-codex-integration",
    "fleet-dispatch-schema",
}


def _record(local_id: str) -> str:
    return json.dumps({"id": local_id, "instance": "fixture", "source_path": "fixture"}) + "\n"


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    """Create a relocated checkout with a healthy, short, and absent source."""
    projects = tmp_path / "projects"
    repo = projects / "hindsight"
    (repo / "pipeline" / "L1").mkdir(parents=True)
    (repo / "catalog").mkdir()
    (repo / "pipeline" / "reconcile_l1.py").write_bytes(RECONCILER.read_bytes())

    (repo / "catalog" / "failure-modes.md").write_text(
        "| ID | Class | Instance | Lesson | Enforcement |\n"
        "| FM-001 | A | one | one | Judgment |\n"
        "| FM-002 | A | two | two | Judgment |\n",
        encoding="utf-8",
    )
    (repo / "pipeline" / "L1" / "homelab-canon.jsonl").write_text(
        _record("FM-001") + _record("FM-002"), encoding="utf-8"
    )

    (projects / "fleet" / "orchestration").mkdir(parents=True)
    (projects / "fleet" / "FAILURE-MODES.md").write_text("## OPS-1\n", encoding="utf-8")
    (projects / "fleet" / "orchestration" / "FAILURE-MODES.md").write_text(
        "## OPS-2\n## OPS-99\n", encoding="utf-8"
    )
    (projects / "fleet" / "CODING-INVARIANTS.md").write_text("## CI-1\n", encoding="utf-8")
    (projects / "fleet" / "CODING-FAILURE-MODES.md").write_text("## FM-1\n", encoding="utf-8")
    (repo / "pipeline" / "L1" / "fleet-main.jsonl").write_text(
        _record("OPS-1"), encoding="utf-8"
    )
    (repo / "pipeline" / "L1" / "fleet-orch.jsonl").write_text(
        _record("OPS-2") + _record("CI-1") + _record("FM-1"), encoding="utf-8"
    )

    (projects / "fleet-dispatch" / "migrations").mkdir(parents=True)
    (projects / "fleet-dispatch" / "migrations" / "0017_failure_class.sql").write_text(
        "CHECK (failure_class IN ('fixture_failure'))\n", encoding="utf-8"
    )
    (repo / "pipeline" / "L1" / "fleet-dispatch-schema.jsonl").write_text(
        _record("fixture_failure"), encoding="utf-8"
    )

    # The claude-codex source is intentionally absent. Its configured path is
    # still part of the copied reconciler's source set, so a selected run must
    # report UNVERIFIED rather than treating an empty truth set as 100%.
    return repo


def run_reconcile(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "pipeline" / "reconcile_l1.py"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def verdict_line(stdout: str) -> str:
    return next(line for line in stdout.splitlines() if "unaccounted for" in line)


def test_selected_healthy_source_succeeds_when_unselected_source_is_short(fixture_repo: Path) -> None:
    result = run_reconcile(fixture_repo, "--source", CANONICAL)

    assert result.returncode == 0
    assert verdict_line(result.stdout).startswith("COMPLETE:")


def test_selected_short_source_fails(fixture_repo: Path) -> None:
    result = run_reconcile(fixture_repo, "--source", SHORT)

    assert result.returncode == 1
    assert verdict_line(result.stdout).startswith("SHORT:")
    assert "OPS-99" in result.stdout


def test_selected_unresolved_source_fails_and_is_not_reported_as_100_percent(
    fixture_repo: Path,
) -> None:
    result = run_reconcile(fixture_repo, "--json", "--source", UNRESOLVED)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report == [
        {
            "slug": UNRESOLVED,
            "ground_truth": 0,
            "jsonl_lines": 0,
            "covered": 0,
            "coverage_pct": None,
            "resolved": False,
            "missing": [],
        }
    ]


def test_unknown_repeated_and_empty_selectors_are_usage_failures(fixture_repo: Path) -> None:
    invalid_invocations = [
        ("unknown", ["--source", "no-such-source"]),
        ("repeated", ["--source", CANONICAL, "--source", CANONICAL]),
        ("empty", ["--source", ""]),
    ]

    for label, args in invalid_invocations:
        result = run_reconcile(fixture_repo, *args)
        assert result.returncode == 2, f"{label} selector was accepted: {result.stdout}{result.stderr}"
        assert "COMPLETE" not in result.stdout


def test_no_selector_preserves_all_source_short_over_partial_precedence(
    fixture_repo: Path,
) -> None:
    result = run_reconcile(fixture_repo)

    assert result.returncode == 1
    assert verdict_line(result.stdout).startswith("SHORT:")
    assert "(4/5 sources resolved)" in verdict_line(result.stdout)


def test_json_output_contains_only_selected_rows(fixture_repo: Path) -> None:
    result = run_reconcile(fixture_repo, "--json", "--source", CANONICAL)

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert {row["slug"] for row in report} == {CANONICAL}
    assert {row["slug"] for row in report} <= ALL_SOURCES
    assert result.stderr
