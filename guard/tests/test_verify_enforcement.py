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


def write_known_phantoms(path: Path, records: list[dict[str, str]]) -> None:
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_enforcement_floor(path: Path, floor: int | str) -> None:
    path.write_text(f"{floor}\n", encoding="utf-8")


def run_verifier(
    monkeypatch: pytest.MonkeyPatch,
    l1_dir: Path,
    projects: Path,
    source_roots_path: Path,
    extra_args: list[str] | None = None,
    known_phantoms: list[dict[str, str]] | None = None,
    enforcement_floor: int | str | None = None,
    known_phantoms_path: Path | None = None,
    enforcement_floor_path: Path | None = None,
) -> int:
    """Drive main() with every default sandboxed to tmp_path.

    known_phantoms / enforcement_floor default to permissive, no-op values
    (an empty ledger, floor 0) so tests that don't care about the debt-
    ledger/floor gates aren't affected by them -- pass known_phantoms_path
    or enforcement_floor_path (pointing at a file you never created, or
    deliberately malformed) to exercise the "fails loud" behavior instead.
    """
    monkeypatch.setattr(MODULE, "default_l1_dir", lambda: l1_dir)
    monkeypatch.setattr(MODULE, "default_projects_dir", lambda: projects)
    monkeypatch.setattr(MODULE, "default_source_roots_path", lambda: source_roots_path)

    if known_phantoms_path is None:
        known_phantoms_path = l1_dir.parent / "known-phantoms.conf"
        write_known_phantoms(known_phantoms_path, known_phantoms or [])
    monkeypatch.setattr(MODULE, "default_known_phantoms_path", lambda: known_phantoms_path)

    if enforcement_floor_path is None:
        enforcement_floor_path = l1_dir.parent / "enforcement-floor.conf"
        write_enforcement_floor(enforcement_floor_path, 0 if enforcement_floor is None else enforcement_floor)
    monkeypatch.setattr(MODULE, "default_enforcement_floor_path", lambda: enforcement_floor_path)

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
    # Assert the exact rendered phantom line, not loose substrings -- "sample"
    # and "example" alone also appear in the always-printed per-source summary
    # row regardless of whether phantom detection ran at all, so a decorative
    # boilerplate print (or a deleted phantom-append) would pass those checks
    # for the wrong reason.
    assert "phantom: missing/control.py (sample:example," in err


# ---------------------------------------------------------------------------
# UNVERIFIABLE: two distinct reasons, neither counted as enforced (silent pass).
# ---------------------------------------------------------------------------


