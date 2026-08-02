"""Contract tests for the mechanical L1 reconciler.

Two layers are covered, because the reconciler's whole value is that a shortfall
is loud:

* the reporting/exit layer (`main`), driven against a synthetic corpus so a known
  gap must produce the word SHORT *and* exit 1 -- the pair CI actually reads;
* the ground-truth layer, which must fail loudly rather than resolve to an empty
  set. An empty ground truth scores 100% by construction
  (`cov = ... if truth else 100.0`), so a renamed or unreadable source file is
  otherwise indistinguishable from a fully covered one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import reconcile_l1


# The production heading pattern, reused rather than re-typed: a test that
# restates the regex proves only that the test agrees with itself.
HEADING_RX = reconcile_l1.ENUMERABLE["fleet-main"][1]

# Floors measured on the current sources. Ground truth only ever grows -- a
# count below these means a source stopped resolving, not that entries were
# legitimately removed.
GROUND_TRUTH_FLOORS = {
    "fleet-main": 102,
    "fleet-orch": 30,
    "homelab-canon": 162,
    "claude-codex-integration": 23,
    "fleet-dispatch-schema": 10,
}

# Skipped only where no source repo is checked out at all (a bare CI runner).
# Where any source is present, the whole configuration is held to account.
SOURCES_PRESENT = any(
    f.exists() for files, _ in reconcile_l1.ENUMERABLE.values() for f in files
)


def build_corpus(tmp_path: Path, monkeypatch, sources: dict[str, tuple[tuple[str, ...], tuple[str, ...] | None]]) -> None:
    """Point the reconciler at a synthetic corpus.

    ``sources`` maps slug -> (ground-truth ids, extracted ids). An extracted
    value of ``None`` means the L1 file does not exist at all.
    """
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    l1 = tmp_path / "L1"
    l1.mkdir(exist_ok=True)

    enumerable = {}
    for slug, (truth_ids, found_ids) in sources.items():
        md = src / f"{slug}.md"
        md.write_text("".join(f"## {i}\n" for i in truth_ids), encoding="utf-8")
        enumerable[slug] = ([md], HEADING_RX)
        if found_ids is not None:
            (l1 / f"{slug}.jsonl").write_text(
                "".join(json.dumps({"id": i}) + "\n" for i in found_ids),
                encoding="utf-8",
            )

    monkeypatch.setattr(reconcile_l1, "ENUMERABLE", enumerable)
    monkeypatch.setattr(reconcile_l1, "L1", l1)


def run_main(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["reconcile_l1.py", *argv])
    return reconcile_l1.main()


def test_shortfall_prints_short_and_exits_1(tmp_path: Path, monkeypatch, capsys) -> None:
    """A missing entry must be both named SHORT and exit 1 -- not one or the other."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {
            "alpha": (("OPS-1", "OPS-2"), ("OPS-1", "OPS-2")),
            "beta": (("CI-5", "CI-6"), ("CI-5",)),
        },
    )

    status = run_main(monkeypatch)
    out = capsys.readouterr().out

    verdict = [line for line in out.splitlines() if "unaccounted for" in line]

    assert status == 1
    # Contract extended deliberately: the verdict line now also states how many
    # sources RESOLVED, because "SHORT: 0 unaccounted for" and "nothing was on
    # disk to compare against" used to render identically. Asserted exactly, so
    # the count cannot silently drift.
    assert verdict == ["SHORT: 1 enumerable entries unaccounted for (2/2 sources resolved)"]
    assert "CI-6" in out


def test_fully_covered_corpus_prints_complete_and_exits_0(tmp_path: Path, monkeypatch, capsys) -> None:
    build_corpus(
        tmp_path,
        monkeypatch,
        {"alpha": (("OPS-1",), ("OPS-1",)), "beta": (("CI-5",), ("CI-5",))},
    )

    status = run_main(monkeypatch)
    out = capsys.readouterr().out

    assert status == 0
    assert "COMPLETE: 0 enumerable entries unaccounted for" in out


def test_json_report_covers_every_configured_source(tmp_path: Path, monkeypatch, capsys) -> None:
    """Every configured source must be reconciled, not just the first one."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {
            "alpha": (("OPS-1",), ("OPS-1",)),
            "beta": (("CI-5",), ("CI-5",)),
            "gamma": (("FM-9",), ("FM-9",)),
        },
    )

    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert status == 0
    assert [row["slug"] for row in report] == ["alpha", "beta", "gamma"]
    assert len(report) == len(reconcile_l1.ENUMERABLE)


def test_missing_l1_file_is_a_shortfall_not_full_coverage(tmp_path: Path, monkeypatch, capsys) -> None:
    """An absent extraction file must read as 0 covered, never as covered-by-default."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {"alpha": (("OPS-1", "OPS-2"), None)},
    )

    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert status == 1
    assert report[0]["jsonl_lines"] == 0
    assert report[0]["covered"] == 0
    assert report[0]["missing"] == ["OPS-1", "OPS-2"]


