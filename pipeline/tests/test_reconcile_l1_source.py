"""Unit coverage for `reconcile_l1.py --source`, the scoping flag issue #73 added.

Until now the flag was exercised only from bats, which reaches it through the
add loop and the pre-commit hook. Those prove the loop is unblocked; they do not
pin the flag's own contract, and the contract is where the danger is: a scoping
flag that silently accepts an unrecognised value would certify an empty scope
and exit 0 -- "nothing was compared" reported as "nothing is missing", which is
the exact fail-open this repo exists to catalogue.

Three exit codes carry meaning and are asserted, never inferred:
  0  COMPLETE for the selected scope
  1  the scope was checked and something is missing / unverifiable
  2  the invocation itself is wrong (unknown, empty, or malformed slug)

Ground truth is built hermetically in a temp tree rather than read from whatever
sibling repos happen to exist on the host, so a missing checkout changes a
verdict here instead of quietly changing the meaning of a passing test.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
RECONCILE = REPO / "pipeline" / "reconcile_l1.py"
CATALOG = REPO / "catalog" / "failure-modes.md"
CANON_L1 = REPO / "pipeline" / "L1" / "homelab-canon.jsonl"

ALL_SLUGS = [
    "fleet-main",
    "fleet-orch",
    "homelab-canon",
    "claude-codex-integration",
    "fleet-dispatch-schema",
]
# The one source deliberately made SHORT in the hermetic fixture.
FIXTURE_MISSING_ID = "OPS-99"
SCOPE_MARKER = "SCOPE: --source restricted this run to"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, cwd=str(script.resolve().parents[1]),
    )


def _record(local_id: str) -> str:
    return json.dumps({"id": local_id, "instance": "fixture entry",
                       "source_path": "fixture"}) + "\n"


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    """A self-contained corpus: four sources complete, `fleet-orch` short by one.

    Mirrors the real layout -- the reconciler derives its repo root from its own
    file and its sibling roots from that root's parent -- so the copied script is
    the shipped script, unmodified.
    """
    projects = tmp_path / "projects"
    repo = projects / "hindsight"
    (repo / "pipeline" / "L1").mkdir(parents=True)
    (repo / "catalog").mkdir(parents=True)
    (repo / "pipeline" / "reconcile_l1.py").write_bytes(RECONCILE.read_bytes())

    (repo / "catalog" / "failure-modes.md").write_text(
        "| ID | Class | Instance | Lesson | Enforcement |\n"
        "| FM-001 | A | one | one | Judgment |\n"
        "| FM-002 | A | two | two | Judgment |\n"
        "| FM-003 | A | three | three | Judgment |\n",
        encoding="utf-8",
    )
    (repo / "pipeline" / "L1" / "homelab-canon.jsonl").write_text(
        "".join(_record(i) for i in ("FM-001", "FM-002", "FM-003")), encoding="utf-8")

    (projects / "fleet" / "orchestration").mkdir(parents=True)
    (projects / "fleet" / "FAILURE-MODES.md").write_text("## OPS-1\n", encoding="utf-8")
    (projects / "fleet" / "orchestration" / "FAILURE-MODES.md").write_text(
        f"## OPS-2\n## {FIXTURE_MISSING_ID}\n", encoding="utf-8")
    (projects / "fleet" / "CODING-INVARIANTS.md").write_text("## CI-1\n", encoding="utf-8")
    (projects / "fleet" / "CODING-FAILURE-MODES.md").write_text("## FM-1\n", encoding="utf-8")
    (repo / "pipeline" / "L1" / "fleet-main.jsonl").write_text(
        _record("OPS-1"), encoding="utf-8")
    # OPS-99 is deliberately absent: fleet-orch is the short source.
    (repo / "pipeline" / "L1" / "fleet-orch.jsonl").write_text(
        "".join(_record(i) for i in ("OPS-2", "CI-1", "FM-1")), encoding="utf-8")

    (projects / "claude-codex" / "docs").mkdir(parents=True)
    (projects / "claude-codex" / "docs" / "integration-failure-modes.md").write_text(
        "## FM-001\n", encoding="utf-8")
    (repo / "pipeline" / "L1" / "claude-codex-integration.jsonl").write_text(
        _record("FM-001"), encoding="utf-8")

    (projects / "fleet-dispatch" / "migrations").mkdir(parents=True)
    (projects / "fleet-dispatch" / "migrations" / "0017_failure_class.sql").write_text(
        "CHECK (failure_class IN ('fixture_failure'))\n", encoding="utf-8")
    (repo / "pipeline" / "L1" / "fleet-dispatch-schema.jsonl").write_text(
        json.dumps({"id": "fixture_failure", "instance": "schema class",
                    "source_path": "migration"}) + "\n", encoding="utf-8")

    return repo


# ── the invocation contract: a bad slug is an error, never an empty scope ─────

@pytest.mark.parametrize("args", [
    pytest.param(["--source"], id="flag-with-no-value"),
    pytest.param(["--source", ""], id="empty-string"),
    pytest.param(["--source", "fleet"], id="prefix-of-a-real-slug"),
    pytest.param(["--source", "homelab-canon;id"], id="shell-metacharacter-payload"),
    pytest.param(["--source", "no-such"], id="unknown-slug"),
    pytest.param(["--source", "homelab-canon", "--source", "no-such"],
                 id="one-valid-one-unknown"),
    pytest.param(["--source", "Homelab-Canon"], id="wrong-case"),
])
def test_a_slug_the_reconciler_does_not_know_exits_2(fixture_repo: Path, args) -> None:
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py", *args)
    assert result.returncode == 2, (
        f"{args} exited {result.returncode}; a scope that names nothing real must "
        "be a hard error, not a run that certifies an empty selection."
    )
    # And it must not have printed a verdict that a caller could read as a pass.
    assert "COMPLETE" not in result.stdout
    assert result.returncode != 0


def test_an_unknown_slug_names_itself_and_the_known_slugs(fixture_repo: Path) -> None:
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py", "--source", "no-such")
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "no-such" in combined, "the rejection must name the slug it rejected"
    for slug in ALL_SLUGS:
        assert slug in combined, f"the rejection must list {slug} as a known source"


# ── the verdict contract ─────────────────────────────────────────────────────

def test_unscoped_run_checks_every_source_and_fails_on_the_short_one(
    fixture_repo: Path,
) -> None:
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py")
    assert result.returncode == 1
    assert "SHORT" in result.stdout
    assert FIXTURE_MISSING_ID in result.stdout
    assert f"({len(ALL_SLUGS)}/{len(ALL_SLUGS)} sources resolved)" in result.stdout
    assert SCOPE_MARKER not in result.stdout, (
        "an unscoped run skipped nothing and must not print a narrowing notice"
    )


def test_gate_keeps_the_full_report_but_only_blocks_its_named_source(
    fixture_repo: Path,
) -> None:
    """A write gate may narrow exit status without hiding sibling drift (#101)."""
    result = _run(
        fixture_repo / "pipeline" / "reconcile_l1.py",
        "--gate",
        "homelab-canon",
    )

    assert result.returncode == 0
    assert "SHORT" in result.stdout
    assert FIXTURE_MISSING_ID in result.stdout
    assert "GATE: COMPLETE across homelab-canon; exit 0" in result.stdout
    assert SCOPE_MARKER not in result.stdout, (
        "--gate changes blocking semantics only; it must not omit source reports"
    )


def test_gate_rejects_unknown_or_empty_source_names(fixture_repo: Path) -> None:
    for value in ("", "no-such", "homelab-canon,no-such"):
        result = _run(
            fixture_repo / "pipeline" / "reconcile_l1.py", "--gate", value
        )
        assert result.returncode == 2, value
        assert "GATE:" not in result.stdout


def test_naming_every_source_is_equivalent_to_the_unscoped_run(fixture_repo: Path) -> None:
    args: list[str] = []
    for slug in ALL_SLUGS:
        args += ["--source", slug]
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py", *args)
    assert result.returncode == 1
    assert "SHORT" in result.stdout
    assert FIXTURE_MISSING_ID in result.stdout
    assert SCOPE_MARKER not in result.stdout, (
        "naming all five sources narrows nothing; a SCOPE notice here would be "
        "a false warning"
    )


def test_scoping_to_a_clean_source_passes_and_states_what_it_skipped(
    fixture_repo: Path,
) -> None:
    # Repeated deliberately: a repeated slug is a scope of one, not of two.
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py",
                  "--source", "homelab-canon", "--source", "homelab-canon")
    assert result.returncode == 0
    assert "COMPLETE" in result.stdout
    assert "(1/1 sources resolved)" in result.stdout
    assert SCOPE_MARKER in result.stdout, "a narrowed run must never be silent"
    for slug in ALL_SLUGS:
        if slug == "homelab-canon":
            continue
        assert slug in result.stdout, (
            f"a scoped run must name {slug} among the sources it did not check"
        )
    assert FIXTURE_MISSING_ID not in result.stdout, (
        "scoping to homelab-canon must not report another source's shortfall"
    )


