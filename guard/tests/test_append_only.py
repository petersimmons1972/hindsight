"""G3 — the ordering rule is replaced by an append-only ID-set invariant.

Measured before the change (150 rows): zero gaps, zero duplicates, five
out-of-order transitions. So the ordering warning fired five times a run and
never once indicated a defect -- it was pure noise, and noise on a gate trains
people to ignore the gate. Ordering was never the property anyone cared about.

The property people actually care about is stated in CLAUDE.md as a
non-negotiable: "Never delete a catalog row to satisfy a validator. That is
precisely how 11 real failure modes (FM-REC-01..11) were nearly lost." Until now
that was a sentence in a document -- nothing enforced it. This suite pins the
mechanism that does (Law 1: a rule becomes a mechanism or a principle, never a
third thing).

The ledger is the record of every ID that has ever been canonical. The catalog
may grow freely; it may never shed an ID that the ledger has seen.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "guard" / "failure_mode_catalog_guard.py"
SPEC = importlib.util.spec_from_file_location("failure_mode_catalog_guard_ao", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def rows_text(ids: list[str]) -> str:
    return "\n".join(f"| {i} | class | instance | check | 🤖 |" for i in ids)


# --- the invariant itself ---------------------------------------------------


def test_removing_a_known_id_is_FATAL() -> None:
    """The whole point. A row that once existed may not vanish."""
    text = rows_text(["FM-01", "FM-03"])
    errors, _ = MODULE.validate_catalog(
        text, MODULE.parse_rows(text), known_ids={"FM-01", "FM-02", "FM-03"}
    )
    assert any("FM-02" in e for e in errors), "removal of FM-02 must be reported"
    assert any("removed" in e.lower() or "missing" in e.lower() for e in errors)


def test_adding_new_ids_is_allowed() -> None:
    """Growth is the normal case and must not be obstructed."""
    text = rows_text(["FM-01", "FM-02", "FM-03"])
    errors, _ = MODULE.validate_catalog(
        text, MODULE.parse_rows(text), known_ids={"FM-01", "FM-02"}
    )
    assert not errors, f"appending FM-03 must be clean, got {errors}"


def test_count_preserving_deletion_is_still_caught() -> None:
    """The sneaky case: delete one row and renumber another so the COUNT matches.

    A guard that compares lengths passes this. Comparing SETS is what makes it a
    real invariant rather than a tally.
    """
    text = rows_text(["FM-01", "FM-02", "FM-99"])
    errors, _ = MODULE.validate_catalog(
        text, MODULE.parse_rows(text), known_ids={"FM-01", "FM-02", "FM-03"}
    )
    assert any("FM-03" in e for e in errors), "count matched, but FM-03 is gone"


# --- fail-loud, not fail-open ----------------------------------------------


def test_absent_ledger_is_an_ERROR_not_a_silent_skip() -> None:
    """A gate that cannot find its baseline must refuse, never wave things through.

    'I could not check' rendered as 'it is fine' is this repository's defining
    failure. known_ids=None means the ledger could not be read.
    """
    text = rows_text(["FM-01"])
    errors, _ = MODULE.validate_catalog(text, MODULE.parse_rows(text), known_ids=None)
    assert errors, "an unreadable ledger must be fatal, not ignored"
    # Assert the SPECIFIC diagnostic, not merely that some error mentioning
    # "ledger" appeared. Mutation testing caught this: deleting the absent-ledger
    # branch let None fall through to the empty-ledger branch, which still errors
    # and still says "ledger" -- so a weaker assertion passed while the guard had
    # lost its ability to tell "baseline missing" from "baseline says nothing".
    # Those are different defects with different fixes (restore the file vs.
    # investigate an emptied one), and a diagnostic that conflates them sends the
    # operator down the wrong path.
    assert any("could not be read" in e.lower() for e in errors), errors
    assert not any("is empty" in e.lower() for e in errors), errors


def test_empty_ledger_is_an_ERROR_not_a_vacuous_pass() -> None:
    """An empty baseline trivially satisfies 'nothing was removed'.

    That is a vacuous pass -- exactly the fail-open shape catalogued as FM-155
    (a floor satisfied by an element that verifies nothing).
    """
    text = rows_text(["FM-01", "FM-02"])
    errors, _ = MODULE.validate_catalog(text, MODULE.parse_rows(text), known_ids=set())
    assert errors, "an empty ledger must be fatal, not a free pass"
    # The other half of the pair above: an EMPTY ledger must not be reported as
    # an UNREADABLE one either. Both directions, so neither branch can absorb
    # the other's case unnoticed.
    assert any("is empty" in e.lower() for e in errors), errors
    assert not any("could not be read" in e.lower() for e in errors), errors


def test_empty_catalog_against_a_populated_ledger_is_fatal() -> None:
    """The catastrophic case, stated explicitly rather than left to arithmetic."""
    errors, _ = MODULE.validate_catalog("", [], known_ids={"FM-01", "FM-02"})
    assert errors


# --- the rule this replaces -------------------------------------------------


def test_ordering_no_longer_warns() -> None:
    """G3: the advisory ordering rule is REMOVED, not demoted again.

    Both directions matter. This asserts the noise is gone; the tests above
    assert the real invariant took its place. Removing a rule without replacing
    it would be a net loss of coverage, so these live in one file on purpose.
    """
    text = rows_text(["FM-42", "FM-07"])  # deliberately descending
    errors, warnings = MODULE.validate_catalog(
        text, MODULE.parse_rows(text), known_ids={"FM-07", "FM-42"}
    )
    assert not any("out of order" in w for w in warnings), "ordering rule must be gone"
    assert not any("out of order" in e for e in errors)


# --- the loader -------------------------------------------------------------


def test_loader_reads_ids_and_ignores_comments(tmp_path: Path) -> None:
    p = tmp_path / "id-ledger.txt"
    p.write_text("# a comment\n\nFM-01\nFM-02\n  FM-03  \n")
    assert MODULE.load_known_ids(p) == {"FM-01", "FM-02", "FM-03"}


def test_loader_returns_None_when_absent(tmp_path: Path) -> None:
    """Distinguish 'absent' from 'empty' -- they are different defects."""
    assert MODULE.load_known_ids(tmp_path / "nope.txt") is None


# --- the wiring, not just the function --------------------------------------


def _run_guard(catalog: Path) -> "subprocess.CompletedProcess[str]":
    import subprocess

    return subprocess.run(
        [sys.executable, str(MODULE_PATH), str(catalog)],
        capture_output=True,
        text=True,
    )


def test_cli_enforces_the_invariant(tmp_path: Path) -> None:
    """The gate that actually runs must evaluate this, not just the function.

    Mutation testing caught the gap: every unit test above still passed when
    main() stopped passing known_ids through, because they call validate_catalog
    directly. A correct function that nothing calls is the 'artifact is not the
    fix' family -- require-real-ci.sh sat in this repo for a day gating nothing
    for exactly that reason.
    """
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(rows_text(["FM-01", "FM-03"]) + "\n")
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02\nFM-03\n")

    result = _run_guard(catalog)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FM-02" in result.stderr, result.stderr


def test_cli_passes_when_nothing_was_removed(tmp_path: Path) -> None:
    """Both directions: the CLI must still accept a legitimately grown catalog."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(rows_text(["FM-01", "FM-02", "FM-03"]) + "\n")
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02\n")

    result = _run_guard(catalog)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_refuses_when_the_ledger_is_absent(tmp_path: Path) -> None:
    """No ledger beside the catalog means the gate cannot certify anything."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(rows_text(["FM-01"]) + "\n")

    result = _run_guard(catalog)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ledger" in result.stderr.lower()


def test_loader_rejects_a_malformed_line(tmp_path: Path) -> None:
    """Garbage in the baseline must not be silently dropped to 'no such ID'."""
    p = tmp_path / "id-ledger.txt"
    p.write_text("FM-01\nnot-an-id\n")
    with pytest.raises(ValueError):
        MODULE.load_known_ids(p)
