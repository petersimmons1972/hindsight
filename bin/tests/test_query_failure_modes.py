"""query-failure-modes.sh must state the scope it actually searched (hindsight#184).

The script greps a curated CRITICAL+HIGH subset of catalog/criticality.jsonl. Without a
denominator on every result, a miss reads as "the catalog holds no such failure mode" --
the false NONE that gets used to demote a standing rule. Both directions are asserted:
the scope line on a hit, and the explicit non-clearance wording on a miss.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "bin" / "query-failure-modes.sh"


def _fixture(tmp_path: Path) -> dict[str, str]:
    pointer = tmp_path / "POINTER.md"
    high = tmp_path / "HIGH.md"
    criticality = tmp_path / "criticality.jsonl"
    pointer.write_text("# pointer\n\n- **FM-01** [BROAD] never truncate a shared table\n")
    high.write_text(
        "# high\n\n"
        "- **FM-02** [BROAD] propagate the child exit code\n"
        "- **FM-03** [NARROW] pin every image to a digest\n"
    )
    # Five distinct ids, one of them repeated (a re-triage of the same FM, not a
    # fourth population member) -- so the denominator is 5, not 6.
    criticality.write_text(
        "\n".join(
            f'{{"fm_id": "FM-0{n}", "tier": "HIGH"}}' for n in (1, 2, 3, 4, 5)
        )
        + '\n{"fm_id": "FM-05", "tier": "CRITICAL"}\n'
    )
    return {
        "POINTER": str(pointer),
        "HIGH": str(high),
        "CRITICALITY": str(criticality),
    }


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={"PATH": "/usr/bin:/bin", **_fixture(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_hit_reports_the_searched_subset_and_the_population(tmp_path: Path) -> None:
    result = _run(tmp_path, "truncate")
    assert "FM-01" in result.stdout
    assert "searched 3 of 5 canonical failure modes" in result.stderr


def test_unreadable_population_claims_no_fraction_rather_than_a_false_one(
    tmp_path: Path,
) -> None:
    """A subset larger than its own population is an impossible sentence.

    An empty (or stale) criticality.jsonl beside populated pointer files used to
    print "searched 258 of 0". Printing a scope line is the whole point of this
    script; printing a false one is worse than printing none.
    """
    env = _fixture(tmp_path)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    for criticality, expected in (
        (str(empty), "reports only 0 canonical failure modes"),
        (str(tmp_path / "absent.jsonl"), "could not be read"),
    ):
        result = subprocess.run(
            ["bash", str(SCRIPT), "truncate"],
            env={"PATH": "/usr/bin:/bin", **env, "CRITICALITY": criticality},
            capture_output=True,
            text=True,
            check=False,
        )
        assert "of 0 canonical failure modes" not in result.stderr
        assert expected in result.stderr
        assert "UNKNOWN" in result.stderr


def test_miss_is_labelled_not_in_subset_and_denies_all_clear(tmp_path: Path) -> None:
    result = _run(tmp_path, "nosuchkeywordanywhere")
    assert "not-in-subset" in result.stderr
    assert "searched 3 of 5 canonical failure modes" in result.stderr
    assert "NOT an all-clear" in result.stderr
