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
import sys
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

# The SELF source lives inside this checkout, so it resolves on every host --
# including CI. Everything else is a sibling repo, legitimately absent on a
# runner. Keeping these separate matters, and the reason is instructive: the
# original guard was `any(source exists)`. On CI that was False, so these tests
# skipped. Once the path fix made the self source resolve, `any(...)` became
# True, the guard stopped firing, and a test asserting that SIX sibling repos
# exist began running on a runner that will never have them. A skip condition
# that depends on the thing being fixed is not a skip condition.
SELF_SLUG = "homelab-canon"
EXTERNAL_SOURCES_PRESENT = all(
    f.exists()
    for slug, (files, _) in reconcile_l1.ENUMERABLE.items()
    if slug != SELF_SLUG
    for f in files
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


def build_partial_corpus(tmp_path: Path, monkeypatch) -> None:
    """Build one covered source and one source that is not on disk."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {
            "real": (("OPS-1",), ("OPS-1",)),
            "ghost": (("CI-1",), None),
        },
    )
    (tmp_path / "src" / "ghost.md").unlink()


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
    assert verdict == [
        "SHORT: 1 enumerable entries unaccounted for; "
        "0 canonical row(s) text-divergent (2/2 sources resolved)"
    ]
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


def test_self_ground_truth_source_always_resolves() -> None:
    """The self source must resolve on EVERY host, CI included.

    This is the host-independent half of the old all-sources test, and it is the
    half that actually gates: if this repo cannot find its own catalog, the
    reconcile step compares nothing no matter where it runs.
    """
    ids = reconcile_l1.ground_truth(SELF_SLUG)
    assert ids, "this repo's own catalog resolved to zero entries"
    assert len(ids) >= GROUND_TRUTH_FLOORS[SELF_SLUG], f"{len(ids)} ids"


@pytest.mark.skipif(not EXTERNAL_SOURCES_PRESENT, reason="sibling source repos are not checked out here")
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


@pytest.mark.skipif(not EXTERNAL_SOURCES_PRESENT, reason="sibling source repos are not checked out here")
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


def test_self_source_path_follows_the_module_not_a_hardcoded_home(tmp_path) -> None:
    """The decisive test: LOAD A COPY of the module from another path.

    Asserting paths on THIS host proves nothing -- here the hardcoded
    /home/psimmons/projects IS the checkout, so any equality check passes while
    the bug is fully present. Even running a copy as a subprocess proves nothing,
    because the copy still reads the hardcoded absolute path and that path still
    exists here. Only importing the copy and inspecting where IT thinks its own
    catalog lives discriminates.

    This is FM-158 -- a mechanism verified only in the developer's environment is
    unverified in the environment that gates -- and it is the test that would
    have caught this before the push instead of after CI went red.
    """
    import importlib.util
    import shutil

    dest = tmp_path / "checkout"
    src = Path(reconcile_l1.__file__).resolve().parents[1]
    shutil.copytree(src / "pipeline", dest / "pipeline")
    shutil.copytree(src / "catalog", dest / "catalog")

    spec = importlib.util.spec_from_file_location(
        "reconcile_copy", dest / "pipeline" / "reconcile_l1.py"
    )
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)

    self_files, _rx = copy.ENUMERABLE["homelab-canon"]
    for f in self_files:
        assert f.is_relative_to(dest), (
            f"the relocated module still points its OWN catalog at {f}; "
            f"it must resolve inside its own checkout at {dest}"
        )
    assert copy.L1.is_relative_to(dest), f"L1 resolved outside the checkout: {copy.L1}"


def test_self_source_is_configured_inside_the_checkout(tmp_path) -> None:
    """This repo's own catalog must resolve wherever the repo is checked out.

    `P` was hardcoded to /home/psimmons/projects, so on a CI runner the tool
    could not find its OWN catalog. Combined with the `else 100.0` fail-open
    that produced a COMPLETE verdict over five unresolved sources -- the gate
    passed for a year of runs having compared nothing. Deriving the self path
    from __file__ is what makes the gate mean anything off the workstation.
    """
    files, _rx = reconcile_l1.ENUMERABLE["homelab-canon"]
    repo_root = Path(reconcile_l1.__file__).resolve().parents[1]
    assert files, "homelab-canon must configure at least one source file"
    for f in files:
        assert f.is_relative_to(repo_root), (
            f"self source {f} is not inside the checkout at {repo_root}; "
            "it will not resolve on any other host"
        )
        assert f.exists(), f"self source {f} does not exist"


def test_l1_dir_resolves_from_the_checkout() -> None:
    repo_root = Path(reconcile_l1.__file__).resolve().parents[1]
    assert reconcile_l1.L1.is_relative_to(repo_root)
    assert reconcile_l1.L1.exists()


def test_some_sources_unresolved_is_PARTIAL_not_COMPLETE(tmp_path, monkeypatch, capsys) -> None:
    """The PARTIAL branch is the LIVE CI configuration and had zero coverage.

    Found by an independent re-sweep with fresh mutants. `elif n_unresolved:` ->
    `elif False:` passed the entire suite while turning "1 of 5 sources
    resolved" back into COMPLETE, exit 0 -- the exact fail-open the previous two
    commits were written to close, one degree softer. Not "nothing resolved",
    which was tested, but "most things did not resolve", which was not.

    The lesson generalises past this file: a new verdict added to a gate needs
    its own test at the moment it is added. I introduced PARTIAL and asserted
    only the endpoints either side of it.
    """
    build_partial_corpus(tmp_path, monkeypatch)
    status = run_main(monkeypatch)
    out = capsys.readouterr().out
    verdict = [ln for ln in out.splitlines() if "unaccounted for" in ln]
    assert len(verdict) == 1, verdict
    assert verdict[0].startswith("PARTIAL"), verdict[0]
    assert "(1/2 sources resolved)" in verdict[0], verdict[0]
    assert "were NOT checked" in out
    assert status == 1, "PARTIAL must fail unless explicitly waived"


def test_allow_partial_waives_partial_and_names_unchecked_count(tmp_path, monkeypatch, capsys) -> None:
    """The opt-out applies to PARTIAL only and must declare what it waived."""
    build_partial_corpus(tmp_path, monkeypatch)

    status = run_main(monkeypatch, "--allow-partial")
    out = capsys.readouterr().out

    assert status == 0
    assert (
        "PARTIAL: 0 enumerable entries unaccounted for; "
        "0 canonical row(s) text-divergent (1/2 sources resolved)"
    ) in out
    assert (
        "WAIVER: --allow-partial accepts this PARTIAL result; "
        "1 unresolved source(s) were NOT checked."
    ) in out


def test_allow_partial_does_not_waive_short(tmp_path, monkeypatch, capsys) -> None:
    """A real shortfall remains fatal when the PARTIAL opt-out is present."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {"real": (("OPS-1", "OPS-2"), ("OPS-1",))},
    )

    status = run_main(monkeypatch, "--allow-partial")
    out = capsys.readouterr().out

    assert status == 1
    assert "SHORT: 1 enumerable entries unaccounted for" in out
    assert "WAIVER:" not in out


