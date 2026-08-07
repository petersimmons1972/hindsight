"""Contract tests for Issue #32's retained date-repair behavior.

Successful runs report only anchor, fallback, and still-undated work counts.
Git-anchor dates land in ``first_seen``; ingest fallbacks land only in
``first_seen_fallback`` (founder ruling: never conflate the two). Invalid
input fails loudly. Withdrawn DIFFERENTIAL/fallback-WARNING surfaces stay gone.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from pipeline import repair_first_seen


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, env=env)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "date-repair-test@example.com")
    _git(repo, "config", "user.name", "date-repair-test")


def _commit(repo: Path, relpath: str, content: str, timestamp: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", relpath)
    env = {**os.environ, "GIT_AUTHOR_DATE": timestamp, "GIT_COMMITTER_DATE": timestamp}
    _git(repo, "commit", "-q", "-m", "fixture", env=env)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.projects = tmp_path / "projects"
        self.source = self.projects / "sample-root"
        self.hindsight = tmp_path / "hindsight"
        self.l1 = tmp_path / "L1"
        self.conf = tmp_path / "source-roots.conf"
        _init_repo(self.source)
        _init_repo(self.hindsight)
        self.l1.mkdir()
        self.conf.write_text("sample:sample-root\n", encoding="utf-8")

    def target(self, rows: list[dict]) -> Path:
        target = self.l1 / "sample.jsonl"
        target.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return target

    def args(self, target: Path) -> list[str]:
        return [
            "--l1", str(target), "--source-roots", str(self.conf),
            "--projects-dir", str(self.projects), "--self-dir", str(self.hindsight),
            "--hindsight-repo", str(self.hindsight),
        ]


def _row(row_id: str, anchor: str, *, first_seen: str | None = None) -> dict:
    row = {
        "id": row_id,
        "source_path": "sample-root/docs/source.md",
        "source_anchor": anchor,
        "instance": "fixture",
        "check": "n/a",
        "enforcement": None,
        "auto": "machine",
    }
    if first_seen is not None:
        row["first_seen"] = first_seen
    return row


def _load(path: Path) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def test_dates_by_anchor_and_preserves_provenance(tmp_path: Path) -> None:
    env = Env(tmp_path)
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    target = env.target([_row("anchor", "Anchor")])

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf.read_text()),
        projects_dir=env.projects,
        self_dir=env.hindsight,
        hindsight_repo=env.hindsight,
    )

    assert stats == repair_first_seen.RepairStats(dated_by_anchor=1)
    assert _load(target)["anchor"]["first_seen"] == "2026-01-08"
    assert _load(target)["anchor"]["first_seen_provenance"] == "git-anchor"
    assert "first_seen_fallback" not in _load(target)["anchor"]


def test_fallback_never_renders_as_first_seen(tmp_path: Path) -> None:
    """Founder ruling: ingest fallback is a distinct field, never first_seen."""
    env = Env(tmp_path)
    _commit(env.hindsight, "pipeline/L1/sample.jsonl", '{"id":"fallback"}\n', "2026-03-03T12:00:00+00:00")
    target = env.target([_row("fallback", "Absent"), _row("undated", "Absent")])

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf.read_text()),
        projects_dir=env.projects,
        self_dir=env.hindsight,
        hindsight_repo=env.hindsight,
    )

    rows = _load(target)
    assert stats == repair_first_seen.RepairStats(dated_by_fallback=1, still_undated=1)
    assert rows["fallback"]["first_seen_provenance"] == "l1-ingest-fallback"
    assert rows["fallback"]["first_seen_fallback"] == "2026-03-03"
    # Structural distinction — not a convention on provenance alone.
    assert rows["fallback"].get("first_seen") is None
    assert "first_seen" not in rows["undated"] or rows["undated"].get("first_seen") is None
    assert "first_seen_provenance" not in rows["undated"]
    assert "first_seen_fallback" not in rows["undated"]


def test_fallback_on_null_first_seen_shape_leaves_first_seen_null(tmp_path: Path) -> None:
    """Corpus undated rows often carry explicit first_seen: null — keep that shape."""
    env = Env(tmp_path)
    _commit(env.hindsight, "pipeline/L1/sample.jsonl", '{"id":"nullish"}\n', "2026-04-04T12:00:00+00:00")
    row = _row("nullish", "Absent")
    row["first_seen"] = None
    target = env.target([row])

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf.read_text()),
        projects_dir=env.projects,
        self_dir=env.hindsight,
        hindsight_repo=env.hindsight,
    )

    out = _load(target)["nullish"]
    assert stats == repair_first_seen.RepairStats(dated_by_fallback=1)
    assert out["first_seen"] is None
    assert out["first_seen_fallback"] == "2026-04-04"
    assert out["first_seen_provenance"] == "l1-ingest-fallback"


def test_normal_run_prints_all_three_counts_and_no_withdrawn_reporting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    _commit(env.hindsight, "pipeline/L1/sample.jsonl", '{"id":"fallback"}\n', "2026-03-03T12:00:00+00:00")
    target = env.target([
        _row("anchor", "Anchor"),
        _row("fallback", "Absent"),
        _row("undated", "Absent"),
        _row("existing", "Absent", first_seen="2020-01-01"),
    ])

    assert repair_first_seen.main(env.args(target)) == 0
    err = capsys.readouterr().err
    assert "DATED-BY-ANCHOR: 1" in err
    assert "DATED-BY-FALLBACK: 1" in err
    assert "STILL-UNDATED: 1" in err
    assert "DIFF" + "ERENTIAL" not in err
    assert "WARN" + "ING" not in err
    rows = _load(target)
    assert rows["existing"] == _row("existing", "Absent", first_seen="2020-01-01")
    assert rows["anchor"]["first_seen"] == "2026-01-08"
    assert rows["fallback"].get("first_seen") is None
    assert rows["fallback"]["first_seen_fallback"] == "2026-03-03"


def test_empty_input_fails_loudly_and_names_the_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    target = env.l1 / "empty.jsonl"
    target.touch()

    assert repair_first_seen.main(env.args(target)) == 1
    err = capsys.readouterr().err
    assert str(target) in err
    assert "L1 input is empty" in err
    assert "NOT MEASURED" in err
    assert "DATED-BY-ANCHOR" not in err


def test_directory_validation_error_preserves_every_file_byte_for_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Directory mode validates every staged repair before replacing a file."""
    env = Env(tmp_path)
    env.conf.write_text("a:sample-root\n", encoding="utf-8")
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    early = env.l1 / "a.jsonl"
    late = env.l1 / "z.jsonl"
    early.write_text(json.dumps(_row("anchor", "Anchor")) + "\n", encoding="utf-8")
    late.write_text('{"id":\n', encoding="utf-8")
    original = {path: path.read_bytes() for path in (early, late)}

    assert repair_first_seen.main(env.args(env.l1)) == 1

    assert {path: path.read_bytes() for path in (early, late)} == original
    err = capsys.readouterr().err
    assert "invalid JSON" in err
    assert "NOT MEASURED" in err


