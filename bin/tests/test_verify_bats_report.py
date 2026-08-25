"""Adversarial tests for bin/verify_bats_report.py (hindsight#170).

Every case tries to break the consumer: missing/empty/malformed TAP, count
padding, title forgery, duplicated real titles, and a failing (not ok) line.
A green confirmation of the happy path alone is not sufficient.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "bin" / "verify_bats_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_bats_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_bats(tests_dir: Path, titles: list[str]) -> None:
    tests_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f'@test "{t}" {{\n  true\n}}' for t in titles) + "\n"
    (tests_dir / "suite.bats").write_text(body, encoding="utf-8")


def _write_tap(report: Path, lines: list[str]) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def vmod():
    assert SCRIPT.is_file()
    return _load()


def test_happy_path_exact_titles_and_count(tmp_path: Path, vmod) -> None:
    titles = ["alpha case", "beta case", "gamma case"]
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, titles)
    _write_tap(
        report,
        ["1..3"]
        + [f"ok {i} {t}" for i, t in enumerate(titles, 1)],
    )
    vmod.verify(report, tests)
    proc = _run(str(report), str(tests))
    assert proc.returncode == 0, proc.stderr
    assert "OK (3 cases" in proc.stdout


def test_hash_inside_title_is_not_a_tap_directive(tmp_path: Path, vmod) -> None:
    """Regression: 'issue #89' must not be truncated at '#' (bats keeps it)."""
    titles = [
        "F3-relabel — HELD still grades (issue #89)",
        "plain title",
    ]
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, titles)
    _write_tap(
        report,
        ["1..2"]
        + [f"ok {i} {t}" for i, t in enumerate(titles, 1)],
    )
    vmod.verify(report, tests)


def test_skip_directive_is_stripped_but_title_still_matches(tmp_path: Path, vmod) -> None:
    titles = ["skipped one", "kept"]
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, titles)
    _write_tap(
        report,
        [
            "1..2",
            "ok 1 skipped one # skip because",
            "ok 2 kept",
        ],
    )
    vmod.verify(report, tests)


def test_missing_report_fails_nonzero(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    _write_bats(tests, ["only"])
    proc = _run(str(tmp_path / "missing.tap"), str(tests))
    assert proc.returncode != 0
    assert "missing" in proc.stderr.lower()


def test_empty_report_fails_nonzero(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, ["only"])
    report.write_text("\n", encoding="utf-8")
    proc = _run(str(report), str(tests))
    assert proc.returncode != 0
    assert "empty" in proc.stderr.lower()


def test_malformed_report_with_no_results_fails(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, ["only"])
    _write_tap(report, ["1..1", "# a comment", "Bail out! nope"])
    proc = _run(str(report), str(tests))
    assert proc.returncode != 0
    assert "zero ok/not ok" in proc.stderr


def test_not_ok_line_fails_even_when_count_matches(tmp_path: Path) -> None:
    titles = ["a", "b"]
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, titles)
    _write_tap(report, ["1..2", "ok 1 a", "not ok 2 b"])
    proc = _run(str(report), str(tests))
    assert proc.returncode != 0
    assert "failing case" in proc.stderr


def test_undercount_below_live_floor_fails(tmp_path: Path) -> None:
    titles = ["a", "b", "c"]
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, titles)
    _write_tap(report, ["1..2", "ok 1 a", "ok 2 b"])
    proc = _run(str(report), str(tests))
    assert proc.returncode != 0
    assert "floor" in proc.stderr


def test_tap_stub_forgery_with_matching_count_fails_title_crossref(
    tmp_path: Path,
) -> None:
    """Attack C: N synthetic ok lines, count matches floor, titles are fake."""
    titles = [f"real title {i}" for i in range(1, 6)]
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, titles)
    _write_tap(
        report,
        ["1..5"] + [f"ok {i} fake test {i}" for i in range(1, 6)],
    )
    proc = _run(str(report), str(tests))
    assert proc.returncode != 0
    assert "not present as @test" in proc.stderr


def test_padded_with_duplicated_real_titles_fails(tmp_path: Path) -> None:
    """Count matches floor only if we allow duplicates — refuse padding."""
    titles = ["a", "b", "c"]
    tests = tmp_path / "tests"
    report = tmp_path / "report.tap"
    _write_bats(tests, titles)
    # Three results, all real titles, but "a" repeated and "c" missing.
    _write_tap(report, ["1..3", "ok 1 a", "ok 2 b", "ok 3 a"])
    proc = _run(str(report), str(tests))
    assert proc.returncode != 0
    assert (
        "missing from TAP" in proc.stderr
        or "repeats titles" in proc.stderr
    )


def test_live_bin_tests_floor_is_positive_and_matches_glob() -> None:
    """Sanity: the real tree's floor is read live, never hardcoded."""
    vmod = _load()
    titles = vmod.collect_source_titles(REPO / "bin" / "tests")
    assert len(titles) >= 1
    # Premise-diverse check: grep -c style count must agree.
    import re

    counted = 0
    for path in sorted((REPO / "bin" / "tests").glob("*.bats")):
        counted += sum(
            1
            for line in path.read_text(encoding="utf-8").splitlines()
            if re.match(r'^\s*@test\s+"', line)
        )
    assert len(titles) == counted


def test_cli_requires_two_args() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