def test_root_unknown_is_unverifiable_not_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    # A second, mapped-and-present source with a REAL checked entry, so the
    # root floor sees at least one genuinely useful root and doesn't mask
    # what we're testing here behind the SKIPPED (zero-useful-roots) path.
    (projects / "anchor-repo").mkdir(parents=True)
    (projects / "anchor-repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"anchor": "anchor-repo"})
    write_records(
        l1_dir, "anchor", machine_record("anchor-1", {"file": "control.py", "kind": "test"})
    )
    # "orphan" has NO entry in source-roots.conf at all.
    write_records(
        l1_dir, "orphan", machine_record("orphan-1", {"file": "control.py", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 0  # unverifiable is not a failure
    assert "phantom:" not in err
    # Discriminating: this exact count+message only prints when
    # unverifiable_count > 0, i.e. the UNVERIFIABLE branch actually ran and
    # appended to report.unverifiable. A bare `continue` swapped in for that
    # branch (silently treating the entry as neither checked nor flagged)
    # would leave this count at 0 and this line unprinted -- "unverifiable"
    # in err.lower() alone does NOT catch that, because the line is printed
    # unconditionally too (in the SCOPE footer, and per-source summary row).
    assert "UNVERIFIABLE: 1 machine entries could not be checked" in err
    # The specific detail line, keyed to the entry that was actually
    # appended -- not just the source name, which also appears in the
    # always-printed summary table regardless of whether detection ran.
    assert "unverifiable: control.py (orphan:orphan-1," in err


def test_root_known_but_directory_missing_is_unverifiable_not_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "anchor-repo").mkdir()
    (projects / "anchor-repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    # "vanished" is mapped, but its target directory does not exist on this
    # machine -- exactly the CI-runner-without-checkouts case, but scoped to
    # one source instead of all of them. "anchor" has a real, resolving
    # entry so the root floor sees a genuinely useful root.
    write_source_roots(roots_path, {"anchor": "anchor-repo", "vanished": "never-checked-out"})
    write_records(
        l1_dir, "anchor", machine_record("anchor-1", {"file": "control.py", "kind": "test"})
    )
    write_records(
        l1_dir, "vanished", machine_record("v-1", {"file": "control.py", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "phantom:" not in err
    # Discriminating, same rationale as test_root_unknown_is_unverifiable_not_enforced.
    assert "UNVERIFIABLE: 1 machine entries could not be checked" in err
    assert "unverifiable: control.py (vanished:v-1," in err


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
    (projects / "repo-a" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"a": "repo-a", "b": "repo-b-not-checked-out"})
    # "a" has a real, resolving, non-null entry -- genuinely useful, not just
    # resolved. "b" doesn't resolve at all.
    write_records(l1_dir, "a", machine_record("a-1", {"file": "control.py", "kind": "test"}))
    write_records(l1_dir, "b", machine_record("b-1", None))

    # Only 1 of 2 mapped roots actually verified anything; demanding 2 must
    # ERROR even though nothing is phantom.
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, extra_args=["--require-roots", "2"]
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "error" in err.lower()


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
    # Discriminating: the bare filename alone would also match a merely
    # UNVERIFIABLE detail line or an unrelated print; the exact phantom
    # rendering only appears when the resolve-under-own-root check actually
    # failed it.
    assert "phantom: control.py (sample:example," in capsys.readouterr().err


# ---------------------------------------------------------------------------
# SELF: the one root that must resolve in ANY environment (CI included),
# because it's this checkout's own root, not a sibling under ~/projects.
# ---------------------------------------------------------------------------


def test_self_root_token_resolves_to_this_repo_regardless_of_projects_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    # projects_dir points nowhere real -- if SELF fell back to projects_dir,
    # every entry here would be UNVERIFIABLE (or ERROR at the roots floor).
    projects = tmp_path / "does-not-exist-anywhere"
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "SELF"})
    write_records(
        l1_dir,
        "sample",
        machine_record("real", {"file": "guard/failure_mode_catalog_guard.py", "kind": "test"}),
        machine_record("fake", {"file": "guard/definitely-not-a-real-file.py", "kind": "test"}),
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 1  # the fake one is a genuine (undocumented) phantom
    assert "phantom: guard/definitely-not-a-real-file.py" in err
    assert "guard/failure_mode_catalog_guard.py" not in err.replace(
        "phantom: guard/definitely-not-a-real-file.py", ""
    )  # the real one stayed silent
    # SELF resolved AND verified 2 entries -- the ROOT-FLOOR path specifically
    # must not be why this failed (it failed because the fake phantom is
    # undocumented in known-phantoms.conf, a distinct and correct gate).
    assert "refusing to report success" not in err
    assert "undocumented: phantom: guard/definitely-not-a-real-file.py" in err


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


# ---------------------------------------------------------------------------
# The falsifiable root floor (C4c item 2): a root that RESOLVES but never
# had a single non-null entry to actually check proves nothing and must not
# satisfy --require-roots. This is exactly the CI/homelab-canon shape: SELF
# always resolves, but every one of its entries is enforcement: null.
# ---------------------------------------------------------------------------


def test_resolved_root_with_zero_checked_entries_does_not_satisfy_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)  # the root genuinely resolves...
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # ...but its only entry is unbacked, so it never actually gets checked.
    write_records(l1_dir, "sample", machine_record("example", None))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, extra_args=["--require-roots", "1"])
    err = capsys.readouterr().err
    # Must NOT be a silent/vacuous pass reported as "verified" -- and must
    # not be misreported as a phantom or a hard ERROR either: the
    # environment isn't misconfigured, it structurally has nothing to check
    # yet. A declared SKIP is the honest outcome.
    assert exit_code == 0
    assert "phantom:" not in err
    assert "SKIPPED" in err


def test_zero_roots_resolved_at_all_is_still_a_hard_error_not_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Distinguishes the two honest-failure shapes: a root that resolves but
    checks nothing is a SKIP (above); NO root resolving at all is still the
    original, harder signal that the environment itself looks broken
    (wrong projects_dir, deleted source-roots.conf mappings, ...)."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()  # exists, but the mapped subdir does not
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "does-not-exist-on-this-machine"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "SKIPPED" not in err
    assert "0 of 1 mapped source roots are present on this machine at all" in err


# ---------------------------------------------------------------------------
# The enforcement-bearing floor (C4c item 3, "floor not just a cap"): the
# fleet#152 shape -- a debt ledger can be "reduced" by deleting the flagged
# entry instead of fixing it. Only a floor on the TOTAL corpus count catches
# that, and it must hold with NO root resolved at all (root-independent).
# ---------------------------------------------------------------------------


def test_enforcement_bearing_count_dropping_below_floor_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # Only 1 enforcement-bearing entry exists this run...
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    # ...but the floor says there used to be 5 -- as if 4 records were
    # deleted (or their enforcement value nulled) instead of ever being
    # fixed. That must fail loud, even though nothing here is phantom.
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor=5
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "dropped to 1, below floor 5" in err


def test_enforcement_bearing_count_at_or_above_floor_is_fine(
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

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, enforcement_floor=1)
    assert exit_code == 0


def test_missing_enforcement_floor_file_fails_loud_not_a_silent_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        enforcement_floor_path=tmp_path / "does-not-exist-floor.conf",
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "enforcement floor file not found" in err.lower()


def test_malformed_enforcement_floor_file_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))

    floor_path = tmp_path / "bad-floor.conf"
    floor_path.write_text("not-a-number\n", encoding="utf-8")
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor_path=floor_path
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "not an integer" in err.lower()


# ---------------------------------------------------------------------------
# The known-phantoms debt ledger (C4c item 3): a phantom already documented
# (with evidence + disposition) is visible debt, not a build failure -- but
# an UNDOCUMENTED phantom is fatal by default, and the ledger going missing
# must never be a silent "0 known, so nothing to check."
# ---------------------------------------------------------------------------


def test_documented_phantom_is_debt_not_a_build_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"}))

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "sample",
                "id": "example",
                "claimed_path": "missing.py",
                "evidence": "ls repo/missing.py -> absent (test fixture)",
                "disposition": "genuine-phantom: test fixture",
            }
        ],
    )
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "phantom: missing.py (sample:example," in err  # still visible, not hidden
    assert "DEBT: 1 known phantom(s)" in err