def _directory_targets_with_repairable_rows(env: Env) -> tuple[Path, Path]:
    env.conf.write_text("a:sample-root\nb:sample-root\n", encoding="utf-8")
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    first, second = env.l1 / "a.jsonl", env.l1 / "b.jsonl"
    first.write_text(json.dumps(_row("a", "Anchor")) + "\n", encoding="utf-8")
    second.write_text(json.dumps(_row("b", "Anchor")) + "\n", encoding="utf-8")
    return first, second


def test_directory_replace_failure_restores_every_original_and_cleans_temps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed later replacement compensates earlier replacements."""
    env = Env(tmp_path)
    first, second = _directory_targets_with_repairable_rows(env)
    original = {path: path.read_bytes() for path in (first, second)}
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(repair_first_seen.os, "replace", fail_second_replace)

    assert repair_first_seen.main(env.args(env.l1)) == 1

    assert {path: path.read_bytes() for path in (first, second)} == original
    assert not list(env.l1.glob(".*"))
    err = capsys.readouterr().err
    assert "injected second replace failure" in err
    assert "NOT MEASURED" in err


def test_cleanup_leftovers_do_not_change_committed_or_repeat_run_outcomes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-commit cleanup failures are warnings, not failed measurements."""
    env = Env(tmp_path)
    first, second = _directory_targets_with_repairable_rows(env)
    real_unlink = Path.unlink
    refused: list[Path] = []

    def fail_backup_unlink(path: Path, missing_ok: bool = False) -> None:
        if ".backup-" in path.name:
            refused.append(path)
            raise OSError("injected backup cleanup failure")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_backup_unlink)

    assert repair_first_seen.main(env.args(env.l1)) == 0

    assert _load(first)["a"]["first_seen"] == "2026-01-08"
    assert _load(second)["b"]["first_seen"] == "2026-01-08"
    assert len(refused) == 2
    assert all(path.exists() for path in refused)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "repaired outputs were committed" in err
    assert all(str(path) in err for path in refused)
    assert "DATED-BY-ANCHOR: 2" in err
    assert "DATED-BY-FALLBACK: 0" in err
    assert "STILL-UNDATED: 0" in err
    assert "NOT MEASURED" not in err

    monkeypatch.undo()
    assert repair_first_seen.main(env.args(env.l1)) == 0
    repeat_err = capsys.readouterr().err
    assert "DATED-BY-ANCHOR: 0" in repeat_err
    assert "DATED-BY-FALLBACK: 0" in repeat_err
    assert "STILL-UNDATED: 0" in repeat_err
    assert "WARNING" not in repeat_err
    assert "NOT MEASURED" not in repeat_err


