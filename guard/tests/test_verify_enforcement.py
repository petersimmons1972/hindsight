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


def write_unmapped_sources(path: Path, records: list[dict[str, str]]) -> None:
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


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
    mapped_sources_floor: int | str | None = None,
    mapped_sources_floor_path: Path | None = None,
    checked_floor: int | str | None = None,
    checked_floor_path: Path | None = None,
    unmapped_sources: list[dict[str, str]] | None = None,
    unmapped_sources_path: Path | None = None,
) -> int:
    """Drive main() with every default sandboxed to tmp_path.

    known_phantoms / enforcement_floor / mapped_sources_floor / checked_floor
    / unmapped_sources all default to permissive, no-op values (an empty
    ledger, floor 0, no declarations) so tests that don't care about a given
    gate aren't affected by it -- pass the matching *_path parameter
    (pointing at a file you never created, or deliberately malformed) to
    exercise that gate's own "fails loud" behavior instead.
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

    if mapped_sources_floor_path is None:
        mapped_sources_floor_path = l1_dir.parent / "mapped-sources-floor.conf"
        write_enforcement_floor(
            mapped_sources_floor_path, 0 if mapped_sources_floor is None else mapped_sources_floor
        )
    monkeypatch.setattr(MODULE, "default_mapped_sources_floor_path", lambda: mapped_sources_floor_path)

    if checked_floor_path is None:
        checked_floor_path = l1_dir.parent / "checked-floor.conf"
        write_enforcement_floor(checked_floor_path, 0 if checked_floor is None else checked_floor)
    monkeypatch.setattr(MODULE, "default_checked_floor_path", lambda: checked_floor_path)

    if unmapped_sources_path is None:
        unmapped_sources_path = l1_dir.parent / "unmapped-sources.conf"
        write_unmapped_sources(unmapped_sources_path, unmapped_sources or [])
    monkeypatch.setattr(MODULE, "default_unmapped_sources_path", lambda: unmapped_sources_path)

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
    # "orphan" has NO entry in source-roots.conf at all -- declared unmappable
    # instead, since C4d requires every L1 source to be one or the other.
    write_records(
        l1_dir, "orphan", machine_record("orphan-1", {"file": "control.py", "kind": "test"})
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        unmapped_sources=[{"source": "orphan", "reason": "test fixture: deliberately never mapped"}],
    )
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
    # C4d D6: "error" in err.lower() alone is decorative -- satisfiable by any
    # error path whatsoever. Pin the exact rendered line for THIS gate.
    assert "0 of 1 mapped source roots are present on this machine at all" in err


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
    # C4d D6: pin the exact rendered line, not a bare "error" substring.
    assert (
        "only 1 of 2 mapped source roots actually verified an entry on this machine "
        "(require >= 2)" in err
    )


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
    # C4d D6: this test's NAME claims it tests the empty-map guard
    # specifically, but previously asserted nothing that could only be
    # satisfied by THAT guard -- a different, later guard (zero-roots-
    # resolved) could supply the nonzero exit instead and this would still
    # pass. Pin the exact message load_source_roots raises for an empty map.
    assert "source-roots map is empty" in err


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
    """Runs against the REAL, uncontrolled repo corpus/config -- so the exit
    code is legitimately environment-dependent (a workstation with all
    source repos checked out behaves differently than CI). What must hold
    in EVERY environment: every config-integrity gate ran and printed its
    line, and the exit code is internally consistent with whether an ERROR
    was ever printed -- not just "0 or 1", which is satisfiable by a stub
    that always returns 1 regardless of what (if anything) it checked.
    """
    exit_code = MODULE.main(["--verify-enforcement"])
    output = capsys.readouterr().err
    assert exit_code in {0, 1}
    assert (
        "enforcement-verifier: summary (source machine judgment unbacked phantoms "
        "unverifiable checked)" in output
    )
    assert "enforcement-verifier: MAPPED-SOURCES-FLOOR:" in output
    assert "enforcement-verifier: DEBT-FLOOR:" in output
    assert "enforcement-verifier: ROOTS:" in output
    has_error = "enforcement-verifier: ERROR:" in output
    if exit_code == 0:
        assert not has_error
    else:
        assert has_error or any(
            line.startswith("enforcement-verifier: undocumented:") for line in output.splitlines()
        )


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


# ---------------------------------------------------------------------------
# C4d D1: the map that decides what gets checked must itself be gated. A
# shrinking conf/source-roots.conf must FAIL, not silently improve the ROOTS
# ratio by shrinking its own denominator.
# ---------------------------------------------------------------------------


def test_mapped_sources_floor_dropping_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    # Only 1 source mapped this run...
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    # ...but the floor says there used to be 13 -- as if 12 lines were
    # deleted from source-roots.conf. Must fail loud, even though nothing
    # here is phantom and the (empty-denominator) ROOTS ratio would read
    # 1/1 = "100%".
    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, mapped_sources_floor=13)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "mapped source count dropped to 1, below floor 13" in err


def test_mapped_sources_floor_at_or_above_is_fine(
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

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, mapped_sources_floor=1)
    assert exit_code == 0


def test_reducing_source_roots_conf_to_a_single_entry_still_fails_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The literal repro: `printf 'fleet-dispatch-schema:.\\n' > conf/source-roots.conf`
    reduced a real multi-line map to one entry, and the (unfloored) ROOTS
    ratio read 1/1 = 100% with all 15 real phantoms vanished. Reproduced here
    structurally: a map that used to have several mapped sources, reduced to
    one, must fail the floor regardless of what that one entry says."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "only-repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"only": "only-repo"})
    write_records(l1_dir, "only", machine_record("only-1", None))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, mapped_sources_floor=5)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "mapped source count dropped to 1, below floor 5" in err


def test_missing_mapped_sources_floor_file_fails_loud(
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
        mapped_sources_floor_path=tmp_path / "does-not-exist-mapped-floor.conf",
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "mapped-sources floor file not found" in err.lower()


# ---------------------------------------------------------------------------
# C4d D3: a root of "." (or an ancestor of another mapped root) is forbidden
# at config-VALIDATION time, before any path on disk is even looked at --
# it reopens the cross-repo leak this whole file exists to close (a
# substack/README.md entry would resolve as "enforced" for another source).
# ---------------------------------------------------------------------------


def test_root_of_dot_is_rejected_at_config_validation_time_before_any_path_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    # A file that exists ANYWHERE under projects_dir but not under any real
    # per-repo root -- if "." were allowed, this would resolve as enforced.
    (projects / "unrelated-repo").mkdir(parents=True)
    (projects / "unrelated-repo" / "README.md").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "."})
    write_records(
        l1_dir, "sample", machine_record("leak", {"file": "unrelated-repo/README.md", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    # Rejected as a config error -- never even reaches phantom detection, so
    # the leaked "enforced" entry must never appear as silently accepted.
    assert "phantom:" not in err
    assert "unrelated-repo/README.md" not in err
    assert "maps to '.'" in err
    assert "forbidden" in err.lower()


def test_normal_repo_scoped_roots_still_pass_the_dot_check(
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


def test_root_that_is_ancestor_of_another_mapped_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "parent" / "child").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    # "outer" maps to "parent", "inner" maps to "parent/child" -- outer's
    # entries could resolve against inner's files too. Forbidden.
    write_source_roots(roots_path, {"outer": "parent", "inner": "parent/child"})
    write_records(l1_dir, "outer", machine_record("o-1", None))
    write_records(l1_dir, "inner", machine_record("i-1", None))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "is an ancestor of" in err


# ---------------------------------------------------------------------------
# C4d D2: every L1 source must be mapped, or explicitly declared unmappable
# with a reason -- an unmapped, undeclared source used to be a free pass.
# ---------------------------------------------------------------------------


def test_unmapped_undeclared_source_fails_loud(
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
    # "orphan" carries a fabricated enforcement claim, mapped nowhere and
    # declared nowhere -- exactly D2's reproduction.
    write_records(
        l1_dir, "orphan", machine_record("fake", {"file": "bin/totally-made-up-gate.sh", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "L1 source 'orphan' has no root mapping" in err
    assert "not declared unmappable" in err


def test_declared_unmappable_source_passes_coverage_but_stays_unverifiable(
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
    write_records(
        l1_dir, "orphan", machine_record("fake", {"file": "bin/totally-made-up-gate.sh", "kind": "test"})
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        unmapped_sources=[{"source": "orphan", "reason": "test fixture: straddles two repos"}],
    )
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "phantom:" not in err  # never checked, so never flagged as phantom either
    assert "unverifiable: bin/totally-made-up-gate.sh (orphan:fake," in err


def test_mapped_and_declared_unmappable_is_contradictory_and_rejected(
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
        unmapped_sources=[{"source": "sample", "reason": "contradicts the mapping above"}],
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "BOTH mapped" in err


# ---------------------------------------------------------------------------
# C4d D2 (the exploit itself, mutation-bar item d): a floor on entries
# actually CHECKED, not merely present as an enforcement-bearing claim.
# Padding a declared-unmappable source with a new fabricated claim raises
# the (root-independent) enforcement-bearing floor's headroom, but must NOT
# be able to mask a genuinely checked entry disappearing elsewhere.
# ---------------------------------------------------------------------------


def test_checked_floor_dropping_is_an_error_even_though_bearing_floor_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # Only ONE checked entry survives this run (the deletion of a second,
    # previously-checked entry is simulated by the floor value below)...
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))
    # ...but pad an unmapped, declared-unmappable source with a brand-new
    # fabricated enforcement claim. This raises the root-independent
    # enforcement-bearing total (still satisfied against its own floor of 1
    # below) without ever being checked -- exactly D2's exploit.
    write_records(
        l1_dir, "orphan", machine_record("fake", {"file": "bin/totally-made-up-gate.sh", "kind": "test"})
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        unmapped_sources=[{"source": "orphan", "reason": "test fixture"}],
        enforcement_floor=1,  # bearing floor: 1 (sample) + 1 (orphan, padded) = 2, satisfied
        checked_floor=2,  # but only 1 entry was actually CHECKED -- must fail
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "checked entry count dropped to 1, below floor 2" in err
    # The bearing floor must NOT be why this failed -- it's the padding
    # exploit that this floor exists to close, not a coarser gate re-catching it.
    assert "enforcement-bearing entry count dropped" not in err


def test_checked_floor_at_or_above_is_fine(
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

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, checked_floor=1)
    assert exit_code == 0


def test_checked_floor_is_not_consulted_in_the_skip_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An environment that structurally cannot check anything (checked == 0
    everywhere) must take the declared SKIP path, not be penalized by the
    checked floor -- that floor only applies "wherever roots resolve"."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)  # root resolves...
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))  # ...but unbacked, checked=0

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, checked_floor=99)
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "SKIPPED" in err
    assert "checked entry count dropped" not in err


def test_missing_checked_floor_file_fails_loud(
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
        checked_floor_path=tmp_path / "does-not-exist-checked-floor.conf",
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "checked floor file not found" in err.lower()


# ---------------------------------------------------------------------------
# C4d D4: the phantom ledger (and every other config input) must be
# validated in EVERY environment, including one that structurally cannot
# check anything -- not only on the "happy path" where roots resolve. The
# original defect: known-phantoms.conf's load happened AFTER the SKIPPED
# return, so deleting it on a CI-like runner (no source repos checked out)
# was invisible.
# ---------------------------------------------------------------------------


def test_missing_known_phantoms_ledger_fails_loud_even_in_the_ci_skip_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)  # root resolves ("SELF"-like)...
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # ...but every entry is unbacked, so nothing is ever actually checked --
    # this IS the CI-with-no-source-repos shape (useful_count == 0, SKIPPED).
    write_records(l1_dir, "sample", machine_record("example", None))

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms_path=tmp_path / "does-not-exist-ledger-ci.conf",
    )
    err = capsys.readouterr().err
    # Must fail BEFORE ever reaching (or printing) the SKIPPED declaration --
    # a vanished ledger is a config-integrity defect, not a "nothing to
    # check here" environment, and the two must not be conflated.
    assert exit_code != 0
    assert "known-phantoms ledger not found" in err.lower()
    assert "SKIPPED" not in err


def test_known_phantoms_ledger_present_still_allows_the_skip_state_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "SKIPPED" in err


# ---------------------------------------------------------------------------
# C4c D5 (test-coverage gaps carried into C4d): three of the five surviving
# mutations pinned with discriminating tests. M8 is closed by the tightened
# assertion on test_empty_source_roots_conf_fails_loud above. M13
# (--require-roots default 1->0) is judged NOT worth a synthetic test: given
# the code structure, useful_count == 0 always takes the SKIPPED return
# (exit 0) BEFORE args.require_roots is ever consulted, so useful_count is
# always >= 1 by the time the require_roots comparison runs -- "1 < 1" and
# "1 < 0" are both False, identically, for every useful_count >= 1. The
# default is only ever observable when raised above 1 via the flag, which
# the existing test_require_roots_flag_raises_the_floor already exercises
# directly. No environment exists in which the bare default value 0 vs 1
# changes an outcome; it is an equivalent mutant given the current control
# flow, same class as the "totals.checked incremented early" case the C4c
# review already reported as equivalent rather than papering over with a
# test that can't fail for the right reason.
# ---------------------------------------------------------------------------


def test_enforcement_bearing_floor_excludes_unbacked_entries_mutation_M5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """M5: `total_enforcement_bearing` must be machine MINUS unbacked, not
    machine alone. A regression that drops the "- unbacked" subtraction
    would count every unbacked (enforcement: null) entry as if it were
    enforcement-bearing too, silently raising the floor's headroom and
    defeating the fleet#152 defense with entries that carry no claim at
    all."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # 1 real enforcement-bearing entry, 1 unbacked (null) entry: machine=2,
    # unbacked=1, so the CORRECT bearing total is 2-1=1, not 2.
    write_records(
        l1_dir,
        "sample",
        machine_record("real", {"file": "control.py", "kind": "test"}),
        machine_record("unbacked", None),
    )

    # Floor demands 2. The correct (machine - unbacked = 1) total must fail;
    # only the buggy (machine = 2) total would pass.
    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, enforcement_floor=2)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "dropped to 1, below floor 2" in err


