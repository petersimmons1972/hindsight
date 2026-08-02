"""Contract tests for the C4g attestation mechanism.

CI cannot check out the source repos the enforcement verifier needs, so it
cannot run the real check itself -- confirmed five separate times (C4b..C4f)
by a config edit that made a fake "nothing to check" indistinguishable from
a real one. Instead: a workstation that DOES have the source repos runs the
real check (`--write-attestation`) and, only on a genuinely clean result,
writes a signed record of what it measured, bound to a digest over every
scope-defining config input. CI (`--verify-attestation`) verifies that
record instead of faking the run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "guard" / "failure_mode_catalog_guard.py"
SPEC = importlib.util.spec_from_file_location("failure_mode_catalog_guard_attestation", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def make_scope(tmp_path: Path) -> dict[str, Path]:
    """A minimal, self-consistent scope: one mapped source, one repo root,
    one enforced entry, floors all at 0/1 so a single checked entry clears
    them, no known phantoms."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    (projects / "repo" / "control.py").touch()

    source_roots_path = tmp_path / "source-roots.conf"
    _write(source_roots_path, "sample:repo\n")

    unmapped_sources_path = tmp_path / "unmapped-sources.conf"
    _write(unmapped_sources_path, "")

    enforcement_floor_path = tmp_path / "enforcement-floor.conf"
    _write(enforcement_floor_path, "0\n")

    mapped_sources_floor_path = tmp_path / "mapped-sources-floor.conf"
    _write(mapped_sources_floor_path, "0\n")

    checked_floor_path = tmp_path / "checked-floor.conf"
    _write(checked_floor_path, "0\n")

    known_phantoms_path = tmp_path / "known-phantoms.conf"
    _write(known_phantoms_path, "")

    _write(
        l1_dir / "sample.jsonl",
        json.dumps(
            {"id": "e1", "auto": "machine", "enforcement": {"file": "control.py", "kind": "test"}}
        )
        + "\n",
    )

    return {
        "l1_dir": l1_dir,
        "projects": projects,
        "source_roots_path": source_roots_path,
        "unmapped_sources_path": unmapped_sources_path,
        "enforcement_floor_path": enforcement_floor_path,
        "mapped_sources_floor_path": mapped_sources_floor_path,
        "checked_floor_path": checked_floor_path,
        "known_phantoms_path": known_phantoms_path,
    }


def patch_scope(monkeypatch: pytest.MonkeyPatch, scope: dict[str, Path]) -> None:
    monkeypatch.setattr(MODULE, "default_l1_dir", lambda: scope["l1_dir"])
    monkeypatch.setattr(MODULE, "default_projects_dir", lambda: scope["projects"])
    monkeypatch.setattr(MODULE, "default_source_roots_path", lambda: scope["source_roots_path"])
    monkeypatch.setattr(
        MODULE, "default_unmapped_sources_path", lambda: scope["unmapped_sources_path"]
    )
    monkeypatch.setattr(
        MODULE, "default_enforcement_floor_path", lambda: scope["enforcement_floor_path"]
    )
    monkeypatch.setattr(
        MODULE, "default_mapped_sources_floor_path", lambda: scope["mapped_sources_floor_path"]
    )
    monkeypatch.setattr(MODULE, "default_checked_floor_path", lambda: scope["checked_floor_path"])
    monkeypatch.setattr(
        MODULE, "default_known_phantoms_path", lambda: scope["known_phantoms_path"]
    )
    # These fixture floor files live outside the real git repo, so the real
    # previous_floor_value() would always return None (indeterminate) and
    # check_floor_ratchet would hard-fail every run on that alone -- same
    # permissive-stub idiom test_verify_enforcement.py uses.
    monkeypatch.setattr(MODULE, "previous_floor_value", lambda path, ref: 0)


# ---------------------------------------------------------------------------
# compute_config_digest: pure hash-over-bytes behavior.
# ---------------------------------------------------------------------------


def test_digest_is_stable_for_identical_bytes(tmp_path: Path) -> None:
    scope = make_scope(tmp_path)
    d1 = MODULE.compute_config_digest(
        scope["l1_dir"],
        scope["source_roots_path"],
        scope["unmapped_sources_path"],
        scope["enforcement_floor_path"],
        scope["mapped_sources_floor_path"],
        scope["checked_floor_path"],
        scope["known_phantoms_path"],
    )
    d2 = MODULE.compute_config_digest(
        scope["l1_dir"],
        scope["source_roots_path"],
        scope["unmapped_sources_path"],
        scope["enforcement_floor_path"],
        scope["mapped_sources_floor_path"],
        scope["checked_floor_path"],
        scope["known_phantoms_path"],
    )
    assert d1 == d2
    assert d1.startswith("sha256:")