def test_scoping_to_the_short_source_still_fails(fixture_repo: Path) -> None:
    """Scoping narrows what is checked; it must not soften what is found."""
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py",
                  "--source", "fleet-orch")
    assert result.returncode == 1
    assert "SHORT" in result.stdout
    assert FIXTURE_MISSING_ID in result.stdout


def test_json_mode_reports_the_narrowing_on_stderr(fixture_repo: Path) -> None:
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py",
                  "--json", "--source", "homelab-canon")
    assert result.returncode == 0
    assert SCOPE_MARKER in result.stderr, (
        "a JSON consumer must not receive a COMPLETE that silently covered a "
        "subset; the narrowing has to reach it on some stream"
    )
    payload = json.loads(result.stdout)
    assert [entry["slug"] for entry in payload] == ["homelab-canon"]
    assert payload[0]["missing"] == []


def test_a_scoped_run_that_cannot_read_its_ground_truth_refuses(
    fixture_repo: Path,
) -> None:
    """The checker's own evidence source is gone: that must fail, not pass."""
    (fixture_repo / "catalog" / "failure-modes.md").unlink()
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py",
                  "--source", "homelab-canon")
    assert result.returncode != 0, (
        "with no ground-truth file there is nothing to compare against; exiting "
        "0 would turn 'nothing was checked' into 'nothing is missing'"
    )
    assert "COMPLETE" not in result.stdout.split("SCOPE LIMIT")[0]
    assert "UNVERIFIED" in result.stdout