def test_ground_truth_reads_remaining_files_when_one_is_missing(tmp_path: Path, monkeypatch) -> None:
    """One unreadable source file must not silently zero out its siblings."""
    present = tmp_path / "present.md"
    present.write_text("## OPS-9\n", encoding="utf-8")
    monkeypatch.setattr(
        reconcile_l1,
        "ENUMERABLE",
        {"alpha": ([tmp_path / "absent.md", present], HEADING_RX)},
    )

    assert reconcile_l1.ground_truth("alpha") == {"OPS-9"}


def test_ground_truth_matches_heading_levels_two_through_four(tmp_path: Path, monkeypatch) -> None:
    """The accepted heading depth is a contract: narrowing it silently drops entries."""
    md = tmp_path / "source.md"
    md.write_text(
        "# OPS-0\n## OPS-2\n### OPS-3\n#### OPS-4\n##### OPS-5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reconcile_l1, "ENUMERABLE", {"alpha": ([md], HEADING_RX)})

    assert reconcile_l1.ground_truth("alpha") == {"OPS-2", "OPS-3", "OPS-4"}


@pytest.mark.skipif(not SOURCES_PRESENT, reason="ground-truth source repos are not checked out here")
def test_every_configured_ground_truth_source_resolves() -> None:
    """A source that resolves to nothing scores 100%: pin existence and a floor."""
    missing_files = [
        str(f)
        for files, _ in reconcile_l1.ENUMERABLE.values()
        for f in files
        if not f.exists()
    ]
    assert missing_files == []

    for slug in reconcile_l1.ENUMERABLE:
        ids = reconcile_l1.ground_truth(slug)
        assert ids, f"{slug}: ground truth resolved to zero entries"
        assert len(ids) >= GROUND_TRUTH_FLOORS[slug], f"{slug}: {len(ids)} ids"


@pytest.mark.skipif(not SOURCES_PRESENT, reason="ground-truth source repos are not checked out here")
def test_every_configured_source_has_a_non_empty_extraction() -> None:
    """Coverage of 100% is meaningless if the extraction file was never read."""
    for slug in reconcile_l1.ENUMERABLE:
        _, n_lines = reconcile_l1.extracted(slug)
        assert n_lines > 0, f"{slug}: extraction file absent or empty"


# ---------------------------------------------------------------------------
# The vacuous-pass fix. Reported by the mutation sweep as a LIVE production
# defect, not a mutant: on a bare CI runner none of the ground-truth source
# repos exist, so every `truth` set is empty, `cov` falls to the `else 100.0`
# branch, and the gate prints COMPLETE and exits 0 having verified NOTHING.
# "I could not check" rendering as "it is fine" is this repository's defining
# failure, and the gate that measures corpus coverage was committing it.
# ---------------------------------------------------------------------------


def test_all_sources_unresolved_is_fatal_not_complete(tmp_path, monkeypatch, capsys) -> None:
    """Zero resolvable sources must fail loud, never report COMPLETE."""
    l1 = tmp_path / "L1"
    l1.mkdir()
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(
        reconcile_l1,
        "ENUMERABLE",
        {"ghost": ([tmp_path / "does-not-exist.md"], HEADING_RX)},
    )
    status = run_main(monkeypatch)
    out = capsys.readouterr().out
    assert status != 0, "a run that resolved no sources must not exit 0"
    # Assert on the VERDICT line only. The trailing SCOPE LIMIT prose legitimately
    # contains the word COMPLETE ("COMPLETE means 'no enumerable entry is
    # missing'"), so a naive substring check over the whole output would fail for
    # the wrong reason and would pass again if the verdict silently changed.
    verdict = [ln for ln in out.splitlines() if "unaccounted for" in ln]
    assert len(verdict) == 1, verdict
    assert verdict[0].startswith("UNVERIFIED"), verdict[0]
    assert "NOTHING WAS CHECKED" in out


def test_unresolved_source_is_not_reported_as_100_percent(tmp_path, monkeypatch, capsys) -> None:
    """An absent source must not score 100% coverage.

    This is the exact expression that produced the defect:
        cov = (...) / len(truth) * 100 if truth else 100.0
    An empty ground truth means "nothing to compare against", which is the
    absence of a measurement, not a perfect one.
    """
    l1 = tmp_path / "L1"
    l1.mkdir()
    (l1 / "ghost.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(
        reconcile_l1,
        "ENUMERABLE",
        {"ghost": ([tmp_path / "does-not-exist.md"], HEADING_RX)},
    )
    run_main(monkeypatch, "--json")
    out = capsys.readouterr().out
    row = next(r for r in json.loads(out) if r["slug"] == "ghost")
    assert row.get("coverage_pct") != 100.0, f"absent source scored 100%: {row}"
    assert row.get("resolved") is False, f"absent source must be marked unresolved: {row}"