def test_undocumented_phantom_is_fatal_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)  # empty ledger
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "undocumented: phantom: missing.py (sample:example," in err
    assert "new phantoms cannot land silently" in err.lower()


def test_accept_phantom_flag_bypasses_for_this_run_only_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"}))

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, extra_args=["--accept-phantom"]
    )
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "WARNING" in err
    assert "--accept-phantom set" in err


def test_missing_known_phantoms_ledger_fails_loud_not_a_silent_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The (c) mutation bar: deleting known-phantoms.conf must go red, even
    on a corpus with zero real phantoms -- a vanished ledger must never be
    silently read as '0 known, so nothing to check.'"""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms_path=tmp_path / "does-not-exist-ledger.conf",
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "known-phantoms ledger not found" in err.lower()


def test_empty_known_phantoms_ledger_is_a_valid_zero_debt_state(
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

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, known_phantoms=[])
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "DEBT: 0 known phantom(s)" in err


# ---------------------------------------------------------------------------
# Mutation-sweep gap closures (lane-guard survivors S1, S2, S3, S8, S9, S11,
# S12, S13). Each test below was proven to FAIL against its named mutant and
# PASS against unmutated code -- see the sweep report for the diffs.
# ---------------------------------------------------------------------------


def test_path_escaping_its_own_root_is_phantom_even_when_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S1/M23: containment, not mere existence.

    `test_path_existing_in_a_different_repo_is_still_phantom` uses a bare
    filename that does not exist under EITHER root, so exists() alone already
    fails it -- it cannot discriminate the `is_relative_to` half of the check.
    Here the recorded path deliberately climbs out of its own root with `..`
    and lands on a file that genuinely EXISTS in a sibling repo. Only the
    containment half can call this a phantom.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "sibling-repo").mkdir(parents=True)
    (projects / "sibling-repo" / "control.py").touch()
    (projects / "sample-repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "sample-repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("escapee", {"file": "../sibling-repo/control.py", "kind": "test"}),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    err = capsys.readouterr().err
    assert "phantom: ../sibling-repo/control.py (sample:escapee" in err


def test_corrupt_l1_corpus_exits_nonzero_not_a_clean_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S2/M31: the corpus-integrity except-arm is a GATE, not a log line.

    Every raise inside verify_enforcement (bad JSON, non-object record, bad
    `auto`, bad `enforcement`) reaches main() through one except arm. Nothing
    asserted that arm's exit code, so a corrupt corpus could be reported as a
    clean run.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    (l1_dir / "sample.jsonl").write_text(
        json.dumps(machine_record("ok", {"file": "control.py", "kind": "test"}))
        + "\n{ this is not json }\n",
        encoding="utf-8",
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    err = capsys.readouterr().err
    assert "invalid JSON" in err


def test_total_enforcement_bearing_excludes_entries_that_enforce_nothing() -> None:
    """S3/M32: the debt floor counts units of WORK, not units PRESENT (FM-155).

    fleet#152: nulling out an `enforcement` value must lower this total. If
    the floor counted `machine` alone, a maintainer could strip every
    enforcement value in the corpus and DEBT-FLOOR would not notice.
    """
    report = MODULE.EnforcementReport(
        sources={
            "hollow": MODULE.SourceTotals(machine=3, unbacked=3),
            "real": MODULE.SourceTotals(machine=2, unbacked=1, checked=1),
        },
        phantoms=[],
        unverifiable=[],
        roots_resolved={},
        roots_unresolved={},
        mapped_sources=2,
    )

    # hollow contributes 0 (3 machine entries, all with enforcement: null);
    # real contributes exactly the 1 entry that carries a real claim.
    assert MODULE.total_enforcement_bearing(report) == 1


def test_nulling_every_enforcement_value_breaches_the_debt_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S3/M32, end-to-end: the floor must actually fire on hollowed-out entries."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # Two machine entries; the enforcement value of one was removed. Present
    # count is still 2, but only 1 unit of enforcement work remains.
    write_records(
        l1_dir,
        "sample",
        machine_record("kept", {"file": "control.py", "kind": "test"}),
        machine_record("hollowed", None),
    )

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor=2
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "DEBT-FLOOR: 1 total enforcement-bearing entries (floor 2)" in err


def test_malformed_enforcement_file_raises_and_is_not_relabelled_unbacked(
    tmp_path: Path,
) -> None:
    """S8/M34: a malformed claim is corpus corruption, not an honest gap.

    `{"enforcement": {"file": null}}` claims a mechanism and fails to name it.
    Silently counting it as `unbacked` would both skip the phantom check for
    it AND remove it from the enforcement-bearing total -- laundering a broken
    claim into "we never claimed anything".
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_records(l1_dir, "sample", {"id": "bad", "auto": "machine", "enforcement": {"file": None}})

    with pytest.raises(ValueError, match="invalid enforcement.file"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_empty_enforcement_file_string_also_raises(tmp_path: Path) -> None:
    """S8/M34, the other arm of the same condition: `"file": ""`."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_records(l1_dir, "sample", {"id": "bad", "auto": "machine", "enforcement": {"file": ""}})

    with pytest.raises(ValueError, match="invalid enforcement.file"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_require_roots_counts_roots_that_verified_something_not_roots_that_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S9/M33: the falsifiable root floor (FM-155).

    `test_require_roots_flag_raises_the_floor` has resolved == useful == 1, so
    it cannot tell the two counters apart. Here BOTH roots resolve (both
    directories are checked out) but only one of them had a single entry to
    actually check -- the other verified nothing. `--require-roots 2` must
    ERROR, because a floor satisfiable by an element that verifies nothing is
    not a floor.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo-a").mkdir(parents=True)
    (projects / "repo-a" / "control.py").touch()
    (projects / "repo-b").mkdir(parents=True)  # resolves, but checks nothing
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"a": "repo-a", "b": "repo-b"})
    write_records(l1_dir, "a", machine_record("a-1", {"file": "control.py", "kind": "test"}))
    write_records(l1_dir, "b", machine_record("b-1", None))

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, extra_args=["--require-roots", "2"]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "only 1 of 2 mapped source roots actually verified an entry" in err
    assert "phantom:" not in err


def test_load_source_roots_raises_on_a_comment_only_map(tmp_path: Path) -> None:
    """S11/M30: the loader's OWN fail-loud contract.

    `test_empty_source_roots_conf_fails_loud` asserts only on main()'s exit
    code, which the downstream zero-roots check also produces -- so it passes
    even when the loader itself has been made to return an empty map. Pin the
    loader directly.
    """
    roots_path = tmp_path / "source-roots.conf"
    roots_path.write_text("# every line is a comment\n#\n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source-roots map is empty"):
        MODULE.load_source_roots(roots_path)


def test_unrecognised_auto_value_raises_instead_of_dropping_the_record(
    tmp_path: Path,
) -> None:
    """S12/M21: a typo must not delete a record from every total.

    `"Machine"` silently skipped means the entry vanishes from machine,
    judgment, the phantom check and the debt floor alike -- a way to shrink
    the corpus without shrinking any visible counter.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    write_records(
        l1_dir,
        "sample",
        {"id": "typo", "auto": "Machine", "enforcement": {"file": "control.py"}},
    )

    with pytest.raises(ValueError, match="invalid auto value"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_blank_l1_record_raises_instead_of_being_skipped(tmp_path: Path) -> None:
    """S13/M20: a blank line in the corpus is corruption, not whitespace."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    (l1_dir / "sample.jsonl").write_text(
        json.dumps(machine_record("one", {"file": "control.py", "kind": "test"}))
        + "\n\n"
        + json.dumps(machine_record("two", {"file": "control.py", "kind": "test"}))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"blank L1 record in .*sample\.jsonl:2"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


# ---------------------------------------------------------------------------
# Round-2 survivors (briefs/survivors/guard-survivors.md S1–S10, S3–S7, S9).
# Each test was proven to PASS on unmutated code and FAIL under its named
# mutant; a test that is green in both states kills nothing.
# ---------------------------------------------------------------------------


def test_M01_ledger_entry_for_a_different_claimed_path_does_not_excuse_this_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S1/M01: PhantomEntry.key() is a 3-tuple including enforcement_file.

    A ledger row for (source, id, OLD path) must not silence a phantom that
    now claims a different path. Ignoring the third element lets anyone
    rewrite enforcement.file to a fabricated path and keep exit 0.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir, "sample", machine_record("example", {"file": "bin/NEW-phantom.sh", "kind": "test"})
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "sample",
                "id": "example",
                "claimed_path": "bin/OLD-phantom.sh",
                "evidence": "ls showed OLD path missing once",
                "disposition": "genuine-phantom: historical claim",
            }
        ],
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "undocumented" in err
    assert "bin/NEW-phantom.sh" in err


@pytest.mark.parametrize(
    "bad_line",
    [
        "this-line-has-no-colon",
        ":repo2",
        "other:",
    ],
)
def test_M04_M05_malformed_source_roots_line_is_fatal_not_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bad_line: str,
) -> None:
    """S2/M04+M05: a typo in source-roots.conf must fail loud, not drop the map.

    Skipping a malformed line demotes that source to UNVERIFIABLE and can exit
    0 while real debt disappears from the fatal path.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    # One valid mapping so an empty-map check cannot absorb the failure;
    # the malformed line is the only thing that must make the loader raise.
    roots_path.write_text(f"sample:repo\n{bad_line}\n", encoding="utf-8")
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "malformed source-roots line" in err


def test_M30_a_file_where_a_checkout_should_be_is_not_a_resolved_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S3/M30: exists-but-not-a-directory is not a resolved source root.

    A stale file (or broken checkout) must hit the resolved_count == 0 hard
    ERROR, not be counted as present and slipped into the SKIPPED (return 0)
    branch reserved for roots that exist but check nothing.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    # A regular file where the mapped checkout directory should be.
    (projects / "repo").write_text("i am a file not a directory\n", encoding="utf-8")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "0 of 1 mapped source roots" in err
    assert "SKIPPED" not in err


def test_M07_judgment_entries_cannot_prop_up_the_enforcement_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S4/M07: the floor counts machine-with-claim, never judgment.

    Judgment entries require no enforcement at all. Adding them must not
    satisfy a floor that machine-only work no longer meets.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("kept", {"file": "control.py", "kind": "test"}),
        {"id": "j1", "auto": "judgment", "enforcement": None},
        {"id": "j2", "auto": "judgment", "enforcement": None},
        {"id": "j3", "auto": "judgment", "enforcement": None},
        {"id": "j4", "auto": "judgment", "enforcement": None},
        {"id": "j5", "auto": "judgment", "enforcement": None},
    )

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor=3
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "below floor 3" in err


@pytest.mark.parametrize(
    "record",
    [
        # Missing evidence and disposition entirely.
        {
            "source": "sample",
            "id": "example",
            "claimed_path": "missing.py",
        },
        # Present but empty — still a silent allowlist entry.
        {
            "source": "sample",
            "id": "example",
            "claimed_path": "missing.py",
            "evidence": "",
            "disposition": "",
        },
    ],
)
def test_M02_M03_phantom_ledger_demands_nonempty_evidence_and_disposition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record: dict[str, str],
) -> None:
    """S5/M02 + S6/M03: evidence and disposition are the ledger's load-bearing fields.

    Without them the file is a silent allowlist, not a debt ledger.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"})
    )

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, known_phantoms=[record]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "known-phantoms" in err.lower() or "missing required field" in err.lower()


def test_M13_empty_enforcement_object_is_malformed_not_relabelled_unbacked(
    tmp_path: Path,
) -> None:
    """S7/M13: enforcement: {} claims a mechanism and fails to name it.

    Relabelling it unbacked converts a hard corpus-integrity error into a
    benign WARNING path — a broken claim becomes "we never claimed anything".
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_records(l1_dir, "sample", {"id": "bad", "auto": "machine", "enforcement": {}})

    with pytest.raises(ValueError, match="invalid enforcement.file"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_M23_multi_value_floor_file_is_fatal_not_first_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S9/M23: an ambiguous floor file must not silently adopt the first line.

    A half-resolved merge leaving two numbers can quietly weaken the gate if
    the lower value happens to come first.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    floor_path = tmp_path / "floor.conf"
    floor_path.write_text("0\n99\n", encoding="utf-8")
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor_path=floor_path
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "exactly one value" in err


def test_M24_non_object_known_phantoms_line_is_fatal_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S10/M24: a non-object JSONL line in the debt ledger is corruption.

    Silently dropping it understates the printed DEBT count and removes
    ledger-file validation for that entry.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    ledger_path = tmp_path / "known-phantoms.conf"
    ledger_path.write_text('["s","e1","bin/nope.sh"]\n', encoding="utf-8")
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, known_phantoms_path=ledger_path
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "not an object" in err


# ---------------------------------------------------------------------------
# PLAN-01 / issue #18: advisory verification must disclose what it measured
# and what it could not measure, including on the CI-shaped SKIPPED path.
# ---------------------------------------------------------------------------


def test_P01_skip_discloses_debt_unbacked_and_not_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(
        roots_path,
        {
            "sample": "repo",
            "absent-a": "not-checked-out-a",
            "absent-b": "not-checked-out-b",
        },
    )
    write_records(l1_dir, "sample", machine_record("unbacked", None))
    write_records(
        l1_dir,
        "absent-a",
        machine_record("unchecked-a", {"file": "control.py", "kind": "test"}),
    )
    write_records(
        l1_dir,
        "absent-b",
        machine_record("unchecked-b", {"file": "control.py", "kind": "test"}),
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "elsewhere",
                "id": "known-debt",
                "claimed_path": "missing.py",
                "evidence": "documented fixture debt",
                "disposition": "genuine-phantom: fixture",
            }
        ],
    )
    err = capsys.readouterr().err

    assert exit_code == 0
    assert "enforcement-verifier: PHANTOM-DEBT: 1 documented in conf/known-phantoms.conf" in err
    assert "enforcement-verifier: UNBACKED: 1 machine entries carry enforcement: null" in err
    assert "enforcement-verifier: UNVERIFIABLE: 2 machine entries could not be checked" in err
    assert (
        "enforcement-verifier: PHANTOMS-MEASURED: NOT MEASURED HERE "
        "(ROOTS 1/3, 0 entries checked)"
    ) in err
    assert "SKIPPED" in err