def test_digest_changes_when_source_roots_changes(tmp_path: Path) -> None:
    scope = make_scope(tmp_path)
    before = MODULE.compute_config_digest(
        scope["l1_dir"],
        scope["source_roots_path"],
        scope["unmapped_sources_path"],
        scope["enforcement_floor_path"],
        scope["mapped_sources_floor_path"],
        scope["checked_floor_path"],
        scope["known_phantoms_path"],
    )
    # The C4g one-file decoy-roots attack: repoint a mapped root to a
    # nonexistent directory.
    _write(scope["source_roots_path"], "sample:decoy-nonexistent\n")
    after = MODULE.compute_config_digest(
        scope["l1_dir"],
        scope["source_roots_path"],
        scope["unmapped_sources_path"],
        scope["enforcement_floor_path"],
        scope["mapped_sources_floor_path"],
        scope["checked_floor_path"],
        scope["known_phantoms_path"],
    )
    assert before != after


def test_digest_changes_when_an_l1_jsonl_changes(tmp_path: Path) -> None:
    scope = make_scope(tmp_path)
    before = MODULE.compute_config_digest(
        scope["l1_dir"],
        scope["source_roots_path"],
        scope["unmapped_sources_path"],
        scope["enforcement_floor_path"],
        scope["mapped_sources_floor_path"],
        scope["checked_floor_path"],
        scope["known_phantoms_path"],
    )
    with (scope["l1_dir"] / "sample.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"id": "e2", "auto": "machine", "enforcement": {"file": "control.py"}})
            + "\n"
        )
    after = MODULE.compute_config_digest(
        scope["l1_dir"],
        scope["source_roots_path"],
        scope["unmapped_sources_path"],
        scope["enforcement_floor_path"],
        scope["mapped_sources_floor_path"],
        scope["checked_floor_path"],
        scope["known_phantoms_path"],
    )
    assert before != after


def test_digest_raises_on_missing_required_file(tmp_path: Path) -> None:
    scope = make_scope(tmp_path)
    scope["known_phantoms_path"].unlink()
    with pytest.raises(ValueError, match="required scope input missing"):
        MODULE.compute_config_digest(
            scope["l1_dir"],
            scope["source_roots_path"],
            scope["unmapped_sources_path"],
            scope["enforcement_floor_path"],
            scope["mapped_sources_floor_path"],
            scope["checked_floor_path"],
            scope["known_phantoms_path"],
        )


# ---------------------------------------------------------------------------
# write_attestation: refuses on anything but a genuinely clean real run.
# ---------------------------------------------------------------------------


def _args(**overrides: object) -> object:
    class Args:
        pass

    a = Args()
    a.require_roots = 1
    a.accept_phantom = False
    a.allow_floor_decrease = []
    a.ci_no_source_repos = False
    for key, value in overrides.items():
        setattr(a, key, value)
    return a


def test_write_attestation_refuses_with_ci_no_source_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    monkeypatch.setattr(MODULE, "default_attestation_path", lambda: attestation_path)

    exit_code = MODULE.write_attestation(_args(ci_no_source_repos=True))
    assert exit_code == 1
    assert not attestation_path.exists()
    assert "cannot be combined with --ci-no-source-repos" in capsys.readouterr().err


def test_write_attestation_refuses_when_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    # An empty L1 corpus (no machine entries with enforcement) -> SKIPPED.
    (scope["l1_dir"] / "sample.jsonl").write_text("", encoding="utf-8")
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    monkeypatch.setattr(MODULE, "default_attestation_path", lambda: attestation_path)

    exit_code = MODULE.write_attestation(_args())
    assert exit_code == 1
    assert not attestation_path.exists()
    assert "verified nothing" in capsys.readouterr().err


def test_write_attestation_refuses_with_undocumented_phantom_even_under_accept_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    # Point the entry at a file that does not exist -> phantom, undocumented.
    _write(
        scope["l1_dir"] / "sample.jsonl",
        json.dumps(
            {"id": "e1", "auto": "machine", "enforcement": {"file": "missing.py", "kind": "test"}}
        )
        + "\n",
    )
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    monkeypatch.setattr(MODULE, "default_attestation_path", lambda: attestation_path)

    exit_code = MODULE.write_attestation(_args(accept_phantom=True))
    assert exit_code == 1
    assert not attestation_path.exists()
    assert "undocumented phantom" in capsys.readouterr().err


