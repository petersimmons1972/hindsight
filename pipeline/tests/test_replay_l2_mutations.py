"""Mutation evidence for deterministic, network-free replay of committed L2."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"
L1 = PIPELINE / "L1"
SNAPSHOT = PIPELINE / "L2" / "embedding-snapshot.json"
CLUSTERS = PIPELINE / "L2" / "clusters.jsonl"
CLUSTER_CODE = PIPELINE / "cluster.py"
ORIGINALS = (*sorted(L1.glob("*.jsonl")), SNAPSHOT, CLUSTERS, CLUSTER_CODE)

REPLAY_SPEC = importlib.util.spec_from_file_location(
    "hindsight_replay_l2_mutations", PIPELINE / "replay_l2.py"
)
assert REPLAY_SPEC and REPLAY_SPEC.loader
REPLAY = importlib.util.module_from_spec(REPLAY_SPEC)
sys.modules[REPLAY_SPEC.name] = REPLAY
REPLAY_SPEC.loader.exec_module(REPLAY)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def replay_case(tmp_path: Path) -> tuple[dict[str, Path], dict[Path, str]]:
    """Copy every mutable replay input and retain repository integrity evidence."""
    before = {path: _digest(path) for path in ORIGINALS}
    copied_l1 = shutil.copytree(L1, tmp_path / "L1")
    case = {
        "l1": copied_l1,
        "snapshot": Path(shutil.copy2(SNAPSHOT, tmp_path / "embedding-snapshot.json")),
        "clusters": Path(shutil.copy2(CLUSTERS, tmp_path / "clusters.jsonl")),
        "code": Path(shutil.copy2(CLUSTER_CODE, tmp_path / "cluster.py")),
    }
    yield case, before
    assert {path: _digest(path) for path in ORIGINALS} == before


def _run(case: dict[str, Path]) -> int:
    return REPLAY.main(
        [
            "--input-dir", str(case["l1"]),
            "--snapshot", str(case["snapshot"]),
            "--clusters", str(case["clusters"]),
            "--cluster-code", str(case["code"]),
        ]
    )


def _assert_originals(before: dict[Path, str]) -> None:
    assert {path: _digest(path) for path in ORIGINALS} == before


def test_l1_source_digest_mutation_fails_loudly(replay_case, capsys) -> None:
    case, before = replay_case
    record_path = case["l1"] / "claude-codex-integration.jsonl"
    original = record_path.read_bytes()
    marker = b'"instance":"C'
    assert original.count(marker) >= 1
    mutated = original.replace(marker, b'"instance":"D', 1)
    assert len(mutated) == len(original)
    old_record = json.loads(original.splitlines()[0])
    new_record = json.loads(mutated.splitlines()[0])
    assert old_record["id"] == new_record["id"]
    assert old_record.keys() == new_record.keys()
    record_path.write_bytes(mutated)

    assert _run(case) == 1
    assert "replay-l2: error: L1 digest mismatch:" in capsys.readouterr().err
    _assert_originals(before)


def test_committed_l2_member_move_reports_partition_and_id(replay_case, capsys) -> None:
    case, before = replay_case
    rows = [json.loads(line) for line in case["clusters"].read_text().splitlines()]
    source = next(row for row in rows[1:] if "dm-14" in row["members"])
    target = next(row for row in rows[1:] if "ccx-FM-002" in row["members"])
    source["members"].remove("dm-14")
    source["size"] = len(source["members"])
    target["members"].append("dm-14")
    target["members"].sort()
    target["size"] = len(target["members"])
    target["source_repos"] = sorted({*target["source_repos"], "duramind"})
    assert sum("dm-14" in row.get("members", []) for row in rows[1:]) == 1
    case["clusters"].write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    assert _run(case) == 1
    error = capsys.readouterr().err
    assert error.startswith("replay-l2: error: partition mismatch: expected-only=")
    assert "'dm-14'" in error
    _assert_originals(before)


def test_vector_id_binding_mutation_reports_partition(replay_case, capsys) -> None:
    case, before = replay_case
    payload = json.loads(case["snapshot"].read_text())
    # Fixed after a one-time probe: replacing pub-fm-08's vector with the vector
    # from cross-cluster fleet-OPS-14 moves their binding; the test never searches.
    assert payload["embeddings"]["pub-fm-08"] != payload["embeddings"]["fleet-OPS-14"]
    payload["embeddings"]["pub-fm-08"] = payload["embeddings"]["fleet-OPS-14"]
    # hindsight#108: this literal is MACHINE-MAINTAINED. bin/add-failure-mode.sh
    # rewrites the digits as part of the same write transaction that appends a
    # catalog entry, parsing them from the pipeline's own replay report. Do not
    # restate the count in prose here -- the updater rewrites digits, not
    # comments, so any number written above this line drifts silently and lies.
    assert len(payload["embeddings"]) == 824
    case["snapshot"].write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    assert _run(case) == 1
    error = capsys.readouterr().err
    assert error.startswith("replay-l2: error: partition mismatch: expected-only=")
    assert "'fleet-OPS-14', 'pub-fm-08'" in error
    _assert_originals(before)


def test_default_committed_replay_succeeds_with_network_poisoned(
    replay_case, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _case, before = replay_case
    network_attempts: list[str] = []

    def poison(*_args, **_kwargs):
        network_attempts.append("attempted")
        raise AssertionError("NETWORK ACCESS ATTEMPTED DURING OFFLINE REPLAY")

    real_load_cluster = REPLAY._load_cluster

    def load_poisoned_cluster(path, code_bytes=None):
        module = real_load_cluster(path, code_bytes)
        module.select_backend = poison
        module.HttpEmbeddingBackend = poison
        module.urlopen = poison
        return module

    monkeypatch.setattr(socket, "socket", poison)
    monkeypatch.setattr(urllib.request, "urlopen", poison)
    monkeypatch.setattr(REPLAY, "_load_cluster", load_poisoned_cluster)

    assert REPLAY.main([]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    # hindsight#108: these literals are MACHINE-MAINTAINED. bin/add-failure-mode.sh
    # rewrites both digits inside the same write transaction that appends a catalog
    # entry, parsing them from the pipeline's own replay report. Do not restate the
    # CURRENT counts in prose here: the updater rewrites digits, not comments, so a
    # live count written above this line drifts silently and lies.
    assert captured.out == "replay-l2: PASS: 824 entries, 300 clusters\n"
    assert network_attempts == []
    _assert_originals(before)