def test_single_file_replace_failure_restores_original_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single-file mode uses staged replacement and compensation."""
    env = Env(tmp_path)
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    target = env.target([_row("anchor", "Anchor")])
    original = target.read_bytes()
    real_replace = os.replace
    calls = 0

    def fail_replacement(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected single-file replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(repair_first_seen.os, "replace", fail_replacement)

    assert repair_first_seen.main(env.args(target)) == 1

    assert target.read_bytes() == original
    assert not list(env.l1.glob(".*"))
    err = capsys.readouterr().err
    assert "injected single-file replace failure" in err
    assert "NOT MEASURED" in err


def test_single_file_rollback_failure_names_byte_identical_recovery_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambiguous replace failure preserves an exact original-byte recovery path."""
    env = Env(tmp_path)
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    target = env.target([_row("anchor", "Anchor")])
    original = target.read_bytes()
    real_replace = os.replace
    calls = 0

    def replace_then_fail_rollback(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            real_replace(source, destination)
            raise OSError("injected ambiguous replace failure")
        if calls == 2:
            raise OSError("injected single-file rollback failure")
        real_replace(source, destination)

    monkeypatch.setattr(repair_first_seen.os, "replace", replace_then_fail_rollback)

    assert repair_first_seen.main(env.args(target)) == 1

    recovery_paths = list(env.l1.glob(".sample.jsonl.backup-*"))
    assert len(recovery_paths) == 1
    recovery_path = recovery_paths[0]
    assert recovery_path.read_bytes() == original
    err = capsys.readouterr().err
    assert "injected ambiguous replace failure" in err
    assert "injected single-file rollback failure" in err
    assert str(recovery_path) in err
    assert "contains the original bytes" in err
    assert "NOT MEASURED" in err


def test_staging_metadata_failure_preserves_originals_and_cleans_registered_temp(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chmod/stat failure cannot leak a staged output or mutate a target."""
    env = Env(tmp_path)
    first, second = _directory_targets_with_repairable_rows(env)
    original = {path: path.read_bytes() for path in (first, second)}

    def fail_chmod(_path: str | Path, _mode: int) -> None:
        raise OSError("injected staging chmod failure")

    monkeypatch.setattr(repair_first_seen.os, "chmod", fail_chmod)

    assert repair_first_seen.main(env.args(env.l1)) == 1

    assert {path: path.read_bytes() for path in (first, second)} == original
    assert not list(env.l1.glob(".*"))
    err = capsys.readouterr().err
    assert "injected staging chmod failure" in err
    assert "NOT MEASURED" in err


def test_rollback_failure_names_both_errors_and_preserves_recovery_backup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed rollback leaves the original's backup available for recovery."""
    env = Env(tmp_path)
    first, second = _directory_targets_with_repairable_rows(env)
    original = {path: path.read_bytes() for path in (first, second)}
    real_replace = os.replace
    calls = 0

    def fail_commit_and_rollback(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected primary replace failure")
        if calls == 3:
            raise OSError("injected rollback replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(repair_first_seen.os, "replace", fail_commit_and_rollback)

    assert repair_first_seen.main(env.args(env.l1)) == 1

    recovery_paths = list(env.l1.glob(".b.jsonl.backup-*"))
    assert len(recovery_paths) == 1
    recovery_path = recovery_paths[0]
    assert recovery_path.read_bytes() == original[second]
    err = capsys.readouterr().err
    assert "injected primary replace failure" in err
    assert "injected rollback replace failure" in err
    assert str(recovery_path) in err
    assert "contains the original bytes" in err
    assert "NOT MEASURED" in err


def test_predated_row_with_resolvable_anchor_preserves_date_and_provenance(tmp_path: Path) -> None:
    env = Env(tmp_path)
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    row = _row("predated-anchor", "Anchor", first_seen="2020-01-01")
    row["first_seen_provenance"] = "historical-import"
    target = env.target([row])

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf.read_text()),
        projects_dir=env.projects,
        self_dir=env.hindsight,
        hindsight_repo=env.hindsight,
    )

    assert stats == repair_first_seen.RepairStats()
    assert _load(target)["predated-anchor"] == row


def test_predated_row_with_resolvable_fallback_preserves_date_and_provenance(tmp_path: Path) -> None:
    env = Env(tmp_path)
    _commit(env.hindsight, "pipeline/L1/sample.jsonl", '{"id":"predated-fallback"}\n', "2026-03-03T12:00:00+00:00")
    row = _row("predated-fallback", "Absent", first_seen="2020-01-01")
    row["first_seen_provenance"] = "historical-import"
    target = env.target([row])

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf.read_text()),
        projects_dir=env.projects,
        self_dir=env.hindsight,
        hindsight_repo=env.hindsight,
    )

    assert stats == repair_first_seen.RepairStats()
    assert _load(target)["predated-fallback"] == row