def test_allow_partial_does_not_waive_unverified(tmp_path, monkeypatch, capsys) -> None:
    """A zero-source run remains fatal when the PARTIAL opt-out is present."""
    l1 = tmp_path / "L1"
    l1.mkdir()
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(
        reconcile_l1,
        "ENUMERABLE",
        {"ghost": ([tmp_path / "does-not-exist.md"], HEADING_RX)},
    )

    status = run_main(monkeypatch, "--allow-partial")
    out = capsys.readouterr().out

    assert status == 1
    assert "UNVERIFIED: 0 enumerable entries unaccounted for" in out
    assert "WAIVER:" not in out


def test_allow_partial_is_a_noop_for_complete(tmp_path, monkeypatch, capsys) -> None:
    """COMPLETE succeeds on its own and must not claim to need a waiver."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {"real": (("OPS-1",), ("OPS-1",))},
    )

    status = run_main(monkeypatch, "--allow-partial")
    out = capsys.readouterr().out

    assert status == 0
    assert "COMPLETE: 0 enumerable entries unaccounted for" in out
    assert "WAIVER:" not in out


def test_shortfall_outranks_partial_when_another_source_is_unresolved(tmp_path, monkeypatch, capsys) -> None:
    """A missing resolved entry is SHORT, even when a different source is absent."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {
            "real": (("OPS-1", "OPS-2"), ("OPS-1",)),
            "ghost": (("CI-1",), None),
        },
    )
    (tmp_path / "src" / "ghost.md").unlink()

    status = run_main(monkeypatch)
    out = capsys.readouterr().out
    verdict = [ln for ln in out.splitlines() if "unaccounted for" in ln]

    assert status == 1
    assert verdict == [
        "SHORT: 1 enumerable entries unaccounted for; "
        "0 canonical row(s) text-divergent (1/2 sources resolved)"
    ]


