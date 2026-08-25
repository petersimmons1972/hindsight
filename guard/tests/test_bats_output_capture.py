"""Regression: CI bats steps must surface $output when a case fails.

hindsight#153: the guard/tests bats step discarded captured run-block output
on failure because it lacked --print-output-on-failure. A nonzero exit alone
is not enough — that already happened before the fix. This suite drives a
deliberately failing fixture and asserts the diagnostic body survives.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

MARKER = "DIAGNOSTIC_MARKER_XYZ"

_FAILING_FIXTURE = f"""\
#!/usr/bin/env bats

@test "deliberately fails and emits a distinctive diagnostic" {{
  run bash -c 'echo {MARKER}; exit 1'
  [ "$status" -eq 0 ]
}}
"""


def _require_bats() -> str:
    bats = shutil.which("bats")
    assert bats is not None, (
        "bats is required to exercise --print-output-on-failure; "
        "CI installs it via bats-core/bats-action, so a missing binary here "
        "is an environment defect, not a skip."
    )
    return bats


def _write_failing_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "deliberate_failure.bats"
    fixture.write_text(_FAILING_FIXTURE, encoding="utf-8")
    return fixture


def _run_bats(bats: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [bats, *args],
        capture_output=True,
        text=True,
    )


def test_print_output_on_failure_preserves_run_block_diagnostic(
    tmp_path: Path,
) -> None:
    """Positive control: the CI flag keeps $output visible on a failed case."""
    bats = _require_bats()
    fixture = _write_failing_fixture(tmp_path)

    result = _run_bats(bats, "--print-output-on-failure", str(fixture))
    combined = result.stdout + result.stderr

    assert result.returncode != 0, (
        "fixture must fail so we are asserting failure-path capture, "
        f"not a green run; got exit 0 with output:\n{combined}"
    )
    assert MARKER in combined, (
        "with --print-output-on-failure the captured run-block output must "
        f"reach the log; marker {MARKER!r} missing from:\n{combined}"
    )


def test_without_print_output_on_failure_discards_run_block_diagnostic(
    tmp_path: Path,
) -> None:
    """Negative control: without the flag the same failure hides $output.

    This is the pre-#153 behaviour. If it starts passing, either bats changed
    defaults or the fixture no longer exercises a captured run block — either
    way the positive test above would stop being load-bearing.
    """
    bats = _require_bats()
    fixture = _write_failing_fixture(tmp_path)

    result = _run_bats(bats, str(fixture))
    combined = result.stdout + result.stderr

    assert result.returncode != 0, (
        "fixture must still fail without the flag; "
        f"got exit 0 with output:\n{combined}"
    )
    assert "not ok" in combined, (
        "expected a bats failure summary even without the flag; got:\n"
        f"{combined}"
    )
    assert MARKER not in combined, (
        "without --print-output-on-failure the run-block diagnostic must not "
        f"appear; finding {MARKER!r} means the negative control is dead:\n"
        f"{combined}"
    )