def test_P01_checked_run_discloses_measured_zero_not_unmeasured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("checked", {"file": "control.py", "kind": "test"}),
        machine_record("unbacked", None),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    err = capsys.readouterr().err
    assert "enforcement-verifier: PHANTOM-DEBT: 0 documented in conf/known-phantoms.conf" in err
    assert "enforcement-verifier: UNBACKED: 1 machine entries carry enforcement: null" in err
    assert "enforcement-verifier: PHANTOMS-MEASURED: 0 across 1 source roots" in err
    assert "PHANTOMS-MEASURED: NOT MEASURED HERE" not in err


def test_P01_checked_run_discloses_actual_measured_phantom_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("known-debt", {"file": "missing.py", "kind": "test"}),
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "sample",
                "id": "known-debt",
                "claimed_path": "missing.py",
                "evidence": "documented fixture debt",
                "disposition": "genuine-phantom: fixture",
            }
        ],
    )
    err = capsys.readouterr().err

    assert exit_code == 0
    assert "enforcement-verifier: PHANTOM-DEBT: 1 documented in conf/known-phantoms.conf" in err
    assert "enforcement-verifier: PHANTOMS-MEASURED: 1 across 1 source roots" in err


def test_P01_summary_distinguishes_unmeasured_from_measured_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "checked-repo").mkdir(parents=True)
    (projects / "checked-repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(
        roots_path,
        {"checked": "checked-repo", "unmeasured": "not-checked-out"},
    )
    write_records(
        l1_dir,
        "checked",
        machine_record("checked", {"file": "control.py", "kind": "test"}),
    )
    write_records(
        l1_dir,
        "unmeasured",
        machine_record("not-checked", {"file": "control.py", "kind": "test"}),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    err = capsys.readouterr().err
    assert (
        "summary (source machine judgment unbacked "
        "phantoms[-=not-measured] unverifiable checked)"
    ) in err
    assert "  checked: 1 0 0 0 0 1" in err
    assert "  unmeasured: 1 0 0 - 1 0" in err


@pytest.mark.parametrize("checked", [False, True], ids=["skipped", "checked"])
@pytest.mark.parametrize("ledger_state", ["missing", "malformed", "unreadable"])
def test_P01_all_environment_shapes_load_known_phantoms_ledger(
    ledger_state: str,
    checked: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    if checked:
        (projects / "repo" / "control.py").touch()
        write_records(
            l1_dir,
            "sample",
            machine_record("checked", {"file": "control.py", "kind": "test"}),
        )
    else:
        write_records(l1_dir, "sample", machine_record("unbacked", None))
    ledger_path = tmp_path / "known-phantoms.conf"

    if ledger_state == "malformed":
        ledger_path.write_text("{not-json}\n", encoding="utf-8")
    elif ledger_state == "unreadable":
        ledger_path.write_text("", encoding="utf-8")
        original_read_text = Path.read_text

        def deny_ledger_read(path: Path, *args: object, **kwargs: object) -> str:
            if path == ledger_path:
                raise PermissionError(13, "Permission denied", str(path))
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", deny_ledger_read)

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms_path=ledger_path,
    )
    err = capsys.readouterr().err

    assert exit_code == 1
    assert str(ledger_path) in err
    assert "known-phantoms.conf" in err