def test_unresolved_source_has_no_coverage_measurement(tmp_path, monkeypatch, capsys) -> None:
    """An absent ground-truth file is n/a, never measured as zero percent."""
    l1 = tmp_path / "L1"
    l1.mkdir()
    (l1 / "ghost.jsonl").write_text('{"id": "OPS-1"}\n', encoding="utf-8")
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(
        reconcile_l1,
        "ENUMERABLE",
        {"ghost": ([tmp_path / "does-not-exist.md"], HEADING_RX)},
    )

    run_main(monkeypatch)
    out = capsys.readouterr().out
    run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert report[0]["coverage_pct"] is None
    assert report[0]["resolved"] is False
    assert "   n/a%" in out


def test_covered_never_exceeds_ground_truth_when_extraction_has_extra_ids(tmp_path, monkeypatch, capsys) -> None:
    """Extraneous extracted IDs cannot inflate coverage beyond the source truth."""
    build_corpus(
        tmp_path,
        monkeypatch,
        {"alpha": (("OPS-1",), ("OPS-1", "OPS-2", "OPS-3"))},
    )

    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert status == 0
    assert report[0]["covered"] == 1
    assert 0 <= report[0]["covered"] <= report[0]["ground_truth"]


def test_extraction_searches_all_evidence_fields(tmp_path, monkeypatch, capsys) -> None:
    """An ID cited outside `id` still reconciles the record to ground truth."""
    l1 = tmp_path / "L1"
    l1.mkdir()
    md = tmp_path / "real.md"
    md.write_text("## OPS-1\n## CI-2\n## FM-3\n", encoding="utf-8")
    (l1 / "real.jsonl").write_text(
        '\n'.join(
            json.dumps(record)
            for record in (
                {"id": "row-1", "source_anchor": "OPS-1"},
                {"id": "row-2", "instance": "CI-2 happened"},
                {"id": "row-3", "check": "FM-3 is enforced"},
            )
        ) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(reconcile_l1, "ENUMERABLE", {"real": ([md], HEADING_RX)})

    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert status == 0
    assert report[0]["covered"] == report[0]["ground_truth"] == 3
    assert report[0]["missing"] == []


def test_suffixed_id_does_not_cover_its_unsuffixed_sibling(tmp_path, monkeypatch, capsys) -> None:
    """FM-12a and FM-12 are distinct catalog entries, not prefix matches."""
    build_corpus(tmp_path, monkeypatch, {"alpha": (("FM-12",), ("FM-12a",))})

    found, _ = reconcile_l1.extracted("alpha")
    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert "FM-12a" in found
    assert "FM-12" not in found
    assert status == 1
    assert report[0]["missing"] == ["FM-12"]


def test_hyphen_compound_suffix_does_not_cover_its_collided_prefix(tmp_path, monkeypatch, capsys) -> None:
    """hindsight#179 negative control.

    fleet-orch's real corpus disambiguates two source headings that both
    literally read "CI-1" (one in FAILURE-MODES.md, one in
    CODING-INVARIANTS.md) by appending the old FM number, giving records
    "CI-1-FM5" and "CI-1-FM7". Neither record's id, nor its source_anchor
    ("CI-1 (old: FM-7)"), is the standalone entry "CI-1" -- but a raw
    substring search finds "CI-1" inside both, so a genuinely-missing
    standalone "CI-1" would be reported as covered. That is a false
    negative on the shortfall, exactly backwards from what a coverage
    gate is for.
    """
    build_corpus(tmp_path, monkeypatch, {"alpha": (("CI-1",), ("CI-1-FM7",))})

    found, _ = reconcile_l1.extracted("alpha")
    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    # "CI-1-FM7" is a disambiguating id, not itself a recognized FM-style
    # token (no hyphen precedes the digit run in "FM7"), so it contributes
    # nothing to `found` either way -- the fix's job is only to stop it from
    # satisfying "CI-1".
    assert "CI-1" not in found
    assert status == 1
    assert report[0]["missing"] == ["CI-1"]


def test_hyphen_compound_suffix_in_id_field_alone_does_not_cover_prefix(tmp_path, monkeypatch, capsys) -> None:
    """Same collision, reproduced with the exact real-world `id` shape.

    fleet-orch's actual JSONL prefixes the slug: "fleet-orch-CI-1-FM7". This
    checks the fix holds with that literal prefix present too, and with no
    `source_anchor` field to independently supply a clean match -- isolating
    the bug to the `id`-field substring alone.
    """
    l1 = tmp_path / "L1"
    l1.mkdir()
    md = tmp_path / "real.md"
    md.write_text("## CI-1\n", encoding="utf-8")
    (l1 / "real.jsonl").write_text(
        json.dumps({"id": "real-CI-1-FM7"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(reconcile_l1, "ENUMERABLE", {"real": ([md], HEADING_RX)})

    found, _ = reconcile_l1.extracted("real")
    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert "CI-1" not in found
    assert status == 1
    assert report[0]["missing"] == ["CI-1"]


def test_plain_id_without_compound_suffix_still_covers(tmp_path, monkeypatch, capsys) -> None:
    """Positive control: an exact, non-collided ID still reports covered.

    Guards against an overcorrection that would make every ID report
    missing regardless of a real, exact match.
    """
    build_corpus(tmp_path, monkeypatch, {"alpha": (("CI-11",), ("CI-11",))})

    found, _ = reconcile_l1.extracted("alpha")
    status = run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert "CI-11" in found
    assert status == 0
    assert report[0]["missing"] == []
    assert report[0]["covered"] == report[0]["ground_truth"] == 1


def test_unresolved_flag_follows_ground_truth_not_nonempty_extraction(tmp_path, monkeypatch, capsys) -> None:
    """A present JSONL cannot make a missing source look machine-resolved."""
    l1 = tmp_path / "L1"
    l1.mkdir()
    (l1 / "ghost.jsonl").write_text('{"id": "OPS-1"}\n', encoding="utf-8")
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(
        reconcile_l1,
        "ENUMERABLE",
        {"ghost": ([tmp_path / "does-not-exist.md"], HEADING_RX)},
    )

    run_main(monkeypatch, "--json")
    report = json.loads(capsys.readouterr().out)

    assert report[0]["jsonl_lines"] == 1
    assert report[0]["resolved"] is False


def test_all_resolved_and_complete_says_COMPLETE(tmp_path, monkeypatch, capsys) -> None:
    """The other direction, so PARTIAL cannot simply replace COMPLETE."""
    l1 = tmp_path / "L1"
    l1.mkdir()
    (l1 / "real.jsonl").write_text('{"id": "OPS-1"}\n', encoding="utf-8")
    md = tmp_path / "real.md"
    md.write_text("## OPS-1\n", encoding="utf-8")
    monkeypatch.setattr(reconcile_l1, "L1", l1)
    monkeypatch.setattr(reconcile_l1, "ENUMERABLE", {"real": ([md], HEADING_RX)})
    status = run_main(monkeypatch)
    out = capsys.readouterr().out
    verdict = [ln for ln in out.splitlines() if "unaccounted for" in ln][0]
    assert verdict.startswith("COMPLETE"), verdict
    assert "(1/1 sources resolved)" in verdict
    assert status == 0
