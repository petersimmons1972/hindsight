"""Contract tests for the ``first_seen`` date-repair tool (Issue #32, packet P0).

The contract, per the issue:

* A row's ``source_path`` / ``source_anchor`` are mapped, via the row's SOURCE
  NAME (the L1 file's own basename) resolved through a source-roots config,
  to a sibling repo. The commit that first introduced the anchor text into
  that file (``git log --reverse -S<anchor>``) supplies ``first_seen``,
  tagged ``first_seen_provenance: "git-anchor"``.
* When that lookup can't resolve (repo/root absent, path never existed, or
  the pickaxe returns nothing), fall back to the first commit -- in THIS
  checkout -- that introduced the row's own id into its
  ``pipeline/L1/<source>.jsonl``, tagged ``"l1-ingest-fallback"``.
* Rows that already carry ``first_seen`` are left completely alone: same
  value, no provenance key added.
* A row that resolves under neither path is left with no ``first_seen`` and
  no provenance key (STILL-UNDATED), not a fabricated guess.
* Empty/missing input is a named, non-zero-exit failure (R4) -- a zero count
  must never look the same as "wasn't measured".
* Every run reports the three counts (DATED-BY-ANCHOR / DATED-BY-FALLBACK /
  STILL-UNDATED) on stderr, prefixed ``date-repair:``.

Two DIFFERENT things get exercised in this file, deliberately kept apart:

1. ``repair_file`` / the CLI's REPAIR path -- takes an explicit target and
   is legitimately testable against disposable git fixtures (the ``Env``
   class below). ``--l1`` retargeting this is what makes repair testable at
   all.
2. The corpus STATISTICS (``_measure_corpus`` and everything it feeds) --
   these are UNPOINTABLE by construction: they read exactly the module
   constants ``CORPUS_L1`` / ``CORPUS_CLUSTERS`` (this real checkout's own
   ``pipeline/L1`` and ``pipeline/L2/clusters.jsonl``), never an argument.
   There is therefore no way to build a disposable fixture that looks like
   "the corpus" to these functions -- and no test here tries to. The maths
   (``_resolve_measurement``, ``_summarize_family``, ``_pct_pre_dated``,
   ``_fallback_share``) is tested with plain in-memory data; the read-only
   orchestration (``_measure_corpus``) is tested straight against the real,
   already-on-disk corpus (read-only -- these tests never call ``repair_file``
   or ``main`` against real project files, so nothing here can re-date a row
   or touch ``catalog/`` / ``conf/``); and the CLI is tested only for the
   ONE statistics behaviour it can actually still reach: NOT MEASURED when
   ``--l1`` isn't the corpus.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import repair_first_seen  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "repair_first_seen_sample.jsonl"


# --------------------------------------------------------------------------
# git fixture plumbing -- disposable repos built fresh per test, never the
# real ~/projects or this checkout's own history.
# --------------------------------------------------------------------------

def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        env=env,
    )


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "date-repair-test@example.com")
    _git(repo, "config", "user.name", "date-repair-test")
    return repo


def _commit(repo: Path, rel_path: str, content: str, author_date: str, message: str) -> None:
    """Write *content* to *rel_path* inside *repo* and commit it at *author_date*.

    *author_date* is a full ISO-8601 timestamp (e.g. "2026-01-08T09:00:00+00:00")
    so the seconds-level ordering between fixture commits is unambiguous; only
    the calendar-date portion is asserted on.
    """
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    env = {**os.environ, "GIT_AUTHOR_DATE": author_date, "GIT_COMMITTER_DATE": author_date}
    _git(repo, "commit", "-q", "-m", message, env=env)


def _remove_and_commit(repo: Path, rel_path: str, author_date: str, message: str) -> None:
    _git(repo, "rm", "-q", rel_path)
    env = {**os.environ, "GIT_AUTHOR_DATE": author_date, "GIT_COMMITTER_DATE": author_date}
    _git(repo, "commit", "-q", "-m", message, env=env)


class Env:
    """A disposable projects_dir + hindsight_repo pair, wired for --source-roots.

    Used ONLY to exercise repair_file / the CLI's repair path against
    fixture git history. This has no bearing on the corpus statistics at
    all -- there is no argument that routes a fake corpus location into
    _measure_corpus, so nothing built here can be mistaken for "the corpus".
    """

    def __init__(self, tmp_path: Path) -> None:
        self.projects_dir = tmp_path / "projects"
        self.sample_root = self.projects_dir / "sampleroot"
        self.hindsight_repo = tmp_path / "hindsight-checkout"
        self.conf_file = tmp_path / "source-roots.conf"
        self.l1_dir = tmp_path / "L1"
        self.l1_dir.mkdir(parents=True, exist_ok=True)

        _init_repo(self.sample_root)
        _init_repo(self.hindsight_repo)
        self.conf_file.write_text("sample:sampleroot\n", encoding="utf-8")

    def target(self, *rows: dict) -> Path:
        """Write *rows* to pipeline/L1/sample.jsonl under this env's L1 dir.

        Named "sample.jsonl" deliberately: the tool derives the SOURCE NAME
        (both the conf lookup key and the fallback L1 filename) from the
        target file's own basename.
        """
        path = self.l1_dir / "sample.jsonl"
        path.write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
        return path

    def main_args(self, *extra: str) -> list[str]:
        return [
            "--source-roots", str(self.conf_file),
            "--projects-dir", str(self.projects_dir),
            "--self-dir", str(self.hindsight_repo),
            "--hindsight-repo", str(self.hindsight_repo),
            *extra,
        ]


def _load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_fixture_row(row_id: str) -> dict:
    for row in _load_rows(FIXTURE):
        if row["id"] == row_id:
            return dict(row)
    raise AssertionError(f"fixture row {row_id!r} not found in {FIXTURE}")


# --------------------------------------------------------------------------
# (1) anchor whose introducing commit is known
# --------------------------------------------------------------------------

def test_dates_row_from_the_commit_that_introduced_the_anchor(tmp_path: Path) -> None:
    env = Env(tmp_path)

    # c1: file exists, anchor heading absent yet.
    _commit(env.sample_root, "docs/anchor.md", "# Doc\n\nplaceholder\n",
            "2026-01-05T09:00:00+00:00", "add doc")
    # c2: THIS is the introducing commit for the anchor heading.
    _commit(env.sample_root, "docs/anchor.md",
            "# Doc\n\n## Anchor Heading One\nOriginal text.\n",
            "2026-01-08T09:00:00+00:00", "add anchor heading")
    # c3: anchor text removed (occurrence count changes 1 -> 0) -- pickaxe
    # will also match this commit, proving the tool must take the FIRST match.
    _remove_and_commit(env.sample_root, "docs/anchor.md",
                        "2026-01-20T09:00:00+00:00", "drop anchor heading")
    # git rm pruned the now-empty docs/ dir along with the file -- recreate it
    # before writing, same as _commit() already does for every other write.
    restored = env.sample_root / "docs/anchor.md"
    restored.parent.mkdir(parents=True, exist_ok=True)
    restored.write_text("# Doc\n\n## Anchor Heading One\nRestored.\n", encoding="utf-8")
    # c4: anchor text re-added (0 -> 1) -- also a pickaxe match, also must be
    # ignored in favour of the earliest (c2).
    _commit(env.sample_root, "docs/anchor.md",
            "# Doc\n\n## Anchor Heading One\nRestored.\n",
            "2026-02-01T09:00:00+00:00", "restore anchor heading")

    row = {
        "id": "sample-anchor-1",
        "source_path": "sampleroot/docs/anchor.md",
        "source_anchor": "Anchor Heading One",
        "instance": "An anchor-dateable entry.",
        "check": "n/a",
        "enforcement": None,
        "auto": "machine",
    }
    target = env.target(row)

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf_file.read_text()),
        projects_dir=env.projects_dir,
        self_dir=env.hindsight_repo,
        hindsight_repo=env.hindsight_repo,
    )

    assert stats.dated_by_anchor == 1
    assert stats.dated_by_fallback == 0
    assert stats.still_undated == 0

    (result,) = _load_rows(target)
    assert result["first_seen"] == "2026-01-08"
    assert result["first_seen_provenance"] == "git-anchor"


# --------------------------------------------------------------------------
# (2) a row that must fall back
# --------------------------------------------------------------------------

def test_falls_back_to_l1_ingest_commit_when_anchor_lookup_fails(tmp_path: Path) -> None:
    env = Env(tmp_path)

    # The mapped repo exists, but this exact file was never committed to it --
    # the anchor lookup must come back empty and trigger the fallback.
    _commit(env.sample_root, "docs/unrelated.md", "# unrelated\n",
            "2026-01-01T09:00:00+00:00", "unrelated commit")

    # The fallback path: THIS checkout's own pipeline/L1/sample.jsonl history.
    _commit(env.hindsight_repo, "pipeline/L1/sample.jsonl",
            '{"id": "sample-fallback-1", "source_path": "sampleroot/docs/missing.md"}\n',
            "2026-03-03T12:00:00+00:00", "ingest sample-fallback-1")
    _commit(env.hindsight_repo, "pipeline/L1/sample.jsonl",
            '{"id": "sample-fallback-1", "source_path": "sampleroot/docs/missing.md"}\n'
            '{"id": "sample-other-1", "source_path": "sampleroot/docs/other.md"}\n',
            "2026-03-10T12:00:00+00:00", "ingest sample-other-1")

    row = {
        "id": "sample-fallback-1",
        "source_path": "sampleroot/docs/missing.md",
        "source_anchor": "Never Existed Heading",
        "instance": "A fallback-dateable entry.",
        "check": "n/a",
        "enforcement": None,
        "auto": "machine",
    }
    target = env.target(row)

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf_file.read_text()),
        projects_dir=env.projects_dir,
        self_dir=env.hindsight_repo,
        hindsight_repo=env.hindsight_repo,
    )

    assert stats.dated_by_anchor == 0
    assert stats.dated_by_fallback == 1
    assert stats.still_undated == 0

    (result,) = _load_rows(target)
    assert result["first_seen"] == "2026-03-03"
    assert result["first_seen_provenance"] == "l1-ingest-fallback"


# --------------------------------------------------------------------------
# (3) a row that already has first_seen is left untouched, no provenance added
# --------------------------------------------------------------------------

def test_leaves_already_dated_rows_completely_untouched(tmp_path: Path) -> None:
    env = Env(tmp_path)
    row = _load_fixture_row("fixture-existing-1")
    assert row["first_seen"] == "2020-01-01"
    assert "first_seen_provenance" not in row
    target = env.target(row)

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf_file.read_text()),
        projects_dir=env.projects_dir,
        self_dir=env.hindsight_repo,
        hindsight_repo=env.hindsight_repo,
    )

    # An already-dated row must not be counted in any of the three buckets --
    # it was never touched, not "dated by" anything this run.
    assert stats.dated_by_anchor == 0
    assert stats.dated_by_fallback == 0
    assert stats.still_undated == 0

    (result,) = _load_rows(target)
    assert result["first_seen"] == "2020-01-01"
    assert "first_seen_provenance" not in result


# --------------------------------------------------------------------------
# (4) empty input exits non-zero, naming the input
# --------------------------------------------------------------------------

def test_empty_input_exits_nonzero_and_names_the_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = Env(tmp_path)
    empty = env.l1_dir / "sample.jsonl"
    empty.write_text("", encoding="utf-8")

    exit_code = repair_first_seen.main(env.main_args("--l1", str(empty)))

    captured = capsys.readouterr()
    assert exit_code != 0
    assert str(empty) in captured.err


def test_missing_input_exits_nonzero_and_names_the_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = Env(tmp_path)
    missing = env.l1_dir / "does-not-exist.jsonl"

    exit_code = repair_first_seen.main(env.main_args("--l1", str(missing)))

    captured = capsys.readouterr()
    assert exit_code != 0
    assert str(missing) in captured.err


# --------------------------------------------------------------------------
# (5) the three counts are printed, on stderr, prefixed date-repair:
# --------------------------------------------------------------------------

def test_prints_the_three_counts_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = Env(tmp_path)

    _commit(env.sample_root, "docs/anchor.md",
            "# Doc\n\n## Anchor Heading One\nOriginal text.\n",
            "2026-01-08T09:00:00+00:00", "add anchor heading")

    _commit(env.hindsight_repo, "pipeline/L1/sample.jsonl",
            '{"id": "sample-fallback-1"}\n',
            "2026-03-03T12:00:00+00:00", "ingest sample-fallback-1")

    anchor_row = {
        "id": "sample-anchor-1",
        "source_path": "sampleroot/docs/anchor.md",
        "source_anchor": "Anchor Heading One",
        "instance": "An anchor-dateable entry.",
        "check": "n/a",
        "enforcement": None,
        "auto": "machine",
    }
    fallback_row = {
        "id": "sample-fallback-1",
        "source_path": "sampleroot/docs/missing.md",
        "source_anchor": "Never Existed Heading",
        "instance": "A fallback-dateable entry.",
        "check": "n/a",
        "enforcement": None,
        "auto": "machine",
    }
    existing_row = _load_fixture_row("fixture-existing-1")
    undatable_row = _load_fixture_row("fixture-undatable-1")

    target = env.target(anchor_row, fallback_row, existing_row, undatable_row)

    exit_code = repair_first_seen.main(env.main_args("--l1", str(target)))

    captured = capsys.readouterr()
    assert "date-repair: DATED-BY-ANCHOR: 1" in captured.err
    assert "date-repair: DATED-BY-FALLBACK: 1" in captured.err
    assert "DIFFERENTIAL" not in captured.err
    assert "WARNING" not in captured.err
    assert "date-repair: STILL-UNDATED: 1" in captured.err
    # A row already dated coming in must never inflate any of the three counts.
    assert exit_code == 0

    rows = {r["id"]: r for r in _load_rows(target)}
    assert rows["sample-anchor-1"]["first_seen_provenance"] == "git-anchor"
    assert rows["sample-fallback-1"]["first_seen_provenance"] == "l1-ingest-fallback"
    assert rows["fixture-existing-1"]["first_seen"] == "2020-01-01"
    assert "first_seen_provenance" not in rows["fixture-existing-1"]
    assert "first_seen" not in rows["fixture-undatable-1"]
    assert "first_seen_provenance" not in rows["fixture-undatable-1"]


# ==========================================================================
# UNPOINTABLE STATISTICS -- Issue #32 refactor.
#
# CORPUS_L1 / CORPUS_CLUSTERS are module constants derived from this file's
# own __file__ location. No CLI flag, no function argument, reaches them.
# Everything below tests either the PURE maths (in-memory data, no IO, no
# path) or the real, already-on-disk corpus READ-ONLY (no repair_file / main
# call touches it) or the one CLI behaviour that's still reachable: NOT
# MEASURED when --l1 isn't the corpus.
# ==========================================================================

# --------------------------------------------------------------------------
# constants: derived from module location, and the 134 equality is real
# --------------------------------------------------------------------------

def test_corpus_constants_are_derived_from_this_files_own_location() -> None:
    module_dir = Path(repair_first_seen.__file__).resolve().parent
    assert repair_first_seen.CORPUS_L1 == module_dir / "L1"
    assert repair_first_seen.CORPUS_CLUSTERS == module_dir / "L2" / "clusters.jsonl"


def test_expected_members_is_the_sum_of_the_two_arm_constants() -> None:
    assert repair_first_seen.EXPECTED_MEMBERS == (
        repair_first_seen.EXPECTED_ARM_B_MEMBERS + repair_first_seen.EXPECTED_COMPARATOR_MEMBERS
    )
    assert repair_first_seen.EXPECTED_MEMBERS == 134
    assert repair_first_seen.EXPECTED_ARM_B_MEMBERS == 32
    assert repair_first_seen.EXPECTED_COMPARATOR_MEMBERS == 102


def test_no_clusters_flag_exists_to_redirect_the_statistics() -> None:
    """The old --clusters flag is gone entirely -- argparse must reject it,
    not silently ignore it or accept it and do nothing."""
    with pytest.raises(SystemExit):
        repair_first_seen.main(["--clusters", "/tmp/anything"])


# --------------------------------------------------------------------------
# _resolve_measurement -- PURE. In-memory found_families / id_provenance
# dicts only; no path, no IO. This is what instance #8 (a clusters file
# quietly stripped of some of a family's members) and instance #6 (a
# clusters file missing whole families) attacked.
# --------------------------------------------------------------------------

def _synthetic_full_families(**overrides: dict[str, list[str]]) -> dict[str, set[str]]:
    """Every EXPECTED_FAMILIES key present (satisfies family-presence), all
    empty unless overridden -- lets a test target just the families/counts
    it cares about."""
    all_families = repair_first_seen.ARM_B_FAMILIES | repair_first_seen.COMPARATOR_FAMILIES
    return {cid: set(overrides.get(cid, [])) for cid in all_families}


def test_resolve_measurement_succeeds_on_exact_expected_membership() -> None:
    arm_b_ids = [f"ab-{i}" for i in range(repair_first_seen.EXPECTED_ARM_B_MEMBERS)]
    comparator_ids = [f"cp-{i}" for i in range(repair_first_seen.EXPECTED_COMPARATOR_MEMBERS)]
    families = _synthetic_full_families(
        **{next(iter(sorted(repair_first_seen.ARM_B_FAMILIES))): arm_b_ids,
           next(iter(sorted(repair_first_seen.COMPARATOR_FAMILIES))): comparator_ids}
    )
    id_provenance = {i: "git-anchor" for i in arm_b_ids} | {i: "l1-ingest-fallback" for i in comparator_ids}

    measurement = repair_first_seen._resolve_measurement(families, id_provenance)

    assert measurement.measured is True
    assert measurement.reason is None
    assert len(measurement.arm_b_ids) == 32
    assert len(measurement.comparator_ids) == 102


def test_resolve_measurement_not_measured_when_a_family_is_missing() -> None:
    families = _synthetic_full_families()
    del families[next(iter(repair_first_seen.ARM_B_FAMILIES))]

    measurement = repair_first_seen._resolve_measurement(families, {})

    assert measurement.measured is False
    assert "missing 1 of 21 expected families" in measurement.reason


def test_resolve_measurement_not_measured_when_arm_b_membership_shrinks() -> None:
    """Instance #8 regression: 2 of a family's declared members quietly
    stripped out of the clusters data -- the arm-b union comes up 30, not
    32. Must NOT MEASURED naming the actual count, never silently recompute
    the percentage over the 30 that survived."""
    arm_b_ids = [f"ab-{i}" for i in range(30)]  # 2 short of EXPECTED_ARM_B_MEMBERS
    comparator_ids = [f"cp-{i}" for i in range(repair_first_seen.EXPECTED_COMPARATOR_MEMBERS)]
    families = _synthetic_full_families(
        **{next(iter(sorted(repair_first_seen.ARM_B_FAMILIES))): arm_b_ids,
           next(iter(sorted(repair_first_seen.COMPARATOR_FAMILIES))): comparator_ids}
    )
    id_provenance = {i: "git-anchor" for i in arm_b_ids} | {i: "git-anchor" for i in comparator_ids}

    measurement = repair_first_seen._resolve_measurement(families, id_provenance)

    assert measurement.measured is False
    assert "30 arm-b members" in measurement.reason
    assert "expected 32" in measurement.reason


def test_resolve_measurement_not_measured_when_comparator_membership_grows() -> None:
    """The equality cuts both ways -- more resolved members than expected is
    just as much a fabrication risk (a family gained a member from somewhere
    it shouldn't have) as fewer."""
    arm_b_ids = [f"ab-{i}" for i in range(repair_first_seen.EXPECTED_ARM_B_MEMBERS)]
    comparator_ids = [f"cp-{i}" for i in range(103)]  # 1 too many
    families = _synthetic_full_families(
        **{next(iter(sorted(repair_first_seen.ARM_B_FAMILIES))): arm_b_ids,
           next(iter(sorted(repair_first_seen.COMPARATOR_FAMILIES))): comparator_ids}
    )
    id_provenance = {i: "git-anchor" for i in arm_b_ids} | {i: "git-anchor" for i in comparator_ids}

    measurement = repair_first_seen._resolve_measurement(families, id_provenance)

    assert measurement.measured is False
    assert "103 comparator members" in measurement.reason
    assert "expected 102" in measurement.reason


def test_resolve_measurement_not_measured_when_a_declared_member_never_loaded() -> None:
    arm_b_ids = [f"ab-{i}" for i in range(repair_first_seen.EXPECTED_ARM_B_MEMBERS)]
    comparator_ids = [f"cp-{i}" for i in range(repair_first_seen.EXPECTED_COMPARATOR_MEMBERS)]
    families = _synthetic_full_families(
        **{next(iter(sorted(repair_first_seen.ARM_B_FAMILIES))): arm_b_ids,
           next(iter(sorted(repair_first_seen.COMPARATOR_FAMILIES))): comparator_ids}
    )
    # ab-0 never appears in any loaded L1 row.
    id_provenance = {i: "git-anchor" for i in arm_b_ids[1:]} | {i: "git-anchor" for i in comparator_ids}

    measurement = repair_first_seen._resolve_measurement(families, id_provenance)

    assert measurement.measured is False
    assert measurement.reason == "1 of 134 cluster members did not resolve"


# --------------------------------------------------------------------------
# _summarize_family / _pct_pre_dated / _fallback_share -- PURE maths.
# --------------------------------------------------------------------------

def test_summarize_family_counts_each_provenance_bucket() -> None:
    ids = frozenset({"a", "b", "c", "d", "e"})
    id_provenance = {
        "a": "pre-existing", "b": "git-anchor", "c": "l1-ingest-fallback",
        "d": "l1-ingest-fallback", "e": "undated",
    }
    assert repair_first_seen._summarize_family(ids, id_provenance) == (1, 1, 2, 1)


def test_pct_pre_dated_computes_percentage_and_handles_zero_total() -> None:
    assert repair_first_seen._pct_pre_dated(1, 1, 2) == "25.0%"
    assert repair_first_seen._pct_pre_dated(0, 0, 0) == "n/a"


def test_fallback_share_counts_across_all_provenance_values() -> None:
    id_provenance = {
        "x1": "git-anchor", "x2": "l1-ingest-fallback",
        "x3": "l1-ingest-fallback", "x4": "l1-ingest-fallback",
        "x5": "pre-existing", "x6": "undated",
    }
    fallback, dated = repair_first_seen._fallback_share(id_provenance)
    assert (fallback, dated) == (3, 4)


# --------------------------------------------------------------------------
# _print_differential / _print_fallback_warning -- take a CorpusMeasurement
# object only, no path, no IO. Hand-built in-memory measurements.
# --------------------------------------------------------------------------

def test_print_differential_not_measured_names_the_reason(capsys: pytest.CaptureFixture[str]) -> None:
    measurement = repair_first_seen.CorpusMeasurement(False, "some reason")
    repair_first_seen._print_differential(measurement)
    assert capsys.readouterr().err.strip() == "date-repair: DIFFERENTIAL: NOT MEASURED (some reason)"


def test_print_differential_reports_provenance_split_not_just_dated_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Every id already carries first_seen -- the old "is not None" metric
    # would read 100.0%/100.0% and hide the provenance skew below.
    id_provenance = {
        "a1": "pre-existing", "a2": "git-anchor", "a3": "l1-ingest-fallback", "a4": "l1-ingest-fallback",
        "b1": "pre-existing", "b2": "l1-ingest-fallback",
    }
    measurement = repair_first_seen.CorpusMeasurement(
        True,
        id_provenance=id_provenance,
        arm_b_ids=frozenset({"a1", "a2", "a3", "a4"}),
        comparator_ids=frozenset({"b1", "b2"}),
    )
    repair_first_seen._print_differential(measurement)
    err = capsys.readouterr().err
    assert "100.0%" not in err
    assert (
        "date-repair: DIFFERENTIAL: intervention-family (n=4) "
        "pre-existing=1 git-anchor=1 l1-ingest-fallback=2 undated=0 -> 25.0% pre-dated"
    ) in err
    assert (
        "date-repair: DIFFERENTIAL: comparator-pool (n=2) "
        "pre-existing=1 git-anchor=0 l1-ingest-fallback=1 undated=0 -> 50.0% pre-dated"
    ) in err


def test_print_fallback_warning_not_measured_names_the_reason(capsys: pytest.CaptureFixture[str]) -> None:
    measurement = repair_first_seen.CorpusMeasurement(False, "some reason")
    repair_first_seen._print_fallback_warning(measurement)
    assert capsys.readouterr().err.strip() == "date-repair: WARNING: NOT MEASURED (some reason)"


def test_print_fallback_warning_fires_above_fifty_percent(capsys: pytest.CaptureFixture[str]) -> None:
    id_provenance = {
        "x1": "git-anchor", "x2": "l1-ingest-fallback",
        "x3": "l1-ingest-fallback", "x4": "l1-ingest-fallback",
    }
    measurement = repair_first_seen.CorpusMeasurement(True, id_provenance=id_provenance)
    repair_first_seen._print_fallback_warning(measurement)
    err = capsys.readouterr().err
    assert "date-repair: WARNING:" in err
    assert "75.0%" in err


def test_print_fallback_warning_silent_at_or_below_fifty_percent(capsys: pytest.CaptureFixture[str]) -> None:
    id_provenance = {"x1": "git-anchor", "x2": "l1-ingest-fallback"}
    measurement = repair_first_seen.CorpusMeasurement(True, id_provenance=id_provenance)
    repair_first_seen._print_fallback_warning(measurement)
    assert capsys.readouterr().err == ""


def test_print_fallback_warning_silent_when_nothing_dated(capsys: pytest.CaptureFixture[str]) -> None:
    measurement = repair_first_seen.CorpusMeasurement(
        True, id_provenance={"x1": "pre-existing", "x2": "undated"}
    )
    repair_first_seen._print_fallback_warning(measurement)
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------
# _measure_corpus against the REAL, already-on-disk corpus -- read-only.
# Neither test below calls repair_file or main, so nothing here can re-date
# a row or touch catalog/ or conf/. This is the ground-truth regression the
# whole refactor exists to protect.
# --------------------------------------------------------------------------

def test_measure_corpus_reproduces_the_real_corpus_ground_truth() -> None:
    measurement = repair_first_seen._measure_corpus(repair_first_seen.CORPUS_L1)

    assert measurement.measured is True
    assert measurement.reason is None
    assert len(measurement.arm_b_ids) == 32
    assert len(measurement.comparator_ids) == 102

    arm_b = repair_first_seen._summarize_family(measurement.arm_b_ids, measurement.id_provenance)
    comparator = repair_first_seen._summarize_family(measurement.comparator_ids, measurement.id_provenance)
    assert arm_b == (17, 3, 12, 0)
    assert comparator == (66, 4, 32, 0)
    assert repair_first_seen._pct_pre_dated(*arm_b[:3]) == "53.1%"
    assert repair_first_seen._pct_pre_dated(*comparator[:3]) == "64.7%"


def test_warning_fires_from_the_real_corpus_independent_of_any_runs_deltas() -> None:
    """_print_fallback_warning's signature takes only a CorpusMeasurement --
    it cannot see, and therefore cannot be influenced by, how many rows any
    particular run dated. This proves the real corpus's 90.1% fallback share
    fires from corpus provenance alone."""
    measurement = repair_first_seen._measure_corpus(repair_first_seen.CORPUS_L1)
    assert measurement.measured is True

    fallback, dated = repair_first_seen._fallback_share(measurement.id_provenance)
    assert dated > 0
    assert f"{fallback / dated * 100:.1f}%" == "90.1%"

    import io
    from contextlib import redirect_stderr
    buf = io.StringIO()
    with redirect_stderr(buf):
        repair_first_seen._print_fallback_warning(measurement)
    assert "90.1%" in buf.getvalue()


def test_measure_corpus_not_measured_when_target_is_not_the_corpus(tmp_path: Path) -> None:
    scratch = tmp_path / "not-the-corpus"
    scratch.mkdir()
    measurement = repair_first_seen._measure_corpus(scratch)
    assert measurement == repair_first_seen.CorpusMeasurement(False, "target is not the corpus")


def test_measure_corpus_not_measured_when_corpus_directory_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """monkeypatch, not an argument: there is no CLI flag that reaches this
    branch in production (CORPUS_L1 always exists in this checkout), so the
    only way to exercise it at all is to substitute the constant for the
    duration of one test."""
    missing = tmp_path / "no-such-corpus"
    monkeypatch.setattr(repair_first_seen, "CORPUS_L1", missing)
    measurement = repair_first_seen._measure_corpus(missing)
    assert measurement.measured is False
    assert measurement.reason == f"no corpus directory at {missing}"


def test_measure_corpus_not_measured_when_clusters_file_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_dir = tmp_path / "L1"
    corpus_dir.mkdir()
    missing_clusters = tmp_path / "no-such-clusters.jsonl"
    monkeypatch.setattr(repair_first_seen, "CORPUS_L1", corpus_dir)
    monkeypatch.setattr(repair_first_seen, "CORPUS_CLUSTERS", missing_clusters)

    measurement = repair_first_seen._measure_corpus(corpus_dir)

    assert measurement.measured is False
    assert measurement.reason == f"no clusters file at {missing_clusters}"


# --------------------------------------------------------------------------
# The one CLI-reachable statistics behaviour: NOT MEASURED when --l1 (which
# only ever retargets REPAIR) doesn't resolve to CORPUS_L1. No fixture here
# pretends to be "the corpus" -- it's an ordinary scratch file, and the
# point of the test is exactly that it can never be mistaken for one.
# --------------------------------------------------------------------------

def test_cli_does_not_print_withdrawn_statistics_when_l1_is_not_the_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    row = _load_fixture_row("fixture-existing-1")
    target = env.target(row)

    exit_code = repair_first_seen.main(env.main_args("--l1", str(target)))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DIFFERENTIAL" not in captured.err
    assert "WARNING" not in captured.err
