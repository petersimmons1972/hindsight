"""Exit-code and parsing-rule contract for the guard CLI.

Mutation sweep finding: most of this file's behaviour was correct but
unasserted. Nothing pinned what ``main()`` RETURNS, so a mutant that turned
every "I could not find the thing I gate on" branch into ``return 0`` passed
the whole suite -- the canonical fail-open shape. These tests drive the script
as a subprocess and assert the exit code, because the exit code is the only
thing ``.githooks/pre-commit`` and ``bin/add-failure-mode.sh`` actually read.

Each test below is paired with the surviving mutant it kills (S-id from the
sweep report); do not weaken an assertion without re-running that mutant.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "guard" / "failure_mode_catalog_guard.py"
SPEC = importlib.util.spec_from_file_location("failure_mode_catalog_guard", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def rows_text(ids: list[str]) -> str:
    return "\n".join(f"| {i} | bug | class | evidence | Machine |" for i in ids)


def _run_guard(*argv: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *argv],
        capture_output=True,
        text=True,
    )


# --- CLI exit codes: the fail-open shapes -----------------------------------


def test_cli_malformed_id_ledger_exits_nonzero(tmp_path: Path) -> None:
    """S4 (M16). A corrupt baseline must refuse, not certify the catalog.

    load_known_ids raising was already unit-tested; nothing asserted that the
    CLI turns that raise into a failing exit code.
    """
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(rows_text(["FM-01", "FM-02"]) + "\n")
    (tmp_path / "id-ledger.txt").write_text("FM-01\nnot-an-id\n")

    result = _run_guard(str(catalog))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "malformed ledger entry" in result.stderr, result.stderr


def test_cli_missing_catalog_exits_nonzero(tmp_path: Path) -> None:
    """S5 (M14). "The file I gate on is absent" must never render as success."""
    result = _run_guard(str(tmp_path / "does-not-exist.md"))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "catalog not found" in result.stderr, result.stderr


def test_cli_next_id_validates_before_minting(tmp_path: Path) -> None:
    """S6 (M18). --next-id is the ONLY automated ID-assignment path.

    bin/add-failure-mode.sh sources the next ID from it, so minting an ID from
    a catalog that failed validation hands out an ID derived from corrupt data
    and then blames the author for the duplicate.
    """
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(rows_text(["FM-01", "FM-03"]) + "\n")
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02\nFM-03\n")

    result = _run_guard(str(catalog), "--next-id")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FM-02" in result.stderr, result.stderr
    assert "FM-04" not in result.stdout, result.stdout


def test_cli_next_id_prints_the_id_on_a_sound_catalog(tmp_path: Path) -> None:
    """Both directions of the test above: validation must not block the happy path."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(rows_text(["FM-01", "FM-02"]) + "\n")
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02\n")

    result = _run_guard(str(catalog), "--next-id")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "FM-03", result.stdout


# --- empty-catalog diagnostics ----------------------------------------------


def test_empty_catalog_is_an_error_on_the_no_ledger_path() -> None:
    """S7 (M12). A zero-row catalog returning errors == [] is "nothing is wrong"
    reported from a file with no data in it."""
    errors, _warnings = MODULE.validate_catalog("", [])
    assert errors, errors
    assert any("no canonical FM rows found" in e for e in errors), errors


def test_empty_catalog_keeps_its_own_diagnostic_alongside_the_ledger_error() -> None:
    """S19 (M13). Diagnostic-only: the exit code is already fatal via the
    append-only arm, but losing this line means an operator reading stderr is
    told only "IDs were removed" and never "the file has no rows at all"."""
    errors, _warnings = MODULE.validate_catalog("", [], known_ids={"FM-01"})
    assert any("canonical IDs removed" in e for e in errors), errors
    assert any("no canonical FM rows found" in e for e in errors), errors


# --- historical-alias rule: both directions ---------------------------------


def _alias_errors(extra_line: str) -> list[str]:
    text = "\n".join(["| FM-01 | bug | class | evidence | Machine |", extra_line])
    errors, _warnings = MODULE.validate_catalog(text, MODULE.parse_rows(text))
    return errors


