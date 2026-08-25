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
RECONCILED_FAMILY = "dedup-identity-key"


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


def test_reconciled_released_dedup_floor_is_the_measured_two_thirds() -> None:
    """#121 records the known corpus-growth floor as exact reconciled arithmetic.

    The released partition originally fragmented to 2/3 at n=736 (a
    corpus-growth artifact past roughly 673 entries, not #118 and not a
    per-entry-quality judgment), then reclustered to 3/3 at n=762. hindsight#106's
    sync-consumer extraction (PR #177, 762->816 entries) grew the corpus again and
    fragmented it back to 2/3 -- re-measured and re-pinned here, directly
    founder-authorized (2026-08-24/25), and isolated empirically as corpus-size
    driven rather than a defect in PR #177's own content (hindsight#178 tracks the
    general floor-vs-corpus-growth policy question; not #118 and not a
    per-entry-quality regression). Keeping the numerator and denominator alongside
    the fraction prevents a rounded literal from quietly becoming a lower floor.
    """
    payload = json.loads(COMMITTED.read_text(encoding="utf-8"))
    floor = payload["reconciled_floors"]["released"][RECONCILED_FAMILY]
    assert (floor["together"], floor["members"], floor["fraction"]) == (2, 3, 0.6666666666666666)
    assert "corpus growth" in floor["cause"]
    assert "#118" in floor["cause"]
    assert payload["provenance"]["corpus_size"] == 816

    measured = MODULE.measure(["released"])["released"][RECONCILED_FAMILY]
    assert measured == {key: floor[key] for key in ("together", "members", "fraction")}


def test_update_preserves_reconciled_floors(artifact: Path) -> None:
    """A release rewrite must retain the #121 reconciliation evidence verbatim."""
    payload = json.loads(COMMITTED.read_text(encoding="utf-8"))
    artifact.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = json.dumps(payload["reconciled_floors"], sort_keys=True, separators=(",", ":")).encode()

    assert _run(artifact, "--update") == 0

    after = json.loads(artifact.read_text(encoding="utf-8"))
    assert "reconciled_floors" in after
    assert json.dumps(after["reconciled_floors"], sort_keys=True, separators=(",", ":")).encode() == before


def test_reconciled_floor_refuses_a_genuinely_degraded_staged_partition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A staged 1/3 partition must remain red below the recorded reconciled floor."""
    rows = [json.loads(line) for line in (REPO / "pipeline" / "L2" / "clusters.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    family = set(MODULE.load_families()[RECONCILED_FAMILY])
    degraded: list[dict[str, object]] = []
    for row in rows:
        if "_meta" in row:
            degraded.append(row)
            continue
        kept = [member for member in row["members"] if member not in family]
        if kept:
            degraded.append({**row, "members": kept})
    degraded.extend(
        {"cluster_id": f"degraded-{member}", "members": [member]} for member in sorted(family)
    )
    clusters = tmp_path / "clusters.jsonl"
    clusters.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in degraded) + "\n", encoding="utf-8"
    )

    before = COMMITTED.read_bytes()
    assert _run(COMMITTED, "--clusters", str(clusters)) == 1
    assert COMMITTED.read_bytes() == before
    assert "released/dedup-identity-key: 0.6667 -> 0.3333" in capsys.readouterr().err


def test_find_drops_uses_reconciled_floor_above_a_raw_baseline_drop() -> None:
    """A #121 floor replaces, rather than merely decorates, its raw baseline."""
    recorded = {
        "baselines": {"released": {"f": {"fraction": 1.0}}},
        "reconciled_floors": {"released": {"f": {"fraction": 0.6667}}},
    }
    measured = {"released": {"f": {"fraction": 0.7}}}

    assert MODULE.find_drops(recorded, measured) == []


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
