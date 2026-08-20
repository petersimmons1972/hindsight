"""The recall-baseline ratchet must refuse a drop, and record an accepted one.

Founder ruling 2026-08-19 (hindsight#121) replaced the absolute 0.75 recall floor
with a recorded per-(family, backend) baseline. That trade is only safe if the
"fail loudly on a drop" half is real: a ratchet that silently re-records a lower
number is strictly WORSE than the absolute floor it replaced, because it launders
regressions under a green suite while looking like a gate.

So these tests attack that half specifically. Each one plants a baseline HIGHER
than the corpus can currently deliver -- the shape of a genuine regression -- and
asserts the tool refuses, writes nothing, and only relents when handed an
explicit override plus a reason that ends up recorded in the artifact.

Everything here runs against the cheap `released` backend (the committed
clusters.jsonl partition) in a tmp_path copy: no live embedding, no writes to the
real artifact.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "pipeline" / "recall_baselines.py"
SPEC = importlib.util.spec_from_file_location("hindsight_recall_baselines_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

COMMITTED = REPO / "pipeline" / "L2" / "recall-baselines.json"
FAMILY = "shared-mutable-checkout"


@pytest.fixture()
def artifact(tmp_path: Path) -> Path:
    """A copy of the committed artifact, with one family planted unreachably high."""
    payload = json.loads(COMMITTED.read_text(encoding="utf-8"))
    payload["baselines"]["released"][FAMILY] = {
        "together": 7, "members": 7, "fraction": 1.0,
    }
    path = tmp_path / "recall-baselines.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _run(artifact: Path, *extra: str) -> int:
    return MODULE.main(["--artifact", str(artifact), "--backend", "released", *extra])


def test_committed_artifact_matches_the_committed_partition() -> None:
    """The recorded `released` baselines must describe the clusters.jsonl in tree.

    Without this the artifact could drift into fiction and every other assertion
    in this file would be checking a number nobody measures.
    """
    assert _run(COMMITTED) == 0


def test_verify_refuses_when_current_recall_is_below_the_recorded_baseline(
    artifact: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plain verify: non-zero exit, and the drop is named in stderr."""
    before = artifact.read_bytes()
    assert _run(artifact) == 1
    assert artifact.read_bytes() == before, "a refused verify must not rewrite the artifact"
    err = capsys.readouterr().err
    assert "REFUSED" in err and FAMILY in err and "--allow-drop" in err


def test_update_refuses_a_drop_and_writes_nothing_without_the_override(
    artifact: Path,
) -> None:
    """The release path itself must not re-record a lower number by default.

    This is the assertion that makes the ratchet a ratchet. If it ever goes red,
    the baseline file has become a log of whatever happened rather than a floor.
    """
    before = artifact.read_bytes()
    assert _run(artifact, "--update") == 1
    assert artifact.read_bytes() == before


def test_override_requires_a_non_empty_reason(artifact: Path) -> None:
    """`--allow-drop` alone is not an argument for accepting a regression."""
    before = artifact.read_bytes()
    assert _run(artifact, "--update", "--allow-drop") == 2
    assert _run(artifact, "--update", "--allow-drop", "--reason", "   ") == 2
    assert artifact.read_bytes() == before


def test_override_is_only_meaningful_with_update(artifact: Path) -> None:
    """A verify-mode `--allow-drop` would be a silent waiver; refuse it outright."""
    assert _run(artifact, "--allow-drop", "--reason", "why") == 2


def test_override_accepts_the_drop_and_records_the_reason(artifact: Path) -> None:
    """With the flag AND a reason, the drop lands -- and stays visible forever."""
    reason = "measured corpus growth, re-baselined under the 2026-08-19 ruling"
    assert _run(artifact, "--update", "--allow-drop", "--reason", reason) == 0

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["baselines"]["released"][FAMILY]["fraction"] < 1.0
    overrides = payload["overrides"]
    assert overrides, "an accepted drop must leave an override record behind"
    latest = overrides[-1]
    assert latest["reason"] == reason
    accepted = {(row["backend"], row["family"]) for row in latest["accepted"]}
    assert ("released", FAMILY) in accepted

    # And the ratchet re-arms at the new value: a second plain verify passes,
    # but the recorded reason is not consumed or overwritten by it.
    assert _run(artifact) == 0
    assert json.loads(artifact.read_text(encoding="utf-8"))["overrides"] == overrides


def test_a_missing_member_counts_against_the_family() -> None:
    """A member absent from the partition must not be able to raise recall.

    Guards the sentinel in `recall_from_assignments`: if absent members were
    dropped instead, deleting records would look like a recall improvement.
    """
    families = {"f": ["a", "b", "c", "d"]}
    both_present = MODULE.recall_from_assignments({m: "c-1" for m in families["f"]}, families)
    two_missing = MODULE.recall_from_assignments({"a": "c-1", "b": "c-1"}, families)
    assert both_present["f"]["fraction"] == 1.0
    assert two_missing["f"]["together"] == 2
    assert two_missing["f"]["fraction"] == 0.5


def test_an_unmeasured_backend_is_never_treated_as_a_drop() -> None:
    """An unreachable HTTP backend must not launder a regression by silence.

    Not measuring is not the same as measuring zero: `find_drops` reports only
    on rows it actually observed, and `_merge_baselines` leaves the untouched
    rows in place rather than resetting them.
    """
    recorded = {"baselines": {"http": {"f": {"fraction": 0.9, "together": 9, "members": 10}}}}
    assert MODULE.find_drops(recorded, {}) == []
    merged = MODULE._merge_baselines(recorded, {"tfidf": {"f": {"fraction": 0.5}}})
    assert merged["http"]["f"]["fraction"] == 0.9
    assert merged["tfidf"]["f"]["fraction"] == 0.5
