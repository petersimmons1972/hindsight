"""Contract tests for the ``first_seen`` date-repair tool (Issue #32, packet P0).

RED phase only: ``pipeline/repair_first_seen.py`` does not exist yet. Every test
below is expected to fail on collection (ModuleNotFoundError) until the module
is implemented in the next packet. That is the point -- these tests pin the
contract first.

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

All git fixtures below are built as disposable temp repos at test time --
nothing here touches the real ~/projects checkouts, conf/, or catalog/.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import repair_first_seen  # RED: module does not exist yet


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
    """A disposable projects_dir + hindsight_repo pair, wired for --source-roots."""

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


# --------------------------------------------------------------------------
# D-1: FABRICATED STATISTIC -- the differential must be computed over the
# real corpus directory, never a directory inferred from --l1. If the run's
# target isn't the real corpus, print NOT MEASURED, never a number.
# --------------------------------------------------------------------------

def test_differential_not_measured_when_target_is_not_the_real_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)

    # The real corpus (self_dir/pipeline/L1): a1 IS dated, via git-anchor.
    corpus_dir = env.hindsight_repo / "pipeline" / "L1"
    corpus_dir.mkdir(parents=True)
    l2_dir = env.hindsight_repo / "pipeline" / "L2"
    l2_dir.mkdir(parents=True)
    (l2_dir / "clusters.jsonl").write_text(
        json.dumps({"cluster_id": "c-043", "members": ["a1"]}) + "\n", encoding="utf-8"
    )
    (corpus_dir / "sample.jsonl").write_text(
        json.dumps({"id": "a1", "first_seen": "2020-01-01",
                     "first_seen_provenance": "git-anchor"}) + "\n",
        encoding="utf-8",
    )

    # This run's actual TARGET is an unrelated scratch file whose parent dir
    # happens to contain a same-id row that is UNDATED. If the differential's
    # directory is inferred from the target's parent (the bug), it reports
    # a1 as 0% dated -- the opposite of the real corpus's 100%. Either number
    # is a fabrication here; the only honest output is "not measured".
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    (scratch_dir / "unrelated-noise.jsonl").write_text(
        json.dumps({"id": "a1"}) + "\n", encoding="utf-8"
    )
    row = _load_fixture_row("fixture-existing-1")
    target_file = scratch_dir / "sample.jsonl"
    target_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

    exit_code = repair_first_seen.main(env.main_args("--l1", str(target_file)))

    captured = capsys.readouterr()
    assert exit_code == 0
    diff_lines = [ln for ln in captured.err.splitlines() if "DIFFERENTIAL" in ln]
    assert len(diff_lines) == 1
    assert diff_lines[0] == "date-repair: DIFFERENTIAL: NOT MEASURED (target is not the corpus)"


# --------------------------------------------------------------------------
# D-2: R4 VIOLATION -- on a fail-loud path, no counts (not even zeros) may
# be printed. A zero must never look like "wasn't measured".
# --------------------------------------------------------------------------

def test_fail_loud_path_prints_not_measured_never_zero_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    empty = env.l1_dir / "sample.jsonl"
    empty.write_text("", encoding="utf-8")

    exit_code = repair_first_seen.main(env.main_args("--l1", str(empty)))

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "date-repair: ERROR:" in captured.err
    assert "date-repair: NOT MEASURED" in captured.err
    # A zero count must never be emitted on this path -- it is
    # indistinguishable from a genuine all-zero successful run.
    assert "DATED-BY-ANCHOR" not in captured.err
    assert "DATED-BY-FALLBACK" not in captured.err
    assert "STILL-UNDATED" not in captured.err


# --------------------------------------------------------------------------
# D-3: DEGENERATE METRIC -- the differential must report the split across
# pre-existing / git-anchor / l1-ingest-fallback provenance, not just
# "first_seen is not None", which goes to 100%/100% once repair finishes
# and can never again surface the bias it exists to surface.
# --------------------------------------------------------------------------

def test_differential_reports_provenance_split_not_just_dated_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    corpus_dir = env.hindsight_repo / "pipeline" / "L1"
    corpus_dir.mkdir(parents=True)
    l2_dir = env.hindsight_repo / "pipeline" / "L2"
    l2_dir.mkdir(parents=True)
    (l2_dir / "clusters.jsonl").write_text(
        json.dumps({"cluster_id": "c-043", "members": ["a1", "a2", "a3", "a4"]}) + "\n"
        + json.dumps({"cluster_id": "c-003", "members": ["b1", "b2"]}) + "\n",
        encoding="utf-8",
    )
    # Every one of these six rows already carries first_seen -- the old
    # "is not None" metric would read 100.0%/100.0% and hide the skew below.
    (corpus_dir / "sample.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in [
            {"id": "a1", "first_seen": "2020-01-01"},
            {"id": "a2", "first_seen": "2020-01-01", "first_seen_provenance": "git-anchor"},
            {"id": "a3", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
            {"id": "a4", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
            {"id": "b1", "first_seen": "2020-01-01"},
            {"id": "b2", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
        ]),
        encoding="utf-8",
    )

    exit_code = repair_first_seen.main(env.main_args())

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "100.0%" not in captured.err
    assert (
        "date-repair: DIFFERENTIAL: intervention-family (n=4) "
        "pre-existing=1 git-anchor=1 l1-ingest-fallback=2 undated=0 -> 25.0% pre-dated"
    ) in captured.err
    assert (
        "date-repair: DIFFERENTIAL: comparator-pool (n=2) "
        "pre-existing=1 git-anchor=0 l1-ingest-fallback=1 undated=0 -> 50.0% pre-dated"
    ) in captured.err


# --------------------------------------------------------------------------
# D-4 / B-1: the >50%-fallback WARNING must be computed from CORPUS
# PROVENANCE -- the first_seen_provenance tags already sitting on the L1
# rows -- never from this run's own deltas. Repair is idempotent: the run
# that dates rows only happens once per row, so a deltas-gated warning goes
# permanently silent in steady state (dated_this_run == 0 forever after)
# even while the corpus stays mostly fallback-dated. The warning must fire
# on EVERY run against the real corpus, whether or not this run itself
# dated anything.
# --------------------------------------------------------------------------

def test_warning_fires_from_corpus_provenance_even_when_run_dates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    corpus_dir = env.hindsight_repo / "pipeline" / "L1"
    corpus_dir.mkdir(parents=True)
    l2_dir = env.hindsight_repo / "pipeline" / "L2"
    l2_dir.mkdir(parents=True)
    (l2_dir / "clusters.jsonl").write_text("", encoding="utf-8")

    # Steady state: every row already carries first_seen + provenance, so
    # THIS run dates zero of them -- but the corpus itself is 3 fallback /
    # 1 anchor = 75% fallback, which must still trigger the WARNING.
    (corpus_dir / "sample.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in [
            {"id": "x1", "first_seen": "2020-01-01", "first_seen_provenance": "git-anchor"},
            {"id": "x2", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
            {"id": "x3", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
            {"id": "x4", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
        ]),
        encoding="utf-8",
    )

    exit_code = repair_first_seen.main(env.main_args())

    captured = capsys.readouterr()
    assert exit_code == 0
    # This run itself dated nothing -- the old deltas-based warning would
    # have gone silent here. Prove it didn't.
    assert "date-repair: DATED-BY-ANCHOR: 0" in captured.err
    assert "date-repair: DATED-BY-FALLBACK: 0" in captured.err
    assert "date-repair: WARNING:" in captured.err
    assert "75.0%" in captured.err


def test_warning_reflects_corpus_not_this_runs_deltas(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run that itself dates a single anchor row (a minority outcome)
    must still warn, because the CORPUS around it is majority-fallback --
    the opposite of what a deltas-based (this run only) computation would
    show for a single anchor-only delta."""
    env = Env(tmp_path)
    corpus_dir = env.hindsight_repo / "pipeline" / "L1"
    corpus_dir.mkdir(parents=True)
    l2_dir = env.hindsight_repo / "pipeline" / "L2"
    l2_dir.mkdir(parents=True)
    (l2_dir / "clusters.jsonl").write_text("", encoding="utf-8")

    _commit(env.sample_root, "docs/anchor.md",
            "# Doc\n\n## Anchor Heading One\nOriginal text.\n",
            "2026-01-08T09:00:00+00:00", "add anchor heading")

    # Pre-existing corpus rows: already 3 fallback-dated, 0 anchor-dated.
    # This run's OWN delta is 1 anchor / 0 fallback -- by itself a 0%
    # fallback share -- but the corpus as a whole is still majority
    # fallback once the new anchor row is folded in (3 of 4 = 75%).
    (corpus_dir / "sample.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in [
            {
                "id": "sample-anchor-1",
                "source_path": "sampleroot/docs/anchor.md",
                "source_anchor": "Anchor Heading One",
                "instance": "An anchor-dateable entry.",
                "check": "n/a",
                "enforcement": None,
                "auto": "machine",
            },
            {"id": "x2", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
            {"id": "x3", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
            {"id": "x4", "first_seen": "2020-01-01", "first_seen_provenance": "l1-ingest-fallback"},
        ]),
        encoding="utf-8",
    )

    exit_code = repair_first_seen.main(env.main_args())

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "date-repair: DATED-BY-ANCHOR: 1" in captured.err
    assert "date-repair: DATED-BY-FALLBACK: 0" in captured.err
    assert "date-repair: WARNING:" in captured.err
    assert "75.0%" in captured.err


