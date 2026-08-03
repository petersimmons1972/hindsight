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
