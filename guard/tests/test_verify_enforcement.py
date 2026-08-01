"""Contract tests for the L1 enforcement-existence verifier.

The verifier resolves each `auto: machine` entry's enforcement path against
the checkout root of the source it came from -- NOT against a single shared
directory. A path is one of three things:

  enforced      -- root known and present, path resolves.        (silent)
  phantom       -- root known and present, path does NOT resolve. (FATAL)
  UNVERIFIABLE  -- root unknown, or root known but absent on this machine.
                   Reported loudly with a count; never folded into "enforced".

And the whole check refuses to report success if it could not see anything:
zero resolved roots is an ERROR, not a vacuous pass.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "guard" / "failure_mode_catalog_guard.py"
SPEC = importlib.util.spec_from_file_location("failure_mode_catalog_guard", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_records(l1_dir: Path, source: str, *records: dict[object, object]) -> None:
    (l1_dir / f"{source}.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def write_source_roots(path: Path, mapping: dict[str, str]) -> None:
    lines = [f"{source}:{relpath}" for source, relpath in mapping.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_verifier(
    monkeypatch: pytest.MonkeyPatch,
    l1_dir: Path,
    projects: Path,
    source_roots_path: Path,
    extra_args: list[str] | None = None,
) -> int:
    monkeypatch.setattr(MODULE, "default_l1_dir", lambda: l1_dir)
    monkeypatch.setattr(MODULE, "default_projects_dir", lambda: projects)
    monkeypatch.setattr(MODULE, "default_source_roots_path", lambda: source_roots_path)
    return MODULE.main(["--verify-enforcement", *(extra_args or [])])


def machine_record(id_: str, enforcement: dict[str, str] | None) -> dict[str, object]:
    return {"id": id_, "auto": "machine", "enforcement": enforcement}


# ---------------------------------------------------------------------------
# Baseline: root known and present.
# ---------------------------------------------------------------------------


def test_root_known_and_path_exists_is_enforced_and_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    err = capsys.readouterr().err
    assert "phantom:" not in err
    assert "control.py" not in err  # enforced entries are silent, not just non-fatal


def test_root_known_and_path_absent_is_phantom_names_entry_and_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing/control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    err = capsys.readouterr().err
    assert "missing/control.py" in err
    assert "sample" in err
    assert "example" in err


# ---------------------------------------------------------------------------
# UNVERIFIABLE: two distinct reasons, neither counted as enforced (silent pass).
# ---------------------------------------------------------------------------


def test_root_unknown_is_unverifiable_not_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    # A second, mapped-and-present source so the overall "zero roots resolved"
    # floor is satisfied and doesn't mask what we're testing here.
    (projects / "anchor-repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"anchor": "anchor-repo"})
    write_records(l1_dir, "anchor", machine_record("anchor-1", None))
    # "orphan" has NO entry in source-roots.conf at all.
    write_records(
        l1_dir, "orphan", machine_record("orphan-1", {"file": "control.py", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 0  # unverifiable is not a failure
    assert "phantom:" not in err
    assert "unverifiable" in err.lower()
    assert "orphan" in err
    assert "1" in err  # the count is printed somewhere


def test_root_known_but_directory_missing_is_unverifiable_not_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "anchor-repo").mkdir()
    roots_path = tmp_path / "source-roots.conf"
    # "vanished" is mapped, but its target directory does not exist on this
    # machine -- exactly the CI-runner-without-checkouts case, but scoped to
    # one source instead of all of them.
    write_source_roots(roots_path, {"anchor": "anchor-repo", "vanished": "never-checked-out"})
    write_records(l1_dir, "anchor", machine_record("anchor-1", None))
    write_records(
        l1_dir, "vanished", machine_record("v-1", {"file": "control.py", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "phantom:" not in err
    assert "unverifiable" in err.lower()
    assert "vanished" in err


# ---------------------------------------------------------------------------
# The fail-open case: nothing resolved must ERROR, never silently pass.
# ---------------------------------------------------------------------------


def test_zero_roots_resolved_is_an_error_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()  # exists, but none of the mapped repo subdirs do
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "does-not-exist-on-this-machine"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err  # must fail as an ERROR, not be misreported as a phantom
    assert "error" in err.lower()


def test_require_roots_flag_raises_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo-a").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"a": "repo-a", "b": "repo-b-not-checked-out"})
    write_records(l1_dir, "a", machine_record("a-1", None))
    write_records(l1_dir, "b", machine_record("b-1", None))

    # Only 1 of 2 mapped roots resolves; demanding 2 must ERROR even though
    # nothing is phantom.
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, extra_args=["--require-roots", "2"]
    )
    assert exit_code != 0
    assert "error" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# The inverse of the original bug: a path that happens to exist SOMEWHERE
# under projects_dir (in a different repo) must not count as enforced just
# because it was found -- it must resolve under ITS OWN mapped root.
# ---------------------------------------------------------------------------


def test_path_existing_in_a_different_repo_is_still_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    # The file genuinely exists -- but in a sibling repo, not "sample"'s own root.
    (projects / "sibling-repo").mkdir(parents=True)
    (projects / "sibling-repo" / "control.py").touch()
    (projects / "sample-repo").mkdir(parents=True)  # sample's real root: empty
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "sample-repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    assert "control.py" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The map itself must never silently be treated as "no map, so all fine".
# ---------------------------------------------------------------------------


def test_missing_source_roots_conf_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    roots_path = tmp_path / "does-not-exist.conf"
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "source-roots" in err.lower() or "source_roots" in err.lower()


def test_empty_source_roots_conf_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    roots_path = tmp_path / "empty.conf"
    roots_path.write_text("# just a comment, no mappings\n", encoding="utf-8")
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err


# ---------------------------------------------------------------------------
# Preserved from the original two-way check.
# ---------------------------------------------------------------------------


def test_unbacked_machine_entry_warns_but_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    assert "WARNING" in capsys.readouterr().err


def test_unbacked_judgment_entry_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", {"id": "example", "auto": "judgment", "enforcement": None})

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    assert "WARNING" not in capsys.readouterr().err


def test_real_corpus_reports_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert MODULE.main(["--verify-enforcement"]) in {0, 1}
    output = capsys.readouterr().err
    assert "summary" in output.lower()
    assert "machine" in output.lower()
