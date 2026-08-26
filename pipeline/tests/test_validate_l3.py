"""Tests for pipeline/validate_l3.py (plan-06 D1-D6, hindsight#21).

The primary fixture, pipeline/tests/fixtures/l3_ground_truth.jsonl, is the
founder-authorized ground truth committed in PR #63 (2026-08-03, co-authored
by the founder) -- this test module is table-driven off THAT fixture per
plan-06 section 8's red-first procedure, rather than inventing its own
scenarios: the synthesizing session does not get to author the fixture that
grades it (R3).

Each fixture line is {"case", "row", "expect_valid", "expect_error"?}. This
module writes each case's `row` out as a one-line ledger, runs
validate_l3.py against it, and asserts the exit code (and, on a designed
failure, that the stderr names the field the plan's D-clause says must be
named) match the fixture's own expectation.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_L3 = REPO_ROOT / "pipeline" / "validate_l3.py"
GROUND_TRUTH = REPO_ROOT / "pipeline" / "tests" / "fixtures" / "l3_ground_truth.jsonl"


def _load_ground_truth_cases():
    cases = []
    with open(GROUND_TRUTH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


GROUND_TRUTH_CASES = _load_ground_truth_cases()


def _write_clusters(path, non_empty=True):
    with open(path, "w") as f:
        f.write(json.dumps({"_meta": {"backend": "test"}}) + "\n")
        if non_empty:
            f.write(json.dumps({"cluster_id": "c-gt", "source_repos": ["a", "b"]}) + "\n")


def _write_ledger(path, row):
    with open(path, "w") as f:
        f.write(json.dumps(row) + "\n")


def _run(ledger, clusters, extra_args=None, repo_root=None):
    args = [sys.executable, str(VALIDATE_L3), "--ledger", str(ledger), "--clusters", str(clusters)]
    if repo_root is not None:
        args += ["--repo-root", str(repo_root)]
    if extra_args:
        args += extra_args
    return subprocess.run(args, capture_output=True, text=True)


@pytest.mark.parametrize("case", GROUND_TRUTH_CASES, ids=[c["case"] for c in GROUND_TRUTH_CASES])
def test_ground_truth_case(tmp_path, case):
    """Table-driven against the founder-authorized fixture -- red-first per plan-06 section 8."""
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, case["row"])
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters)
    result = _run(ledger, clusters, extra_args=["--assert-paths-exist"], repo_root=REPO_ROOT)

    if case["expect_valid"]:
        assert result.returncode == 0, (
            f"case {case['case']!r} expected valid but got exit "
            f"{result.returncode}: {result.stdout + result.stderr}"
        )
    else:
        assert result.returncode == 1, f"case {case['case']!r} expected invalid but got exit 0"
        expect_error = case.get("expect_error")
        if expect_error:
            combined = result.stdout + result.stderr
            assert expect_error in combined, (
                f"case {case['case']!r} expected error mentioning {expect_error!r}, "
                f"got: {combined}"
            )


def test_real_ledger_passes():
    """A1: the real, committed ledger validates clean against the real clusters file."""
    real_ledger = REPO_ROOT / "pipeline" / "L3" / "invariants.jsonl"
    real_clusters = REPO_ROOT / "pipeline" / "L2" / "clusters.jsonl"
    result = _run(real_ledger, real_clusters)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_ledger_passes_with_assert_paths_exist():
    """A2: every machine-kind path in the real ledger actually resolves."""
    real_ledger = REPO_ROOT / "pipeline" / "L3" / "invariants.jsonl"
    real_clusters = REPO_ROOT / "pipeline" / "L2" / "clusters.jsonl"
    result = _run(real_ledger, real_clusters, extra_args=["--assert-paths-exist"], repo_root=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_empty_clusters_file_fails_loud(tmp_path):
    """D5: empty clusters.jsonl must exit 1, never a silent empty-ledger pass."""
    clusters = tmp_path / "empty_clusters.jsonl"
    clusters.write_text("")
    ledger = tmp_path / "empty_ledger.jsonl"
    ledger.write_text("")
    result = _run(ledger, clusters)
    assert result.returncode == 1


def test_missing_clusters_file_fails_loud(tmp_path):
    """D5: a --clusters path that does not exist at all must exit 1, not crash-as-0."""
    clusters = tmp_path / "does_not_exist.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    result = _run(ledger, clusters)
    assert result.returncode == 1


def test_dev_null_clusters_fails_loud():
    """A5 exact command: --clusters /dev/null must exit 1."""
    ledger = REPO_ROOT / "pipeline" / "L3" / "invariants.jsonl"
    result = subprocess.run(
        [sys.executable, str(VALIDATE_L3), "--ledger", str(ledger), "--clusters", "/dev/null"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1


def test_missing_ledger_fails_loud(tmp_path):
    """A missing --ledger must also fail loud, not silently pass on zero rows."""
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters)
    ledger = tmp_path / "does_not_exist.jsonl"
    result = _run(ledger, clusters)
    assert result.returncode == 1


def test_judgment_count_matches_substitute_count():
    """A6: count of kind=judgment rows equals count of rows carrying a non-null substitute,
    on the real committed ledger."""
    real_ledger = REPO_ROOT / "pipeline" / "L3" / "invariants.jsonl"
    judgment = 0
    with_substitute = 0
    with open(real_ledger) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("kind") == "judgment":
                judgment += 1
            if row.get("procedural_substitute"):
                with_substitute += 1
    assert judgment == with_substitute
    assert judgment > 0