def test_rec_scheme_as_row_id_is_rejected() -> None:
    """S10 (M06). FM-REC-01..11 are the eleven rows CLAUDE.md says were nearly
    lost; the REC arm of the rule had no test at all (only FM-RC-*)."""
    errors = _alias_errors("| FM-REC-04 | legacy | row | id | Judgment |")
    assert any("historical alias scheme" in e for e in errors), errors


def test_single_digit_legacy_row_id_is_rejected() -> None:
    """S15 (M08). \\d+ not \\d{2,}: | FM-RC-1 | is still a legacy row ID."""
    errors = _alias_errors("| FM-RC-1 | legacy | row | id | Judgment |")
    assert any("historical alias scheme" in e for e in errors), errors


def test_bare_cell_provenance_annotation_is_not_flagged() -> None:
    """S16 (M07), the FALSE-POSITIVE direction.

    The rule is anchored to the START of the line on purpose: the old unanchored
    version flagged 50 legitimate provenance annotations in the bug-class
    column. The existing inversion test only covers the parenthesised form
    ("... (FM-RC-01)"); a breadcrumb occupying a whole cell is the form that an
    unanchored rule silently starts rejecting.
    """
    errors = _alias_errors("| FM-37 | container drift | FM-REC-04 | tests/x.py | Judgment |")
    assert errors == [], errors


# --- next_id and parse line numbers -----------------------------------------


def test_next_id_is_derived_from_the_max_id_not_the_row_count() -> None:
    """S14 (M10). Survives on the live catalog only because it is contiguous.
    The first gap makes add-failure-mode.sh hand out an ID that already exists."""
    text = rows_text(["FM-01", "FM-42"])
    assert MODULE.next_id(MODULE.parse_rows(text)) == "FM-43"


def test_next_id_keeps_two_digit_zero_padding() -> None:
    """S17 (M11). Invisible at 162 rows; FM-9 is not a canonical ID shape."""
    text = rows_text(["FM-08"])
    assert MODULE.next_id(MODULE.parse_rows(text)) == "FM-09"


def test_parse_rows_line_numbers_are_one_based() -> None:
    """S18 (M02). Off-by-one here makes every duplicate report point at the
    wrong row, which sends the reader to a line that looks innocent."""
    text = "# heading\n\n| FM-01 | bug | class | evidence | Machine |"
    rows = MODULE.parse_rows(text)
    assert [r.line for r in rows] == [3]


def test_duplicate_report_names_the_real_line_numbers() -> None:
    """S18 (M02) through the error message operators actually read."""
    text = rows_text(["FM-02", "FM-02"])
    errors, _warnings = MODULE.validate_catalog(text, MODULE.parse_rows(text))
    assert any("duplicate canonical ID FM-02 on lines 1, 2" in e for e in errors), errors


def test_padded_canonical_id_joins_the_duplicate_census(tmp_path: Path) -> None:
    """Whitespace inside the ID cell cannot hide a second canonical row."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(
        "\n".join(
            [
                "| FM-403 | original | class | evidence | Machine |",
                "|  FM-403 | padded duplicate | class | evidence | Machine |",
            ]
        )
        + "\n"
    )
    (tmp_path / "id-ledger.txt").write_text("FM-403\n")

    result = _run_guard(str(catalog))
    assert result.returncode != 0, result.stdout + result.stderr
    assert "duplicate canonical ID FM-403" in result.stderr, result.stderr


def test_padded_singleton_is_counted_as_a_canonical_row(tmp_path: Path) -> None:
    """Normalization must preserve the existing padded-singleton path."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text("|  FM-403  | bug | class | evidence | Machine |\n")
    (tmp_path / "id-ledger.txt").write_text("FM-403\n")

    result = _run_guard(str(catalog))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK (1 canonical IDs, next FM-404)" in result.stderr, result.stderr