def test_enforcement_file_escaping_via_dotdot_is_phantom_even_if_target_exists_mutation_M7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """M7: dropping `not resolved.is_relative_to(source_root) or` from the
    phantom condition would let a path escape its own source's root via
    `..` and still count as enforced, AS LONG AS the escaped target exists
    somewhere. test_path_existing_in_a_different_repo_is_still_phantom does
    not pin this: there, the target under sample's OWN root doesn't exist
    either, so resolved.exists() alone already fails it, and the
    containment half of the check is never actually exercised. Here the
    escaped target genuinely exists, so only `is_relative_to` catches it."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "sample-repo").mkdir(parents=True)
    (projects / "sibling-repo").mkdir(parents=True)
    (projects / "sibling-repo" / "control.py").touch()  # the escaped target genuinely EXISTS
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "sample-repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("escape", {"file": "../sibling-repo/control.py", "kind": "test"}),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    err = capsys.readouterr().err
    assert "phantom: ../sibling-repo/control.py (sample:escape," in err


def test_known_phantoms_missing_required_field_fails_loud_mutation_M9(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """M9: deleting the required-field validation loop in
    load_known_phantoms would let a malformed ledger line (missing
    "evidence", say) load silently as a partial record, defeating the
    documented contract that every debt entry carries evidence and a
    disposition."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"}))

    known_path = tmp_path / "malformed-known-phantoms.conf"
    known_path.write_text(
        json.dumps(
            {"source": "sample", "id": "example", "claimed_path": "missing.py"}
        )  # missing "evidence" and "disposition"
        + "\n",
        encoding="utf-8",
    )

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, known_phantoms_path=known_path
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "missing required field" in err.lower()
    assert "evidence" in err.lower()


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
