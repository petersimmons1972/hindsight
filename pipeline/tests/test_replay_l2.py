"""Tests for deterministic, network-free L2 replay."""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]
CLUSTER_SPEC = importlib.util.spec_from_file_location("replay_test_cluster", ROOT / "pipeline/cluster.py")
assert CLUSTER_SPEC and CLUSTER_SPEC.loader
CLUSTER = importlib.util.module_from_spec(CLUSTER_SPEC)
sys.modules[CLUSTER_SPEC.name] = CLUSTER
CLUSTER_SPEC.loader.exec_module(CLUSTER)
REPLAY_SPEC = importlib.util.spec_from_file_location("hindsight_replay_l2", ROOT / "pipeline/replay_l2.py")
assert REPLAY_SPEC and REPLAY_SPEC.loader
REPLAY = importlib.util.module_from_spec(REPLAY_SPEC)
sys.modules[REPLAY_SPEC.name] = REPLAY
REPLAY_SPEC.loader.exec_module(REPLAY)


@pytest.mark.parametrize("record_id", ["hc-FM-379", "hc-FM-382"])
def test_process_self_match_catalog_rows_keep_lesson_in_check(record_id: str) -> None:
    """A table delimiter in narrative text must not shift it into the Check cell."""
    records = [
        json.loads(line)
        for line in (ROOT / "pipeline" / "L1" / "homelab-canon.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    record = next(item for item in records if item["id"] == record_id)

    assert "`ps -eo` piped to `awk` variant" in record["instance"]
    assert record["check"].startswith("A process check must match on a token")


def test_committed_snapshot_replays_through_real_default_loader(capsys) -> None:
    # hindsight#108: these literals are MACHINE-MAINTAINED. bin/add-failure-mode.sh
    # rewrites both digits as part of the same write transaction that appends a
    # catalog entry, parsing them from the pipeline's own replay report. The
    # cluster count is NOT derivable from the entry count. Historical evidence,
    # fixed and not a live count: one 2026-08-21 add moved entries 708 -> 709 and
    # clusters 281 -> 283. So both are parsed, never computed. Do not restate the
    # CURRENT counts in prose here: the updater rewrites digits, not comments, so
    # any live count written above this line drifts silently and lies.
    assert REPLAY.main([]) == 0 and "PASS: 980 entries, 348 clusters" in capsys.readouterr().out
def _record(record_id: str) -> dict[str, object]:
    return {
        "id": record_id, "source_path": f"repo/{record_id}", "source_anchor": "line 1",
        "instance": f"distinct incident {record_id}", "check": None, "enforcement": None,
        "auto": "judgment", "first_seen": None,
    }
@pytest.fixture
def replay_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    l1 = tmp_path / "L1"
    l1.mkdir()
    ids = ["a", "b", "c", "d", "e"]
    (l1 / "records.jsonl").write_text(
        "".join(json.dumps(_record(record_id)) + "\n" for record_id in ids), encoding="utf-8"
    )
    cluster_code = tmp_path / "cluster.py"
    cluster_code.write_text("fixture cluster code\n", encoding="utf-8")
    monkeypatch.setattr(CLUSTER, "HTTP_DENSE_WEIGHT", 1.0)
    monkeypatch.setitem(CLUSTER.CLUSTER_CONFIG, "http_dense_weight", 1.0)
    monkeypatch.setattr(CLUSTER, "HTTP_BACKEND_IDENTITY", {
        "name": "http", "model": "fixture", "revision": "v1", "dimensions": 2,
    })
    monkeypatch.setattr(REPLAY, "_load_cluster", lambda _path, _code_bytes=None: CLUSTER)
    entries = CLUSTER.load_entries(l1)
    vectors = {"a": [1.0, 0.0], "b": [0.99, 0.01], "c": [0.0, 1.0],
               "d": [-1.0, 0.0], "e": [0.0, -1.0]}
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "schema": CLUSTER.SNAPSHOT_SCHEMA,
        "provenance": {"l1_sha256": CLUSTER.l1_corpus_digest(l1),
                       "cluster_sha256": CLUSTER.cluster_code_config_digest(cluster_code)},
        "backend": CLUSTER.HTTP_BACKEND_IDENTITY, "embeddings": vectors,
        "similarity_text_sha256": {
            entry.id: CLUSTER.similarity_text_digest(entry) for entry in entries
        },
    }) + "\n", encoding="utf-8")
    clusters = tmp_path / "clusters.jsonl"
    _write_clusters(clusters, [["e"], ["b", "a"], ["d"], ["c"]], CLUSTER)
    return {"l1": l1, "snapshot": snapshot, "clusters": clusters, "code": cluster_code}
def _write_clusters(path: Path, groups: list[list[str]], cluster=CLUSTER,
                    meta: dict[str, object] | None = None) -> None:
    metadata = meta or {"backend": "http", "threshold": cluster.default_threshold("http"),
                        "entry_count": 5, "linkage": cluster.LINKAGE}
    rows = [{"_meta": metadata}, *({"members": group} for group in groups)]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
def _run(case: dict[str, Path]) -> int:
    return REPLAY.main(["--input-dir", str(case["l1"]), "--snapshot", str(case["snapshot"]),
                        "--clusters", str(case["clusters"]), "--cluster-code", str(case["code"])])
def test_equivalent_reordered_partition_passes(replay_case, capsys) -> None:
    assert _run(replay_case) == 0
    assert "PASS: 5 entries, 4 clusters" in capsys.readouterr().out