def test_anchor_upgrades_over_prior_fallback_field(tmp_path: Path) -> None:
    """If a later run finds a real anchor, first_seen wins and fallback is dropped."""
    env = Env(tmp_path)
    _commit(env.source, "docs/source.md", "# source\n## Anchor\n", "2026-01-08T09:00:00+00:00")
    row = _row("upgrade", "Anchor")
    row["first_seen"] = None
    row["first_seen_fallback"] = "2025-01-01"
    row["first_seen_provenance"] = "l1-ingest-fallback"
    target = env.target([row])

    stats = repair_first_seen.repair_file(
        target,
        roots=repair_first_seen.parse_source_roots(env.conf.read_text()),
        projects_dir=env.projects,
        self_dir=env.hindsight,
        hindsight_repo=env.hindsight,
    )

    out = _load(target)["upgrade"]
    assert stats == repair_first_seen.RepairStats(dated_by_anchor=1)
    assert out["first_seen"] == "2026-01-08"
    assert out["first_seen_provenance"] == "git-anchor"
    assert "first_seen_fallback" not in out


def test_repeat_run_does_not_recount_existing_fallback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = Env(tmp_path)
    _commit(env.hindsight, "pipeline/L1/sample.jsonl", '{"id":"fallback"}\n', "2026-03-03T12:00:00+00:00")
    target = env.target([_row("fallback", "Absent")])

    assert repair_first_seen.main(env.args(target)) == 0
    assert "DATED-BY-FALLBACK: 1" in capsys.readouterr().err

    assert repair_first_seen.main(env.args(target)) == 0
    err = capsys.readouterr().err
    assert "DATED-BY-FALLBACK: 0" in err
    assert "STILL-UNDATED: 0" in err
    assert _load(target)["fallback"]["first_seen_fallback"] == "2026-03-03"
    assert _load(target)["fallback"].get("first_seen") is None


def test_withdrawn_reporting_surface_is_not_exported() -> None:
    withdrawn_names = (
        "Corpus" + "Measurement", "ARM_B_" + "FAMILIES", "COMPARATOR_" + "FAMILIES",
        "_print_" + "differential", "_print_fallback_" + "warning",
    )
    assert all(not hasattr(repair_first_seen, name) for name in withdrawn_names)
