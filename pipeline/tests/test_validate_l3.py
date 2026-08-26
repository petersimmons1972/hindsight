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


def _with_default_invariant(row):
    """Inject a placeholder non-empty `invariant` for a PR #63 fixture row that
    lacks one. The founder-authorized ground-truth fixture (pipeline/tests/
    fixtures/l3_ground_truth.jsonl) predates the `invariant` field and only
    grades kind/enforcement/source_repos/procedural_substitute -- it is never
    edited here (R3). This keeps each ground-truth case isolated to the one
    dimension it is actually testing instead of also (accidentally or not)
    exercising the invariant-emptiness check added below.
    """
    if "invariant" in row:
        # A fixture case that deliberately sets `invariant` (including a
        # blank one, to test the emptiness check itself) is left alone --
        # only an absent key gets a placeholder.
        return row
    return {**row, "invariant": "Test-injected placeholder invariant (not part of the pinned PR #63 fixture row)."}


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
    _write_ledger(ledger, _with_default_invariant(case["row"]))
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


@pytest.mark.parametrize(
    "raw_line",
    ["[1, 2, 3]", '"hello"', "42", "true"],
    ids=["json-list", "json-string", "json-number", "json-bool"],
)
def test_ledger_line_that_parses_but_is_not_an_object_fails_loud(tmp_path, raw_line):
    """A ledger line can be valid JSON without being a JSON object -- a bare
    list, string, number, or bool. load_ledger only null-checks on
    JSONDecodeError, so a non-dict row previously reached check_row's
    row.get(...) calls and crashed with an uncaught AttributeError instead
    of a structured failure -- the same defect class as D2/D3/D4, one level
    up from check_row."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(raw_line + "\n")
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters)
    result = _run(ledger, clusters)
    assert result.returncode == 1, (
        f"raw_line={raw_line!r} unexpectedly validated: {result.stdout + result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "Traceback" not in combined, f"must fail structurally, not crash: {combined}"


_D3_BASE_ROW = {
    "cluster_ids": ["fixture-multirepo"],
    "kind": "judgment",
    "invariant": "A generalized claim for the D3 bypass regression cases.",
    "procedural_substitute": "Require an independent reviewer to inspect the rendered artifact before release.",
}


@pytest.mark.parametrize(
    "source_repos",
    ["ab", "fleet", {"a": 1, "b": 2}, ["repo-a", 1], 12, True, ["repo-a", ""], ["repo-a", "repo-a "]],
    ids=[
        "str-two-chars",
        "str-multi-chars",
        "dict-two-keys",
        "list-with-nonstring-member",
        "bare-int",
        "bare-bool",
        "list-with-blank-string",
        "list-with-whitespace-duplicate",
    ],
)
def test_d3_rejects_non_list_or_non_string_source_repos(tmp_path, source_repos):
    """Regression for Grok review r2 Probe C: a string/dict source_repos (or a
    list containing a blank/whitespace/non-string element) previously cleared
    the >=2-distinct-repos bar (or crashed with an uncaught TypeError instead
    of a structured D3 failure). All of these must now be rejected with a
    named D3 error and no traceback."""
    row = {**_D3_BASE_ROW, "source_repos": source_repos}
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, row)
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters)
    result = _run(ledger, clusters)
    assert result.returncode == 1, (
        f"source_repos={source_repos!r} unexpectedly validated: {result.stdout + result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "D3" in combined, f"expected a named D3 failure, got: {combined}"
    assert "Traceback" not in combined, f"D3 must fail structurally, not crash: {combined}"


@pytest.mark.parametrize(
    "invariant_value,present",
    [(None, False), ("", True), ("   ", True), (12, True), ({"a": 1}, True)],
    ids=["key-absent", "empty-string", "whitespace-only", "bare-int", "dict"],
)
def test_invariant_field_rejects_empty_or_blank(tmp_path, invariant_value, present):
    """Regression for Grok review r2 Probe A: a missing, empty, or
    whitespace-only `invariant` field previously validated clean (exit 0).
    docs/L3.md publishes `invariant` as a required schema field; an
    'invariant ledger' that never inspects `invariant` grades hollow rows
    green. Also covers the same type-confusion class D3 was refuted for:
    a naive `not invariant or not str(invariant).strip()` check would let
    a non-string (12, a dict) through once stringified/truthy -- invariant
    must be an actual non-blank string, not anything coercible to one."""
    row = {
        "cluster_ids": ["fixture-multirepo"],
        "source_repos": ["repo-a", "repo-b"],
        "kind": "judgment",
        "procedural_substitute": "Require an independent reviewer to inspect the rendered artifact before release.",
    }
    if present:
        row["invariant"] = invariant_value
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, row)
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters)
    result = _run(ledger, clusters)
    assert result.returncode == 1, (
        f"invariant={invariant_value!r} (present={present}) unexpectedly validated: "
        f"{result.stdout + result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "invariant" in combined.lower(), f"expected an invariant-named failure, got: {combined}"


@pytest.mark.parametrize(
    "substitute_value",
    [12, {"a": 1}, ["x"], True],
    ids=["bare-int", "dict", "list", "bare-bool"],
)
def test_d4_rejects_non_string_procedural_substitute(tmp_path, substitute_value):
    """Same type-confusion class as D3/invariant, in the third field
    check_row grades with a plain truthiness/str() check: a naive
    `not substitute or not str(substitute).strip()` lets a non-string
    substitute through once stringified/truthy (12 -> "12", non-blank)."""
    row = {
        "cluster_ids": ["fixture-multirepo"],
        "source_repos": ["repo-a", "repo-b"],
        "kind": "judgment",
        "invariant": "A generalized claim for the D4 type-confusion regression case.",
        "procedural_substitute": substitute_value,
    }
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, row)
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters)
    result = _run(ledger, clusters)
    assert result.returncode == 1, (
        f"procedural_substitute={substitute_value!r} unexpectedly validated: "
        f"{result.stdout + result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "procedural_substitute" in combined, f"expected a named D4 failure, got: {combined}"
    assert "Traceback" not in combined


@pytest.mark.parametrize(
    "path_value",
    [12, {"a": 1}, ["x"], True],
    ids=["bare-int", "dict", "list", "bare-bool"],
)
def test_d2_rejects_non_string_enforcement_path(tmp_path, path_value):
    """Same type-confusion class, in enforcement.path: a non-string path
    previously cleared the truthiness gate (`not enforcement.get("path")`)
    and then crashed os.path.isabs() with an uncaught TypeError under
    --assert-paths-exist, instead of a structured D2 failure."""
    row = {
        "cluster_ids": ["fixture-multirepo"],
        "source_repos": ["repo-a", "repo-b"],
        "kind": "machine",
        "invariant": "A generalized claim for the D2 type-confusion regression case.",
        "enforcement": {"repo": "hindsight", "path": path_value},
    }
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, row)
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters)
    result = _run(ledger, clusters, extra_args=["--assert-paths-exist"], repo_root=REPO_ROOT)
    assert result.returncode == 1, (
        f"enforcement.path={path_value!r} unexpectedly validated: {result.stdout + result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "D2" in combined, f"expected a named D2 failure, got: {combined}"
    assert "Traceback" not in combined


def test_real_ledger_rows_all_have_nonempty_invariant():
    """Ground truth: the committed seed ledger must itself satisfy the new
    invariant-emptiness check (not just the synthetic fixture cases)."""
    real_ledger = REPO_ROOT / "pipeline" / "L3" / "invariants.jsonl"
    with open(real_ledger) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            assert str(row.get("invariant") or "").strip(), f"row {row.get('id')} has empty invariant"


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