def test_changed_partition_fails_and_names_deterministic_mismatch(replay_case, capsys) -> None:
    _write_clusters(replay_case["clusters"], [["a"], ["b"], ["c"], ["d"], ["e"]])
    assert _run(replay_case) == 1
    error = capsys.readouterr().err
    assert "expected-only" in error and "replay-only" in error and "a" in error and "b" in error
def test_changed_l1_bytes_fail_snapshot_digest(replay_case, capsys) -> None:
    path = replay_case["l1"] / "records.jsonl"
    path.write_text(path.read_text().replace("distinct incident a", "changed incident a"), encoding="utf-8")
    assert _run(replay_case) == 1
    assert "L1 digest mismatch" in capsys.readouterr().err
def test_corrupt_vector_id_mapping_changes_partition_and_fails(replay_case, capsys) -> None:
    payload = json.loads(replay_case["snapshot"].read_text())
    payload["embeddings"]["b"], payload["embeddings"]["c"] = (
        payload["embeddings"]["c"], payload["embeddings"]["b"])
    replay_case["snapshot"].write_text(json.dumps(payload) + "\n", encoding="utf-8")
    assert _run(replay_case) == 1
    assert "partition mismatch" in capsys.readouterr().err
@pytest.mark.parametrize(("groups", "needle"), [
    ([['a', 'b'], ['c'], ['d']], "missing=['e']"),
    ([['a', 'b'], ['c'], ['d'], ['e'], ['foreign']], "unexpected=['foreign']"),
    ([['a', 'b'], ['c'], ['d'], ['e'], ['a']], "duplicate member IDs: ['a']"),
])
def test_committed_member_coverage_fails_loudly(replay_case, capsys, groups, needle) -> None:
    _write_clusters(replay_case["clusters"], groups)
    assert _run(replay_case) == 1
    assert needle in capsys.readouterr().err
@pytest.mark.parametrize(("contents", "needle"), [
    ('{"_meta":}\n', "clusters.jsonl:1: invalid JSON"),
    ('{"_meta": {}}\n\n', "clusters.jsonl:2: blank JSONL line"),
    ('{"members":["a"]}\n', "clusters.jsonl:1: first row"),
    (json.dumps({"_meta": {"backend": "tfidf", "threshold": .2,
                            "entry_count": 5, "linkage": "average"}}) + "\n", "metadata mismatch"),
])
def test_malformed_blank_missing_or_drifted_metadata_fails(replay_case, capsys, contents, needle) -> None:
    replay_case["clusters"].write_text(contents, encoding="utf-8")
    assert _run(replay_case) == 1
    assert needle in capsys.readouterr().err

@pytest.mark.parametrize(("field", "value"), [
    ("backend", 7),
    ("threshold", True),
    ("entry_count", 5.0),
    ("entry_count", True),
    ("linkage", 7),
])
def test_metadata_rejects_equal_or_invalid_scalar_types(
    replay_case, capsys, field, value
) -> None:
    metadata = {
        "backend": "http", "threshold": CLUSTER.default_threshold("http"),
        "entry_count": 5, "linkage": CLUSTER.LINKAGE,
    }
    metadata[field] = value
    _write_clusters(
        replay_case["clusters"], [["e"], ["b", "a"], ["d"], ["c"]], meta=metadata
    )
    assert _run(replay_case) == 1
    assert f"metadata {field}" in capsys.readouterr().err

def test_l1_drift_after_digest_before_comparison_fails(
    replay_case, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_digest = CLUSTER.l1_corpus_digest
    changed = False

    def digest_then_change(path: Path) -> str:
        nonlocal changed
        digest = real_digest(path)
        if not changed:
            changed = True
            record = path / "records.jsonl"
            record.write_text(
                record.read_text(encoding="utf-8").replace("distinct incident a", "drifted incident a"),
                encoding="utf-8",
            )
        return digest

    monkeypatch.setattr(CLUSTER, "l1_corpus_digest", digest_then_change)
    assert _run(replay_case) == 1
    assert "L1 changed during replay" in capsys.readouterr().err

def test_cluster_code_drift_after_digest_before_comparison_fails(
    replay_case, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_digest = CLUSTER.cluster_code_config_digest
    changed = False

    def digest_then_change(path: Path) -> str:
        nonlocal changed
        digest = real_digest(path)
        if not changed:
            changed = True
            path.write_text(path.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        return digest

    monkeypatch.setattr(CLUSTER, "cluster_code_config_digest", digest_then_change)
    assert _run(replay_case) == 1
    assert "cluster code/config changed during replay" in capsys.readouterr().err
def test_replay_never_selects_or_contacts_http(replay_case, monkeypatch) -> None:
    def poisoned(*_args, **_kwargs):
        raise AssertionError("network/backend path reached")
    monkeypatch.setattr(CLUSTER, "select_backend", poisoned)
    monkeypatch.setattr(CLUSTER, "HttpEmbeddingBackend", poisoned)
    monkeypatch.setattr(CLUSTER, "urlopen", poisoned)
    assert _run(replay_case) == 0
def test_command_is_read_only(replay_case, tmp_path: Path) -> None:
    before = {key: path.read_bytes() if path.is_file() else
              {child.name: child.read_bytes() for child in path.iterdir()}
              for key, path in replay_case.items()}
    existing = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert _run(replay_case) == 0
    assert before == {key: path.read_bytes() if path.is_file() else
                      {child.name: child.read_bytes() for child in path.iterdir()}
                      for key, path in replay_case.items()}
    assert existing == sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