# --------------------------------------------------------------------------
# B-2(a): a differential over a directory where cluster members don't
# actually resolve (id absent from every loaded L1 row) must ALARM --
# "NOT MEASURED (<n> of <m> cluster members did not resolve)" -- never
# silently exclude the unresolved ids and print a count for the rest as if
# it were the whole family.
# --------------------------------------------------------------------------

def test_differential_not_measured_when_cluster_members_do_not_resolve(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    corpus_dir = env.hindsight_repo / "pipeline" / "L1"
    corpus_dir.mkdir(parents=True)
    l2_dir = env.hindsight_repo / "pipeline" / "L2"
    l2_dir.mkdir(parents=True)
    (l2_dir / "clusters.jsonl").write_text(
        json.dumps({"cluster_id": "c-043", "members": ["a1", "a2"]}) + "\n"
        + json.dumps({"cluster_id": "c-003", "members": ["b1"]}) + "\n",
        encoding="utf-8",
    )
    # Only a1 is ever loaded -- a2 and b1 are absent from every L1 row, i.e.
    # never resolve. 2 of the 3 expected members are unresolved.
    (corpus_dir / "sample.jsonl").write_text(
        json.dumps({"id": "a1", "first_seen": "2020-01-01", "first_seen_provenance": "git-anchor"}) + "\n",
        encoding="utf-8",
    )

    exit_code = repair_first_seen.main(env.main_args())

    captured = capsys.readouterr()
    assert exit_code == 0
    diff_lines = [ln for ln in captured.err.splitlines() if "DIFFERENTIAL" in ln]
    assert diff_lines == [
        "date-repair: DIFFERENTIAL: NOT MEASURED (2 of 3 cluster members did not resolve)"
    ]
    assert "intervention-family" not in captured.err
    assert "comparator-pool" not in captured.err


def test_differential_all_members_unresolved_reports_not_measured_not_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reproduces the exact scratch-directory shape from the B-2 report:
    a --self-dir/--l1/--clusters combination where the L1 rows loaded share
    no ids with the cluster membership at all. 0 of N resolving must ALARM,
    never print a fully-formed zero differential as if it were a real
    measurement of an empty family."""
    env = Env(tmp_path)
    corpus_dir = env.hindsight_repo / "pipeline" / "L1"
    corpus_dir.mkdir(parents=True)
    l2_dir = env.hindsight_repo / "pipeline" / "L2"
    l2_dir.mkdir(parents=True)
    (l2_dir / "clusters.jsonl").write_text(
        json.dumps({"cluster_id": "c-043", "members": ["a1", "a2", "a3"]}) + "\n"
        + json.dumps({"cluster_id": "c-003", "members": ["b1"]}) + "\n",
        encoding="utf-8",
    )
    # A scratch corpus with unrelated ids -- 0 of the 4 expected members
    # resolve.
    (corpus_dir / "sample.jsonl").write_text(
        json.dumps({"id": "unrelated-1", "first_seen": "2020-01-01"}) + "\n",
        encoding="utf-8",
    )

    exit_code = repair_first_seen.main(env.main_args())

    captured = capsys.readouterr()
    assert exit_code == 0
    diff_lines = [ln for ln in captured.err.splitlines() if "DIFFERENTIAL" in ln]
    assert diff_lines == [
        "date-repair: DIFFERENTIAL: NOT MEASURED (4 of 4 cluster members did not resolve)"
    ]
    assert "n=0" not in captured.err
    assert "n=3" not in captured.err
    assert "n=1" not in captured.err