def test_scoping_to_a_source_whose_l1_extract_is_missing_fails(
    fixture_repo: Path,
) -> None:
    """Ground truth present, extract absent -- every entry is unaccounted for."""
    (fixture_repo / "pipeline" / "L1" / "homelab-canon.jsonl").unlink()
    result = _run(fixture_repo / "pipeline" / "reconcile_l1.py",
                  "--source", "homelab-canon")
    assert result.returncode == 1
    assert "SHORT" in result.stdout
    assert "FM-001" in result.stdout


# ── the positive control CI depends on ───────────────────────────────────────

def test_dropping_a_real_catalog_row_from_l1_fails_the_scoped_ci_gate(
    tmp_path: Path,
) -> None:
    """The check CI actually runs must bite on real drift, not just fixture drift.

    Uses the shipped catalog and the shipped homelab-canon extract, with the
    newest row removed from the extract only. That is exactly the drift the
    scoped CI step exists to catch, and it is how issue #73's own entry
    (FM-172) would present if the extractor lost it.
    """
    assert CATALOG.is_file(), f"evidence source missing: {CATALOG}"
    assert CANON_L1.is_file(), f"evidence source missing: {CANON_L1}"
    catalog_text = CATALOG.read_text(encoding="utf-8")
    ids = re.findall(r"^\| (FM-\d{2,3}) \|", catalog_text, re.M)
    assert ids, "no enumerable rows found in the canonical catalog"
    dropped = ids[-1]

    projects = tmp_path / "projects"
    repo = projects / "hindsight"
    (repo / "pipeline" / "L1").mkdir(parents=True)
    (repo / "catalog").mkdir(parents=True)
    (repo / "pipeline" / "reconcile_l1.py").write_bytes(RECONCILE.read_bytes())
    (repo / "catalog" / "failure-modes.md").write_text(catalog_text, encoding="utf-8")

    kept = [line for line in CANON_L1.read_text(encoding="utf-8").splitlines()
            if dropped not in line]
    removed = len(CANON_L1.read_text(encoding="utf-8").splitlines()) - len(kept)
    assert removed == 1, (
        f"expected exactly one {dropped} record in the shipped extract, removed "
        f"{removed}"
    )
    (repo / "pipeline" / "L1" / "homelab-canon.jsonl").write_text(
        "\n".join(kept) + "\n", encoding="utf-8")

    result = _run(repo / "pipeline" / "reconcile_l1.py", "--source", "homelab-canon")
    assert result.returncode == 1, (
        "the scoped gate CI runs failed to notice a canonical row missing from "
        "the extract it is supposed to reconcile"
    )
    assert "SHORT" in result.stdout
    assert dropped in result.stdout, "the failure must name the row it lost"


def test_the_shipped_scoped_ci_gate_is_green_on_the_committed_tree() -> None:
    """The negative control for the test above: no drift today, so exit 0."""
    result = _run(RECONCILE, "--source", "homelab-canon")
    assert result.returncode == 0, (
        "catalog/failure-modes.md and pipeline/L1/homelab-canon.jsonl have "
        "drifted; the scoped CI step is red on the committed tree."
    )
    assert "COMPLETE" in result.stdout