def test_write_attestation_succeeds_on_a_clean_run_and_records_measured_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    monkeypatch.setattr(MODULE, "default_attestation_path", lambda: attestation_path)
    monkeypatch.setattr(MODULE, "_current_commit", lambda repo_root: "deadbeef")

    exit_code = MODULE.write_attestation(_args())
    assert exit_code == 0
    payload = json.loads(attestation_path.read_text(encoding="utf-8"))
    assert payload["commit"] == "deadbeef"
    assert payload["results"]["total_checked"] == 1
    assert payload["results"]["mapped_sources"] == 1
    assert payload["results"]["unlisted_phantom_count"] == 0
    assert payload["config_digest"].startswith("sha256:")


# ---------------------------------------------------------------------------
# verify_attestation: the CI-side mutation bar (workstation-shape equivalents
# of the five required mutations from the C4g spec).
# ---------------------------------------------------------------------------


def _write_clean_attestation(
    monkeypatch: pytest.MonkeyPatch, scope: dict[str, Path], attestation_path: Path
) -> dict[str, object]:
    monkeypatch.setattr(MODULE, "default_attestation_path", lambda: attestation_path)
    monkeypatch.setattr(MODULE, "_current_commit", lambda repo_root: "deadbeef")
    assert MODULE.write_attestation(_args()) == 0
    return json.loads(attestation_path.read_text(encoding="utf-8"))


def test_verify_attestation_fails_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    monkeypatch.setattr(MODULE, "default_attestation_path", lambda: attestation_path)

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 1
    assert "no attestation at" in capsys.readouterr().err


def test_verify_attestation_fails_on_digest_mismatch_after_decoy_roots_attack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    _write_clean_attestation(monkeypatch, scope, attestation_path)

    # C4g mutation (a): the one-file decoy-roots attack.
    _write(scope["source_roots_path"], "sample:decoy-nonexistent\n")

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 1
    assert "config_digest MISMATCH" in capsys.readouterr().err


def test_verify_attestation_fails_when_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    _write_clean_attestation(monkeypatch, scope, attestation_path)

    # C4g mutation (b).
    attestation_path.unlink()

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 1
    assert "no attestation at" in capsys.readouterr().err


def test_verify_attestation_fails_when_backdated_past_max_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    payload = _write_clean_attestation(monkeypatch, scope, attestation_path)

    # C4g mutation (c).
    payload["generated_at"] = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    attestation_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 1
    assert "past the 14-day max age" in capsys.readouterr().err


def test_verify_attestation_fails_when_scope_config_edited_without_regenerating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    _write_clean_attestation(monkeypatch, scope, attestation_path)

    # C4g mutation (d): edit known-phantoms.conf (a scope file) without
    # regenerating the attestation.
    _write(
        scope["known_phantoms_path"],
        json.dumps(
            {
                "source": "sample",
                "id": "e1",
                "claimed_path": "missing.py",
                "evidence": "manual",
                "disposition": "debt",
            }
        )
        + "\n",
    )

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 1
    assert "config_digest MISMATCH" in capsys.readouterr().err


def test_verify_attestation_fails_when_recorded_checked_count_forged_below_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    # Set a checked-floor of 1 so the real run just barely clears it, then
    # forge the attestation DOWN to 0 without touching any config byte.
    _write(scope["checked_floor_path"], "1\n")
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    payload = _write_clean_attestation(monkeypatch, scope, attestation_path)
    assert payload["results"]["total_checked"] == 1  # sanity: real run was clean

    # C4g mutation (e): hand-edit the attestation's own recorded results,
    # config_digest untouched (no config file byte changed).
    payload["results"]["total_checked"] = 0
    attestation_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "recorded total_checked 0 below checked-floor 1" in err


def test_verify_attestation_fails_when_recorded_unlisted_phantom_count_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    payload = _write_clean_attestation(monkeypatch, scope, attestation_path)

    # Same class as mutation (e): forge a nonzero undocumented-phantom count
    # directly into the results without touching config_digest's inputs.
    payload["results"]["unlisted_phantom_count"] = 3
    attestation_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 1
    assert "undocumented phantom(s) not in the ledger" in capsys.readouterr().err


def test_verify_attestation_succeeds_on_a_clean_matching_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = make_scope(tmp_path)
    patch_scope(monkeypatch, scope)
    attestation_path = tmp_path / "attestation.json"
    _write_clean_attestation(monkeypatch, scope, attestation_path)

    exit_code = MODULE.verify_attestation(_args(max_attestation_age_days=14))
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "digest MATCHES current config" in err
    assert "0 undocumented phantoms" in err