def test_supersedes_claim_requires_matching_tombstone(tmp_path: Path) -> None:
    """A correction claim cannot land while its target remains live."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(
        "\n".join(
            [
                "| FM-01 | class | original claim | check | Judgment |",
                "| FM-02 | class | correction. Supersedes FM-01. | check | Judgment |",
            ]
        )
        + "\n"
    )
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02\n")

    result = _run_guard(str(catalog))
    assert result.returncode != 0, result.stdout + result.stderr
    assert "FM-02 claims Supersedes FM-01" in result.stderr, result.stderr
    assert "FM-01 is not tombstoned as SUPERSEDED by FM-02" in result.stderr, result.stderr


def test_tombstone_requires_matching_supersedes_claim(tmp_path: Path) -> None:
    """A tombstone cannot land without the replacement row naming its target."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(
        "\n".join(
            [
                "| FM-01 | class | SUPERSEDED by FM-02 — original claim | check | Judgment |",
                "| FM-02 | class | unrelated replacement | check | Judgment |",
            ]
        )
        + "\n"
    )
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02\n")

    result = _run_guard(str(catalog))
    assert result.returncode != 0, result.stdout + result.stderr
    assert "FM-01 is tombstoned as SUPERSEDED by FM-02" in result.stderr, result.stderr
    assert "FM-02 does not claim Supersedes FM-01" in result.stderr, result.stderr


def test_matching_supersession_pair_is_valid(tmp_path: Path) -> None:
    """The guard accepts the bidirectional form written by the correction tool."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(
        "\n".join(
            [
                "| FM-01 | class | SUPERSEDED by FM-02 — original claim | check | Judgment |",
                "| FM-02 | class | correction. Supersedes FM-01. | check | Judgment |",
            ]
        )
        + "\n"
    )
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02\n")

    result = _run_guard(str(catalog))
    assert result.returncode == 0, result.stdout + result.stderr


# --- Round-2 survivors: padding, grammar bounds, ledger end-anchor ----------


def test_M16_legacy_row_id_is_rejected_whatever_the_cell_padding() -> None:
    """S8/M16: HISTORICAL_SCHEME_RE must accept zero- and multi-space padding.

    Hand-edited and tool-generated markdown routinely produce unpadded pipes.
    A regex that only matches single-space cells reintroduces the legacy scheme
    whose enforcement nearly lost FM-REC-01..11.
    """
    cases = [
        "|FM-RC-01| legacy | row | id | Judgment |",
        "|  FM-REC-07  | legacy | row | id | Judgment |",
    ]
    for extra_line in cases:
        errors = _alias_errors(extra_line)
        assert any("historical alias scheme" in e for e in errors), (
            f"padding form not rejected: {extra_line!r} -> {errors}"
        )


def test_M15_single_digit_row_id_is_not_a_canonical_row() -> None:
    """S11/M15: the normalized ID-cell parser requires at least two digits.

    Widening to {1,3} silently changes which rows count as canonical, which
    shifts next_id, duplicate detection, and the append-only present-set.
    Single-digit pseudo-rows must not parse as canonical — empty present set
    against a ledger is fatal with the no-rows diagnostic.
    """
    catalog_body = "\n".join(
        [
            "| FM-1 | bug | class | evidence | Machine |",
            "| FM-2 | bug | class | evidence | Machine |",
        ]
    )
    # Unit path: parse_rows must see zero canonical rows.
    assert MODULE.parse_rows(catalog_body) == []
    errors, _ = MODULE.validate_catalog(catalog_body, MODULE.parse_rows(catalog_body))
    assert any("no canonical FM rows found" in e for e in errors), errors


def test_M14_trailing_garbage_on_a_ledger_line_is_rejected_cleanly(tmp_path: Path) -> None:
    """S12/M14: ID_LEDGER_RE end-anchor rejects trailing junk.

    Without `$`, `FM-02 retired-2026-08-01` is accepted and the sort key
    `int(i.split("-")[1])` later raises an uncaught ValueError instead of the
    intended `malformed ledger entry` diagnostic.
    """
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(rows_text(["FM-01", "FM-02"]) + "\n")
    (tmp_path / "id-ledger.txt").write_text("FM-01\nFM-02 retired-2026-08-01\n")

    result = _run_guard(str(catalog))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "malformed ledger entry" in result.stderr, result.stderr
