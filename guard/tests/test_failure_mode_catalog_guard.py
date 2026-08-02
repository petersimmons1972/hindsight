"""Guard contract tests.

The contract changed deliberately on 2026-08-01 when the catalog moved to
hindsight. Two rules were altered, and both directions of each are asserted here
so a future regression cannot silently invert them:

* Ordering is ADVISORY (warning), not fatal. The catalog is a multi-section
  curated document; fatally enforcing global ID order would force a destructive
  re-sort or block every legitimate append.
* The historical-alias rule fires only when a legacy scheme is used as a ROW ID.
  The same strings appear legitimately as provenance annotations in the
  bug-class column (e.g. "Container Runtime - Design (FM-RC-01)"). The old rule
  matched anywhere in the file and flagged 50 legitimate annotations.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "guard" / "failure_mode_catalog_guard.py"
SPEC = importlib.util.spec_from_file_location("failure_mode_catalog_guard", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_rows_reads_canonical_ids() -> None:
    rows = MODULE.parse_rows("| FM-07 | a | b | c | d |\n| FM-42 | a | b | c | d |")
    assert [r.fm_id for r in rows] == ["FM-07", "FM-42"]


def test_duplicate_ids_are_fatal() -> None:
    """Uniqueness is the load-bearing invariant -- it must stay an ERROR."""
    text = "\n".join(
        [
            "| FM-01 | one | two | three | four |",
            "| FM-02 | again | two | three | four |",
            "| FM-02 | third | two | three | four |",
        ]
    )
    errors, _warnings = MODULE.validate_catalog(text, MODULE.parse_rows(text))
    assert any("duplicate canonical ID FM-02" in e for e in errors)


def test_ordering_rule_is_gone_entirely() -> None:
    """G3, 2026-08-02: the ordering rule is REMOVED, not demoted a second time.

    This test previously asserted ordering was reported as a warning. That
    contract was deliberately retired, so the test asserts the new contract
    rather than being deleted -- per CLAUDE.md, a changed rule gets its test
    updated in both directions, never relaxed to let a change pass.

    Measured justification: on 150 rows the catalog had zero gaps and zero
    duplicates but five out-of-order transitions, so this rule emitted five
    warnings per run and never once indicated a defect. Noise on a gate trains
    people to ignore the gate.

    It was replaced, not merely dropped: guard/tests/test_append_only.py pins
    the append-only ID-set invariant that took its place, which enforces the
    property that actually matters (a row may never disappear).
    """
    text = "\n".join(
        [
            "| FM-09 | one | two | three | four |",
            "| FM-02 | two | two | three | four |",
        ]
    )
    errors, warnings = MODULE.validate_catalog(text, MODULE.parse_rows(text))
    assert not any("out of order" in w for w in warnings)
    assert not any("out of order" in e for e in errors)


def test_legacy_scheme_as_row_id_is_rejected() -> None:
    """The rule must still catch the real defect it was written for."""
    text = "\n".join(
        [
            "| FM-01 | one | two | three | four |",
            "| FM-RC-01 | legacy | row | id | Judgment |",
        ]
    )
    errors, _warnings = MODULE.validate_catalog(text, MODULE.parse_rows(text))
    assert any("historical alias scheme" in e for e in errors)


def test_legacy_scheme_as_provenance_annotation_is_allowed() -> None:
    """The inversion guard: narrowing the rule must not create a false negative,
    and must not resume flagging legitimate provenance breadcrumbs."""
    text = "\n".join(
        [
            "| FM-37 | Container Runtime - Design (FM-RC-01) | x | y | Judgment |",
            "Prose mentioning FM-REC-04 as historical context is fine.",
        ]
    )
    errors, _warnings = MODULE.validate_catalog(text, MODULE.parse_rows(text))
    assert not any("historical alias scheme" in e for e in errors)


def test_repo_catalog_is_valid_and_next_id_is_stable() -> None:
    text = (ROOT / "catalog" / "failure-modes.md").read_text(encoding="utf-8")
    rows = MODULE.parse_rows(text)
    errors, _warnings = MODULE.validate_catalog(text, rows)
    assert errors == []
    assert MODULE.next_id(rows) == f"FM-{max(r.number for r in rows) + 1:02d}"


def test_promoted_rec_rows_are_present_and_keep_provenance() -> None:
    """The 11 FM-REC rows were nearly lost in the migration -- pin them down."""
    text = (ROOT / "catalog" / "failure-modes.md").read_text(encoding="utf-8")
    ids = {r.fm_id for r in MODULE.parse_rows(text)}
    assert {f"FM-{n}" for n in range(135, 146)} <= ids, "promoted FM-REC rows missing"
    for old in range(1, 12):
        assert f"(FM-REC-{old:02d})" in text, f"lost provenance for FM-REC-{old:02d}"
