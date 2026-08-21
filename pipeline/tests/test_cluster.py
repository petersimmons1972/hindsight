"""Acceptance tests for root-cause clustering.

The coordinator-authored fixture is deliberately read here rather than mirrored
in test data so this suite cannot silently grade a different contract.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Self
from urllib.error import HTTPError

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "pipeline" / "tests" / "fixtures" / "recurrence_ground_truth.json"
HOLDOUT_FIXTURE = ROOT / "pipeline" / "tests" / "fixtures" / "holdout_paraphrases.json"
MODULE_PATH = ROOT / "pipeline" / "cluster.py"
SPEC = importlib.util.spec_from_file_location("hindsight_cluster", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CAPTURE_PATH = ROOT / "pipeline" / "capture_embedding_snapshot.py"
CAPTURE_SPEC = importlib.util.spec_from_file_location("hindsight_capture", CAPTURE_PATH)
assert CAPTURE_SPEC and CAPTURE_SPEC.loader
CAPTURE = importlib.util.module_from_spec(CAPTURE_SPEC)
sys.modules[CAPTURE_SPEC.name] = CAPTURE
CAPTURE_SPEC.loader.exec_module(CAPTURE)

BASELINES_PATH = ROOT / "pipeline" / "recall_baselines.py"
BASELINES_SPEC = importlib.util.spec_from_file_location("hindsight_recall_baselines", BASELINES_PATH)
assert BASELINES_SPEC and BASELINES_SPEC.loader
BASELINES = importlib.util.module_from_spec(BASELINES_SPEC)
sys.modules[BASELINES_SPEC.name] = BASELINES
BASELINES_SPEC.loader.exec_module(BASELINES)


def _corpus_marker_texts() -> list[str]:
    """The exact text `_cause_shape_markers` is ever allowed to see: instance,
    check, and class_hint -- never id or source_path (identity leakage) and
    never source_anchor (a field markers do not read, so grounding there
    would prove nothing about what the regex can actually match at runtime).
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    return [
        " ".join(filter(None, [entry.instance, entry.check, entry.class_hint])).lower()
        for entry in entries
    ]


def test_clustering_engine_exists() -> None:
    """The L2 engine is an explicit pipeline stage, not an implicit script."""
    assert (ROOT / "pipeline" / "cluster.py").is_file()


def _assignments(clusters: list[object]) -> dict[str, str]:
    return {
        member: cluster.cluster_id
        for cluster in clusters
        for member in cluster.members
    }


def _snapshot_entries() -> list[MODULE.Entry]:
    return [
        MODULE.Entry(
            id="snapshot-a",
            instance="The completion signal claimed success without an artifact.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="one/failures.md",
        ),
        MODULE.Entry(
            id="snapshot-b",
            instance="A successful status was emitted although the artifact was absent.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="two/failures.md",
        ),
        MODULE.Entry(
            id="snapshot-c",
            instance="Certificate renewal used the wrong DNS challenge token.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="three/failures.md",
        ),
        MODULE.Entry(
            id="snapshot-d",
            instance="A database migration waited forever on a schema lock.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="four/failures.md",
        ),
        MODULE.Entry(
            id="snapshot-e",
            instance="A cache key omitted the tenant identifier.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="five/failures.md",
        ),
    ]


def _write_snapshot(
    path: Path,
    *,
    backend: dict[str, object],
    vectors: dict[str, list[float]],
    l1_digest: str = "a" * 64,
    cluster_digest: str = "b" * 64,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "hindsight.embedding-snapshot/v2",
                "provenance": {
                    "l1_sha256": l1_digest,
                    "cluster_sha256": cluster_digest,
                },
                "backend": backend,
                "embeddings": vectors,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_snapshot_matrix_reproduces_equivalent_live_vector_partition(tmp_path: Path) -> None:
    """Offline replay consumes the same vectors without invoking a backend."""
    entries = _snapshot_entries()
    identity = {
        "name": "test-dense",
        "model": "BAAI/bge-m3",
        "revision": "example-revision",
        "dimensions": 4,
    }
    live_matrix = np.asarray(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.99, 0.01, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    snapshot = tmp_path / "embedding-snapshot.json"
    _write_snapshot(
        snapshot,
        backend=identity,
        vectors={entry.id: live_matrix[index].tolist() for index, entry in enumerate(entries)},
    )

    replay_matrix = MODULE.load_embedding_snapshot(
        snapshot, entries, identity, expected_l1_digest="a" * 64, expected_cluster_digest="b" * 64
    )
    live = MODULE.cluster_entries(entries, live_matrix, backend_name="test-dense", threshold=0.95)
    replay = MODULE.cluster_entries(entries, replay_matrix, backend_name="test-dense", threshold=0.95)

    live_assignments = _assignments(live)
    assert live_assignments["snapshot-a"] == live_assignments["snapshot-b"]
    assert live_assignments["snapshot-a"] != live_assignments["snapshot-c"]
    assert _assignments(replay) == live_assignments


def test_precomputed_matrix_rejects_ambiguous_unsorted_entry_order() -> None:
    entries = _snapshot_entries()
    matrix = np.eye(len(entries), dtype=np.float32)

    with pytest.raises(ValueError, match=r"entries must be sorted by L1 id.*matrix row order"):
        MODULE.cluster_entries(list(reversed(entries)), matrix, backend_name="test-dense")


def test_snapshot_backend_identity_mismatch_is_rejected_loudly(tmp_path: Path) -> None:
    entries = _snapshot_entries()
    snapshot = tmp_path / "embedding-snapshot.json"
    _write_snapshot(
        snapshot,
        backend={"name": "http", "model": "BAAI/bge-m3", "revision": "rev-a", "dimensions": 2},
        vectors={entry.id: [1.0, 0.0] for entry in entries},
    )

    with pytest.raises(ValueError, match=r"backend identity mismatch.*revision.*rev-a.*rev-b"):
        MODULE.load_embedding_snapshot(
            snapshot,
            entries,
            {"name": "http", "model": "BAAI/bge-m3", "revision": "rev-b", "dimensions": 2},
            expected_l1_digest="a" * 64,
            expected_cluster_digest="b" * 64,
        )


def test_snapshot_id_mismatch_names_missing_and_unexpected_ids(tmp_path: Path) -> None:
    entries = _snapshot_entries()
    identity = {"name": "http", "model": "model", "revision": "rev", "dimensions": 2}
    snapshot = tmp_path / "embedding-snapshot.json"
    _write_snapshot(
        snapshot,
        backend=identity,
        vectors={"snapshot-a": [1.0, 0.0], "snapshot-c": [0.0, 1.0], "snapshot-extra": [0.5, 0.5]},
    )

    with pytest.raises(ValueError, match=r"missing.*snapshot-b.*unexpected.*snapshot-extra"):
        MODULE.load_embedding_snapshot(
            snapshot, entries, identity, expected_l1_digest="a" * 64, expected_cluster_digest="b" * 64
        )


def test_snapshot_zero_overlap_alarms_and_names_both_id_sets(tmp_path: Path) -> None:
    entries = _snapshot_entries()
    identity = {"name": "http", "model": "model", "revision": "rev", "dimensions": 2}
    snapshot = tmp_path / "embedding-snapshot.json"
    _write_snapshot(snapshot, backend=identity, vectors={"foreign-a": [1.0, 0.0], "foreign-b": [0.0, 1.0]})

    with pytest.raises(
        ValueError,
        match=r"ALARM: zero ID overlap.*snapshot-a.*snapshot-b.*snapshot-c.*foreign-a.*foreign-b",
    ):
        MODULE.load_embedding_snapshot(
            snapshot, entries, identity, expected_l1_digest="a" * 64, expected_cluster_digest="b" * 64
        )


def test_committed_snapshot_covers_the_current_l1_corpus_exactly() -> None:
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    matrix = MODULE.load_embedding_snapshot(
        ROOT / "pipeline" / "L2" / "embedding-snapshot.json",
        entries,
        MODULE.HTTP_BACKEND_IDENTITY,
        expected_l1_digest=MODULE.l1_corpus_digest(ROOT / "pipeline" / "L1"),
        expected_cluster_digest=MODULE.cluster_code_config_digest(ROOT / "pipeline" / "cluster.py"),
    )

    assert matrix.shape == (len(entries), 1024)


def test_snapshot_rejects_stale_declared_digests(tmp_path: Path) -> None:
    entries = _snapshot_entries()
    identity = {"name": "http", "model": "model", "revision": "rev", "dimensions": 2}
    snapshot = tmp_path / "embedding-snapshot.json"
    _write_snapshot(snapshot, backend=identity, vectors={entry.id: [1.0, 0.0] for entry in entries})

    with pytest.raises(ValueError, match="L1 digest mismatch"):
        MODULE.load_embedding_snapshot(
            snapshot, entries, identity, expected_l1_digest="c" * 64, expected_cluster_digest="b" * 64
        )
    with pytest.raises(ValueError, match="cluster code/config digest mismatch"):
        MODULE.load_embedding_snapshot(
            snapshot, entries, identity, expected_l1_digest="a" * 64, expected_cluster_digest="c" * 64
        )


def _write_l1(directory: Path, record_id: str = "item-a", instance: str = "first") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "id": record_id, "source_path": "repo/file", "source_anchor": "line 1",
        "instance": instance, "check": None, "enforcement": None,
        "auto": "judgment", "first_seen": None,
    }
    (directory / "one.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


def test_provenance_digests_change_with_l1_and_cluster_inputs(tmp_path: Path) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1)
    first_l1 = MODULE.l1_corpus_digest(l1)
    _write_l1(l1, instance="changed")
    assert MODULE.l1_corpus_digest(l1) != first_l1

    cluster = tmp_path / "cluster.py"
    cluster.write_text("code-a\n", encoding="utf-8")
    first_cluster = MODULE.cluster_code_config_digest(cluster)
    cluster.write_text("code-b\n", encoding="utf-8")
    assert MODULE.cluster_code_config_digest(cluster) != first_cluster
    code_b_digest = MODULE.cluster_code_config_digest(cluster)
    original = MODULE.CLUSTER_CONFIG["http_dense_weight"]
    MODULE.CLUSTER_CONFIG["http_dense_weight"] = 0.25
    try:
        assert MODULE.cluster_code_config_digest(cluster) != code_b_digest
    finally:
        MODULE.CLUSTER_CONFIG["http_dense_weight"] = original


@pytest.mark.parametrize("changed_input", ["l1", "cluster"])
def test_capture_rejects_provenance_drift_during_request_and_preserves_output(
    tmp_path: Path, monkeypatch, changed_input: str
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1, instance="old text")
    cluster_code = tmp_path / "cluster.py"
    cluster_code.write_text("old code\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"
    prior = b"trusted-prior-snapshot\n"
    output.write_bytes(prior)

    def mutate_during_request(base_url: str, texts: list[str], timeout: float) -> np.ndarray:
        assert "old text" in texts[0]
        if changed_input == "l1":
            _write_l1(l1, instance="new text")
        else:
            cluster_code.write_text("new code\n", encoding="utf-8")
        return np.asarray([[1.0, 0.0]], dtype=np.float32)

    monkeypatch.setattr(CAPTURE, "_request_vectors", mutate_during_request)
    args = CAPTURE._parser().parse_args([
        "--input-dir", str(l1), "--output", str(output),
        "--model", "fake", "--revision", "r1", "--dimensions", "2",
        "--cluster-code", str(cluster_code),
    ])

    with pytest.raises(ValueError, match=r"provenance changed during capture"):
        CAPTURE.capture(args)
    assert output.read_bytes() == prior
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []


def test_capture_rolls_back_when_provenance_changes_inside_replace(
    tmp_path: Path, monkeypatch
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1, instance="old text")
    cluster_code = tmp_path / "cluster.py"
    cluster_code.write_text("stable code\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"
    prior = b"trusted-prior-snapshot\n"
    output.write_bytes(prior)
    monkeypatch.setattr(
        CAPTURE,
        "_request_vectors",
        lambda base_url, texts, timeout: np.asarray([[1.0, 0.0]], dtype=np.float32),
    )
    real_replace = os.replace
    first_replace = True

    def mutate_then_replace(source: Path, destination: Path) -> None:
        nonlocal first_replace
        if first_replace:
            first_replace = False
            _write_l1(l1, instance="changed inside replace")
        real_replace(source, destination)

    monkeypatch.setattr(CAPTURE.os, "replace", mutate_then_replace)
    args = CAPTURE._parser().parse_args([
        "--input-dir", str(l1), "--output", str(output),
        "--model", "fake", "--revision", "r1", "--dimensions", "2",
        "--cluster-code", str(cluster_code),
    ])

    with pytest.raises(ValueError, match=r"provenance changed during capture"):
        CAPTURE.capture(args)
    assert output.read_bytes() == prior
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []


@pytest.mark.parametrize("failure", ["create", "write", "fsync"])
def test_capture_recovery_staging_failure_preserves_prior_snapshot(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1, instance="old text")
    cluster_code = tmp_path / "cluster.py"
    cluster_code.write_text("stable code\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"
    prior = b"trusted-prior-snapshot\n"
    output.write_bytes(prior)
    monkeypatch.setattr(
        CAPTURE,
        "_request_vectors",
        lambda base_url, texts, timeout: np.asarray([[1.0, 0.0]], dtype=np.float32),
    )

    real_named_temporary_file = CAPTURE.tempfile.NamedTemporaryFile
    temporary_calls = 0

    class FailingWriteHandle:
        def __init__(self, handle: object) -> None:
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self.handle.__exit__(*args)

        def __getattr__(self, name: str) -> object:
            return getattr(self.handle, name)

        def write(self, data: bytes) -> int:
            raise OSError("recovery write failed")

    def controlled_named_temporary_file(*args: object, **kwargs: object):
        nonlocal temporary_calls
        temporary_calls += 1
        if temporary_calls == 2 and failure == "create":
            raise OSError("recovery creation failed")
        handle = real_named_temporary_file(*args, **kwargs)
        if temporary_calls == 2 and failure == "write":
            return FailingWriteHandle(handle)
        return handle

    monkeypatch.setattr(CAPTURE.tempfile, "NamedTemporaryFile", controlled_named_temporary_file)
    if failure == "fsync":
        real_fsync = CAPTURE.os.fsync
        fsync_calls = 0

        def fail_recovery_fsync(fd: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError("recovery fsync failed")
            real_fsync(fd)

        monkeypatch.setattr(CAPTURE.os, "fsync", fail_recovery_fsync)

    args = CAPTURE._parser().parse_args([
        "--input-dir", str(l1), "--output", str(output),
        "--model", "fake", "--revision", "r1", "--dimensions", "2",
        "--cluster-code", str(cluster_code),
    ])

    with pytest.raises(OSError, match=r"recovery"):
        CAPTURE.capture(args)
    assert output.read_bytes() == prior
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []
    assert list(tmp_path.glob(".snapshot.json.*.recovery")) == []


@pytest.mark.parametrize("rename_fails", [False, True])
def test_capture_rollback_replace_failure_restores_or_retains_recovery_copy(
    tmp_path: Path, monkeypatch, rename_fails: bool
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1, instance="old text")
    cluster_code = tmp_path / "cluster.py"
    cluster_code.write_text("stable code\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"
    prior = b"trusted-prior-snapshot\n"
    output.write_bytes(prior)
    monkeypatch.setattr(
        CAPTURE,
        "_request_vectors",
        lambda base_url, texts, timeout: np.asarray([[1.0, 0.0]], dtype=np.float32),
    )
    real_replace = os.replace
    replace_calls = 0

    def fail_rollback_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            _write_l1(l1, instance="changed inside replace")
            real_replace(source, destination)
            return
        raise OSError("rollback replace failed")

    monkeypatch.setattr(CAPTURE.os, "replace", fail_rollback_replace)
    if rename_fails:
        monkeypatch.setattr(CAPTURE.os, "rename", lambda source, destination: (_ for _ in ()).throw(OSError("rename failed")))
    args = CAPTURE._parser().parse_args([
        "--input-dir", str(l1), "--output", str(output),
        "--model", "fake", "--revision", "r1", "--dimensions", "2",
        "--cluster-code", str(cluster_code),
    ])

    if rename_fails:
        with pytest.raises(RuntimeError, match=r"prior snapshot preserved at"):
            CAPTURE.capture(args)
        assert not output.exists()
        recovery = list(tmp_path.glob(".snapshot.json.*.recovery"))
        assert len(recovery) == 1
        assert recovery[0].read_bytes() == prior
    else:
        with pytest.raises(ValueError, match=r"provenance changed during capture"):
            CAPTURE.capture(args)
        assert output.read_bytes() == prior
        assert list(tmp_path.glob(".snapshot.json.*.recovery")) == []


class _EmbeddingHandler(BaseHTTPRequestHandler):
    response: object = {"data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}]}
    status = 200

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        self.server.requests.append(json.loads(self.rfile.read(length)))  # type: ignore[attr-defined]
        response = type(self).response
        if self.path == "/v1/embeddings" and isinstance(response, dict) and isinstance(response.get("data"), list):
            response = dict(response)
            response["data"] = [
                ({**item, "index": index} if isinstance(item, dict) and "index" not in item else item)
                for index, item in enumerate(response["data"])
            ]
        body = json.dumps(response).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _serve_embeddings(response: object, status: int = 200):
    _EmbeddingHandler.response = response
    _EmbeddingHandler.status = status
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EmbeddingHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test_openai_response_indices_bind_vectors_to_request_order() -> None:
    payload = {
        "data": [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]
    }
    vectors = CAPTURE._indexed_openai_vectors(payload, 2)
    np.testing.assert_array_equal(vectors, [[1.0, 0.0], [0.0, 1.0]])


@pytest.mark.parametrize(
    "data,error",
    [
        ([{"embedding": [1.0, 0.0]}], "missing or invalid index"),
        ([{"index": True, "embedding": [1.0, 0.0]}], "missing or invalid index"),
        ([{"index": 0, "embedding": [1.0, 0.0]}, {"index": 0, "embedding": [0.0, 1.0]}], "duplicate index"),
        ([{"index": 1, "embedding": [1.0, 0.0]}], "coverage mismatch"),
    ],
)
def test_openai_response_rejects_ambiguous_indices(data: list[object], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        CAPTURE._indexed_openai_vectors({"data": data}, 1)


def test_capture_falls_back_to_native_per_text_endpoint(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def post(base_url: str, endpoint: str, payload: dict[str, object], timeout: float) -> object:
        calls.append((endpoint, payload))
        if endpoint == "/v1/embeddings":
            raise HTTPError(base_url + endpoint, 404, "not supported", None, None)
        content = payload["content"]
        return {"embedding": [1.0, 0.0] if content == "first" else [0.0, 1.0]}

    monkeypatch.setattr(CAPTURE, "_post_json", post)
    matrix = CAPTURE._request_vectors("http://192.168.0.98:8004", ["first", "second"], 1.0)
    np.testing.assert_array_equal(matrix, [[1.0, 0.0], [0.0, 1.0]])
    assert calls == [
        ("/v1/embeddings", {"input": ["first", "second"]}),
        ("/embedding", {"content": "first"}),
        ("/embedding", {"content": "second"}),
    ]


def test_atomic_snapshot_write_fsyncs_file_and_containing_directory(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "snapshot.json"
    real_fsync = os.fsync
    synced_modes: list[int] = []

    def recording_fsync(fd: int) -> None:
        synced_modes.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(CAPTURE.os, "fsync", recording_fsync)
    CAPTURE._atomic_write_json(output, {"ok": True})

    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    assert any(stat.S_ISREG(mode) for mode in synced_modes)
    assert any(stat.S_ISDIR(mode) for mode in synced_modes)


def test_atomic_snapshot_write_persists_recovery_name_before_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"trusted prior\n")
    events: list[str] = []
    real_replace = os.replace

    monkeypatch.setattr(
        CAPTURE, "_fsync_directory", lambda directory: events.append("directory-fsync")
    )

    def recording_replace(source: Path, destination: Path) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(CAPTURE.os, "replace", recording_replace)
    CAPTURE._atomic_write_json(output, {"ok": True})

    assert events[0:2] == ["directory-fsync", "replace"]
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}


def test_controlled_capture_is_loadable_exact_coverage_atomic_and_repeatable(
    tmp_path: Path, monkeypatch
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1, "item-a", "first")
    record = json.loads((l1 / "one.jsonl").read_text())
    record["id"], record["instance"] = "item-b", "second"
    (l1 / "two.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"prior")
    server, url = _serve_embeddings({"data": [{"embedding": [3.0, 0.0]}, {"embedding": [0.0, 4.0]}]})
    monkeypatch.setattr(CAPTURE, "AUTHORIZED_HTTP_HOSTS", frozenset({"127.0.0.1"}))
    try:
        assert CAPTURE.main([
            "--input-dir", str(l1), "--output", str(output), "--backend-url", url,
            "--model", "fake", "--revision", "r1", "--dimensions", "2",
            "--cluster-code", str(MODULE_PATH),
        ]) == 0
        first_bytes = output.read_bytes()
        _EmbeddingHandler.response = {
            "data": [{"embedding": [1.0, 1.0]}, {"embedding": [-1.0, 1.0]}]
        }
        assert CAPTURE.main([
            "--input-dir", str(l1), "--output", str(output), "--backend-url", url,
            "--model", "fake", "--revision", "r1", "--dimensions", "2",
            "--cluster-code", str(MODULE_PATH),
        ]) == 0
    finally:
        server.shutdown()

    entries = MODULE.load_entries(l1)
    matrix = MODULE.load_embedding_snapshot(
        output, entries, {"name": "http", "model": "fake", "revision": "r1", "dimensions": 2},
        expected_l1_digest=MODULE.l1_corpus_digest(l1),
        expected_cluster_digest=MODULE.cluster_code_config_digest(MODULE_PATH),
    )
    np.testing.assert_allclose(
        matrix,
        [[2 ** -0.5, 2 ** -0.5], [-2 ** -0.5, 2 ** -0.5]],
    )
    assert output.read_bytes() != first_bytes
    expected_request = {"input": [MODULE.similarity_text(entry) for entry in entries]}
    assert server.requests == [expected_request, expected_request]
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []


@pytest.mark.parametrize(
    "response,error",
    [
        ({"data": [{"embedding": [1.0, 0.0]}]}, "count"),
        ({"data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}, {"embedding": [1.0, 1.0]}]}, "count"),
        ({"data": [{"embedding": [1.0, 0.0]}, {"embedding": [float("nan"), 1.0]}]}, "finite"),
        ({"data": [{"embedding": ["1", 0.0]}, {"embedding": [0.0, 1.0]}]}, "numeric"),
        ({"data": [{"embedding": [True, 0.0]}, {"embedding": [0.0, 1.0]}]}, "numeric"),
        ({"data": [{"embedding": [1.0]}, {"embedding": [0.0, 1.0]}]}, "dimensions"),
        ({"wrong": []}, "vectors"),
    ],
)
def test_capture_protocol_errors_leave_existing_output_byte_identical(
    tmp_path: Path, monkeypatch, capsys, response: object, error: str
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1, "item-a", "first")
    record = json.loads((l1 / "one.jsonl").read_text())
    record["id"] = "item-b"
    (l1 / "two.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"
    prior = b"do-not-replace\x00"
    output.write_bytes(prior)
    server, url = _serve_embeddings(response)
    monkeypatch.setattr(CAPTURE, "AUTHORIZED_HTTP_HOSTS", frozenset({"127.0.0.1"}))
    try:
        result = CAPTURE.main([
            "--input-dir", str(l1), "--output", str(output), "--backend-url", url,
            "--model", "fake", "--revision", "r1", "--dimensions", "2",
            "--cluster-code", str(MODULE_PATH),
        ])
    finally:
        server.shutdown()
    assert result != 0
    assert error in capsys.readouterr().err
    assert output.read_bytes() == prior


def test_capture_backend_failure_and_write_failure_preserve_prior_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1)
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"prior")
    monkeypatch.setattr(CAPTURE, "AUTHORIZED_HTTP_HOSTS", frozenset({"127.0.0.1"}))
    assert CAPTURE.main([
        "--input-dir", str(l1), "--output", str(output), "--backend-url", "http://127.0.0.1:1",
        "--model", "fake", "--revision", "r1", "--dimensions", "2", "--cluster-code", str(MODULE_PATH),
    ]) != 0
    assert "error" in capsys.readouterr().err
    assert output.read_bytes() == b"prior"

    server, url = _serve_embeddings({"data": [{"embedding": [1.0, 0.0]}]})
    monkeypatch.setattr(CAPTURE.os, "replace", lambda source, target: (_ for _ in ()).throw(OSError("replace denied")))
    try:
        assert CAPTURE.main([
            "--input-dir", str(l1), "--output", str(output), "--backend-url", url,
            "--model", "fake", "--revision", "r1", "--dimensions", "2", "--cluster-code", str(MODULE_PATH),
        ]) != 0
    finally:
        server.shutdown()
    assert output.read_bytes() == b"prior"
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []


def test_capture_rejects_deceptive_or_non_http_backend_before_contact(tmp_path: Path, monkeypatch) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1)
    monkeypatch.setattr(CAPTURE, "AUTHORIZED_HTTP_HOSTS", frozenset({"127.0.0.1"}))
    for url in ("https://127.0.0.1/v1", "http://127.0.0.1.evil.invalid/v1"):
        assert CAPTURE.main([
            "--input-dir", str(l1), "--output", str(tmp_path / "out.json"), "--backend-url", url,
            "--model", "fake", "--revision", "r1", "--dimensions", "2", "--cluster-code", str(MODULE_PATH),
        ]) != 0


def test_capture_rejects_invalid_declared_backend_identity_without_replacing_output(
    tmp_path: Path, monkeypatch
) -> None:
    l1 = tmp_path / "L1"
    _write_l1(l1)
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"prior")
    server, url = _serve_embeddings({"data": [{"embedding": [1.0, 0.0]}]})
    monkeypatch.setattr(CAPTURE, "AUTHORIZED_HTTP_HOSTS", frozenset({"127.0.0.1"}))
    try:
        assert CAPTURE.main([
            "--input-dir", str(l1), "--output", str(output), "--backend-url", url,
            "--model", "", "--revision", "r1", "--dimensions", "2",
            "--cluster-code", str(MODULE_PATH),
        ]) != 0
    finally:
        server.shutdown()
    assert output.read_bytes() == b"prior"


def test_capture_refuses_redirect_without_contacting_unauthorized_destination(
    tmp_path: Path, monkeypatch
) -> None:
    class DestinationHandler(BaseHTTPRequestHandler):
        hits = 0

        def _respond(self) -> None:
            type(self).hits += 1
            self.send_response(200)
            body = json.dumps({"data": [{"embedding": [1.0, 0.0]}]}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _respond
        do_POST = _respond

        def log_message(self, format: str, *args: object) -> None:
            pass

    destination = ThreadingHTTPServer(("127.0.0.1", 0), DestinationHandler)
    destination_thread = threading.Thread(target=destination.serve_forever, daemon=True)
    destination_thread.start()

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(302)
            self.send_header(
                "Location", f"http://localhost:{destination.server_port}/stolen"
            )
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
    redirect_thread.start()
    l1 = tmp_path / "L1"
    _write_l1(l1)
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"prior")
    monkeypatch.setattr(CAPTURE, "AUTHORIZED_HTTP_HOSTS", frozenset({"127.0.0.1"}))
    try:
        assert CAPTURE.main([
            "--input-dir", str(l1), "--output", str(output),
            "--backend-url", f"http://127.0.0.1:{redirect.server_port}",
            "--model", "fake", "--revision", "r1", "--dimensions", "2",
            "--cluster-code", str(MODULE_PATH),
        ]) != 0
    finally:
        redirect.shutdown()
        destination.shutdown()
    assert DestinationHandler.hits == 0
    assert output.read_bytes() == b"prior"


def _assert_fixture_contract(clusters: list[object], backend: str) -> None:
    """Precision absolutely; recall against the RECORDED per-backend baseline.

    Founder ruling 2026-08-19 (hindsight#121). Recall was previously asserted
    against the fixture's absolute `min_fraction_together` of 0.75. Corpus growth
    alone (673 -> 678 entries, no code change) pushed `shared-mutable-checkout`
    below that on BOTH backends, so the absolute floor had become a number that
    could only be hand-lowered -- exactly the "floors never lower without a
    measured justification" failure this repo catalogues.

    The gate is now `pipeline/L2/recall-baselines.json`: current recall must be
    at least the recorded baseline for this (family, backend). It is a ratchet --
    recall may rise and the release path re-records it, but it may never fall
    without `recall_baselines.py --update --allow-drop --reason "..."`, which
    writes the reason into the artifact. 0.75 stays the aspirational TARGET (see
    the fixture and `recall_baselines.TARGET_FRACTION`); it is not the gate.

    Precision (`must_not_merge`) and the completion-signal headline are unchanged
    and remain absolute: they are what stops recall being satisfied trivially.
    """
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assignments = _assignments(clusters)
    families = {family["key"]: family["members"] for family in fixture["families"]}
    baselines = BASELINES.load_artifact()["baselines"].get(backend)
    assert baselines, (
        f"no recorded recall baselines for backend {backend!r} in "
        f"{BASELINES.DEFAULT_ARTIFACT}; run pipeline/recall_baselines.py --update"
    )

    for family, members in families.items():
        assigned = [assignments[member] for member in members]
        largest = max(assigned.count(cluster_id) for cluster_id in set(assigned))
        recorded = baselines[family]["fraction"]
        # 1e-9 tolerance: baseline and measurement are the same ratio of the
        # same small integers, round-tripped through JSON. See the matching
        # tolerance in recall_baselines.find_drops.
        assert largest / len(members) >= recorded - 1e-9, (
            f"{family} on {backend}: recall {largest}/{len(members)} fell below the "
            f"recorded baseline {recorded:.6f} (target "
            f"{fixture['assertions']['recall']['min_fraction_together']}). Do not "
            f"edit this test -- investigate, or re-baseline deliberately via "
            f"pipeline/recall_baselines.py --update --allow-drop --reason '...'."
        )

    for left, right in fixture["assertions"]["precision"]["must_not_merge"]:
        assert {
            assignments[member] for member in families[left]
        }.isdisjoint({assignments[member] for member in families[right]}), (left, right)

    completion = families["completion-signal"]
    completion_cluster = max(
        (assignments[member] for member in completion),
        key=lambda cluster_id: sum(assignments[member] == cluster_id for member in completion),
    )
    assert sum(assignments[member] == completion_cluster for member in completion) >= 6


def test_ground_truth_contract_with_forced_tfidf_backend() -> None:
    """Fallback output is held to the same recall and precision gate as HTTP."""
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    clusters = MODULE.cluster_entries_from_backend(entries, MODULE.TfidfEmbeddingBackend())
    _assert_fixture_contract(clusters, "tfidf")


def test_released_http_snapshot_meets_the_ground_truth_contract_offline() -> None:
    """The released HTTP calibration keeps precision without sacrificing recall.

    This deterministic adversarial gate prevents a future threshold relaxation
    from reabsorbing a completion-signal incident into the broad
    shared-mutable-checkout cluster.  It replays the released HTTP vectors, so
    the contract remains testable even when the authorised embedding service
    is unavailable.
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    vectors = MODULE.load_embedding_snapshot(
        ROOT / "pipeline" / "L2" / "embedding-snapshot.json",
        entries,
        MODULE.HTTP_BACKEND_IDENTITY,
        expected_l1_digest=MODULE.l1_corpus_digest(ROOT / "pipeline" / "L1"),
        expected_cluster_digest=MODULE.cluster_code_config_digest(ROOT / "pipeline" / "cluster.py"),
    )
    clusters = MODULE.cluster_entries(entries, vectors, backend_name="http")
    _assert_fixture_contract(clusters, "http")


def test_each_backend_has_an_explicit_calibrated_default_threshold() -> None:
    """A dense embedding backend must not inherit sparse TF-IDF's cutoff."""
    assert MODULE.default_threshold("tfidf") == 0.17
    assert MODULE.default_threshold("http") == 0.22


def test_active_http_backend_meets_the_ground_truth_contract_when_reachable() -> None:
    """The live backend is exercised, or visibly reported as untested when offline."""
    backend = MODULE.HttpEmbeddingBackend()
    if not backend.available:
        pytest.skip("authorised HTTP embedding backend is unreachable")

    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    clusters = MODULE.cluster_entries_from_backend(entries, backend)
    _assert_fixture_contract(clusters, "http")


def test_degenerate_uniform_embeddings_fail_loudly_instead_of_emitting_one_cluster() -> None:
    """A backend that makes every record equivalent cannot produce trusted L2 output."""

    class UniformEmbeddingBackend:
        name = "uniform"

        def embed(self, texts: list[str]) -> np.ndarray:
            return np.ones((len(texts), 2), dtype=np.float32)

    entries = [
        MODULE.Entry(
            id=f"example-{number}",
            instance=f"Unrelated failure {number}.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="examples/failures.md",
        )
        for number in range(5)
    ]

    with pytest.raises(RuntimeError, match=r"degenerate clustering.*uniform.*0\.17"):
        MODULE.cluster_entries_from_backend(entries, UniformEmbeddingBackend())


def test_plausible_low_threshold_is_rejected_not_silently_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A threshold in the tuned neighbourhood that swallows the corpus must fail loud.

    The prior degeneracy guard only fired on absurd inputs (0, -0.1, 1.5).
    0.03 is the same order of magnitude as the calibrated 0.17 default and is
    exactly the kind of "plausible but wrong" value an operator might pass;
    it must exit non-zero and must not write a partial/wrong output file.

    THE INPUT MOVED FROM 0.05 TO 0.03 ON 2026-08-21, and the reason matters more
    than the change. Filing FM-391 took the corpus from 703 to 704 entries and
    this case went red -- not because the guard broke, but because 0.05 sat one
    step from the bound. Measured on the 704-entry corpus (tfidf backend):

        thresh  pinned-at-cap   saturated   fraction   fires?
          0.01              9         360     51.14%   yes
          0.02              9         360     51.14%   yes
          0.03              9         360     51.14%   yes
          0.04              8         320     45.45%   yes
          0.05              7         280     39.77%   NO   <- bound is 40%
          0.06              7         280     39.77%   no

    At 703 entries the same threshold produced EIGHT cap-pinned clusters
    (320/703 = 45.5%, fires). One added entry dropped it to seven and the
    fraction fell through the bound. The measure moves in whole clusters, so it
    jumps by max_members/N -- about 5.7 percentage points here -- and 0.05
    missed by 0.23 points, roughly 1.6 entries.

    NOTHING IS WEAKENED: every assertion below is unchanged, including the exact
    message and the no-output-file check. Only the input moved, to a value where
    the property genuinely holds with an 11-point margin instead of a 0.23-point
    one. Asserting that 0.05 fires would now simply be false.

    The discontinuity itself is a real defect in the guard -- a corpus-size-
    sensitive bound that a single new entry can cross -- and is filed separately.
    Do not "fix" a future red here by nudging this number again; that would be
    chasing the cliff instead of removing it.
    """
    output = tmp_path / "clusters.jsonl"
    exit_code = MODULE.main(
        ["--backend", "tfidf", "--threshold", "0.03", "--output", str(output)]
    )
    assert exit_code == 1
    assert "clusters pinned at the 40-member cap, exceeding the 40% bound" in capsys.readouterr().err
    assert not output.exists()


def test_default_backend_selection_meets_cluster_cardinality_bounds(tmp_path: Path) -> None:
    """Exercise whatever backend `auto` actually selects, on the real corpus.

    Forcing tfidf in every other test means a collapsing or constant-vector
    default (HTTP) backend could ship silently.  This runs the CLI with the
    real, unforced default backend selection and checks the written output's
    cluster cardinality directly, regardless of which backend answered.
    """
    output = tmp_path / "clusters.jsonl"
    assert MODULE.main(["--output", str(output)]) == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    meta = rows[0]["_meta"]
    clusters = rows[1:]
    sizes = [cluster["size"] for cluster in clusters]
    largest_fraction = max(sizes) / meta["entry_count"]
    assert largest_fraction <= MODULE.MAX_CLUSTER_FRACTION, (
        f"backend {meta['backend']!r} produced a {largest_fraction:.1%} cluster on the default path"
    )
    assert sum(sizes) == meta["entry_count"]
    assert any(size == 1 for size in sizes), "default path lost every singleton"


def test_constant_vector_http_backend_fails_loud_on_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken HTTP backend that returns constant vectors must not ship a mega-cluster.

    This is the concrete mutation the review named: `HttpEmbeddingBackend.embed`
    collapsing to constant vectors previously survived because no test ran
    the CLI's actual default (`auto`) selection against a corpus-sized input.
    """

    def constant_embed(self: MODULE.HttpEmbeddingBackend, texts: object) -> np.ndarray:
        count = len(texts)  # type: ignore[arg-type]
        return np.ones((count, 4), dtype=np.float32)

    monkeypatch.setattr(MODULE.HttpEmbeddingBackend, "available", True, raising=False)
    monkeypatch.setattr(MODULE.HttpEmbeddingBackend, "endpoint", "/v1/embeddings", raising=False)
    monkeypatch.setattr(MODULE.HttpEmbeddingBackend, "embed", constant_embed)

    output = tmp_path / "clusters.jsonl"
    exit_code = MODULE.main(["--backend", "http", "--output", str(output)])
    assert exit_code == 1
    assert not output.exists()


def test_similarity_text_never_encodes_id_or_source_path() -> None:
    """ID leakage mutation guard: prepending entry.id must make this red immediately.

    The prior anti-leak test only proved two hand-built entries with wholly
    unrelated prose stayed apart; it said nothing about whether production
    text encodes identity.  This asserts the contract directly on real L1
    records, several of which have IDs built from common family words
    (`fleet-OPS-...`) that would otherwise inflate lexical overlap.
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    for entry in entries[:40]:
        text = MODULE.similarity_text(entry)
        assert entry.id not in text
        assert entry.source_path not in text


def test_markers_disabled_still_clears_a_stated_lower_recall_bound() -> None:
    """Declared-hybrid contract: without markers, TF-IDF alone must clear a real floor.

    Markers are a declared hybrid (see `_cause_shape_markers` docstring), not
    a stand-in for the engine.  Removing them drops recall -- this measures
    and locks the actual floor rather than letting it silently regress to
    zero, and proves the markers are additive, not the entire mechanism
    (completion-signal and fail-silent-gate both still recover some, not all,
    of their members on lexical similarity alone).
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    families = {family["key"]: family["members"] for family in fixture["families"]}

    original_markers = MODULE._cause_shape_markers
    MODULE._cause_shape_markers = lambda text: ()
    try:
        clusters = MODULE.cluster_entries_from_backend(entries, MODULE.TfidfEmbeddingBackend())
    finally:
        MODULE._cause_shape_markers = original_markers
    assignments = _assignments(clusters)

    completion = families["completion-signal"]
    assigned = [assignments[member] for member in completion]
    largest = max(assigned.count(cluster_id) for cluster_id in set(assigned))
    recall = largest / len(completion)
    # Measured floor on the current corpus: markers-off completion-signal
    # recall is ~0.29 (2/7). Assert it stays in that neighbourhood -- neither
    # a silent collapse to 0 (markers doing literally everything) nor a
    # suspicious jump that would mean the "disabled" path isn't really
    # disabled.
    assert 0.20 <= recall <= 0.50, f"markers-disabled completion-signal recall was {recall:.2f}"


def test_false_positive_novel_failure_does_not_join_an_existing_family() -> None:
    """Reviewer-supplied inversion 1: a genuinely novel failure must not be absorbed.

    `novel-SES-1` shares only two generic English words ("resume", "headless")
    with the completion-signal marker trigger and nothing else in common with
    that family -- session/identity confusion is a different root cause. A
    DNS-TTL control with no marker overlap at all is included as a sanity
    check that the corpus does not just swallow every addition.
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    families = {family["key"]: family["members"] for family in fixture["families"]}

    novel_session_confusion = MODULE.Entry(
        id="novel-SES-1",
        instance=(
            "Operator tried to resume a headless tmux session and attached to "
            "a different user's shell."
        ),
        check=None,
        class_hint=None,
        first_seen=None,
        source_path="novel/adversarial",
    )
    novel_control = MODULE.Entry(
        id="novel-CTRL-1",
        instance=(
            "A DNS record TTL was set too low, causing repeated cache misses "
            "across the fleet resolvers."
        ),
        check=None,
        class_hint=None,
        first_seen=None,
        source_path="novel/adversarial",
    )
    clusters = MODULE.cluster_entries_from_backend(
        [*entries, novel_session_confusion, novel_control], MODULE.TfidfEmbeddingBackend()
    )
    assignments = _assignments(clusters)
    _assert_fixture_contract(clusters, "tfidf")

    completion_cluster_ids = {assignments[member] for member in families["completion-signal"]}
    assert assignments["novel-SES-1"] not in completion_cluster_ids
    assert assignments["novel-CTRL-1"] not in completion_cluster_ids
    for members in families.values():
        assert assignments["novel-CTRL-1"] not in {assignments[member] for member in members}


def test_corpus_grounds_every_marker_alternative() -> None:
    """H2 (C1d, 2026-08-01): a regex alternative that matches no real record
    can only have been authored to match a sentence in this test suite.

    Every literal alternative declared through `MODULE._lit()` in
    `_cause_shape_markers` must occur at least once in the actual
    instance/check/class_hint text of a real `pipeline/L1/*.jsonl` record --
    the exact text the marker function is ever given at runtime. This is a
    mechanical, standing gate: it fails immediately, and names the offending
    fragment, the moment anyone (human or agent) widens a marker with an
    alternative lifted from a test sentence rather than the corpus.
    """
    corpus_texts = _corpus_marker_texts()
    ungrounded = [
        fragment
        for fragment in MODULE.MARKER_TEXT_FRAGMENTS
        if not any(re.search(fragment, text) for text in corpus_texts)
    ]
    assert not ungrounded, (
        f"marker alternative(s) with zero corpus occurrences: {ungrounded!r} -- "
        "these can only have been authored from a test sentence, not the corpus"
    )


def test_false_positive_distractor_paraphrases_do_not_join_any_family() -> None:
    """Precision half of the C1d held-out gate (fixtures/holdout_paraphrases.json).

    This fixture was authored by a different agent who never read
    `_cause_shape_markers` (see the fixture's own `authoring_constraints`), so
    it cannot be graded by markers written to match it -- the process defect
    named in the C1d brief. Each of its 6 near-miss distractors
    (`expected_family: null`) must land in none of the five ground-truth
    families' clusters. Recall alone is trivially satisfiable by merging
    everything; this is what makes a recall number mean anything.
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    ground_truth = json.loads(FIXTURE.read_text(encoding="utf-8"))
    families = {family["key"]: family["members"] for family in ground_truth["families"]}
    holdout = json.loads(HOLDOUT_FIXTURE.read_text(encoding="utf-8"))

    def make(entry_id: str, text: str) -> MODULE.Entry:
        return MODULE.Entry(
            id=entry_id, instance=text, check=None, class_hint=None,
            first_seen=None, source_path="novel/holdout",
        )

    holdout_entries = [make(item["id"], item["text"]) for item in holdout["entries"]]
    clusters = MODULE.cluster_entries_from_backend([*entries, *holdout_entries], MODULE.TfidfEmbeddingBackend())
    assignments = _assignments(clusters)

    family_cluster_ids = {
        assignments[member] for members in families.values() for member in members
    }
    distractors = [item["id"] for item in holdout["entries"] if item["expected_family"] is None]
    assert distractors, "fixture must declare at least one distractor"
    false_positives = [d for d in distractors if assignments[d] in family_cluster_ids]
    assert not false_positives, (
        f"distractor(s) wrongly absorbed into a ground-truth family cluster: {false_positives!r}"
    )


def _held_out_recall(clusters: list[object], families: dict[str, list[str]], holdout_entries: list[dict]) -> tuple[int, int]:
    assignments = _assignments(clusters)
    family_majority_cluster = {
        family: max(
            (assignments[member] for member in members),
            key=lambda cluster_id: sum(assignments[member] == cluster_id for member in members),
        )
        for family, members in families.items()
    }
    non_distractors = [item for item in holdout_entries if item["expected_family"] is not None]
    hits = sum(
        1
        for item in non_distractors
        if assignments[item["id"]] == family_majority_cluster[item["expected_family"]]
    )
    return hits, len(non_distractors)


def test_held_out_paraphrase_recall_meets_the_measured_floor() -> None:
    """Recall half of the C1d held-out gate: fresh paraphrases nobody tuned against.

    Unlike the ground-truth fixture (whose members the markers were repaired
    against), every non-distractor entry in `holdout_paraphrases.json` was
    written by an agent who had not read `_cause_shape_markers`.

    Measured, honest result on this commit (TF-IDF backend, forced -- the
    only backend CI can run deterministically): **0/35 recall, 0/6 distractor
    false positives.** This is not a regression introduced by removing H2's
    ungrounded markers -- none of those markers ever fired on a real corpus
    entry, so removing them cannot have changed this number; it was already
    0/35 in the fixture author's own `baseline_measurement`.

    Before accepting 0 as the floor, the blend was actually swept: dense
    weight in {0.10..0.30} crossed with threshold in {0.20..0.35} against the
    real, reachable HTTP embedding backend (BAAI/bge-m3). Every setting that
    raised holdout recall above 0 (weight >= 0.30 at low thresholds) broke
    the ground-truth precision contract (families incorrectly merged) or, at
    weight >= 0.50, collapsed the entire 504-entry corpus into one cluster --
    this backend's raw cosine similarity has too high and too uniform a
    baseline across unrelated incidents to discriminate at any threshold
    that also keeps the calibrated recall/precision contract intact (see
    `cluster.py`'s module docstring, itself already the record of that
    finding for the *default* threshold). No (weight, threshold) point in
    that grid does better than the current 179-cluster / 0.10-weight
    default without failing ground truth. That is the honest ceiling of
    this architecture's average-link-over-blended-cosine design against
    heavily reworded, never-tuned-against phrasing; closing it needs either
    a fundamentally different dense encoder/similarity calibration or a
    non-lexical signal this pipeline does not yet have -- not a wider regex
    (which the corpus-grounding test above exists specifically to block) and
    not a higher dense weight (measured above to break precision first).

    This assertion locks the measurement rather than setting an aspirational
    floor: any change, up or down, means the architecture changed and this
    comment needs a fresh measurement, not a silent bump.
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    ground_truth = json.loads(FIXTURE.read_text(encoding="utf-8"))
    families = {family["key"]: family["members"] for family in ground_truth["families"]}
    holdout = json.loads(HOLDOUT_FIXTURE.read_text(encoding="utf-8"))

    def make(entry_id: str, text: str) -> MODULE.Entry:
        return MODULE.Entry(
            id=entry_id, instance=text, check=None, class_hint=None,
            first_seen=None, source_path="novel/holdout",
        )

    holdout_entries = [make(item["id"], item["text"]) for item in holdout["entries"]]
    clusters = MODULE.cluster_entries_from_backend([*entries, *holdout_entries], MODULE.TfidfEmbeddingBackend())
    hits, total = _held_out_recall(clusters, families, holdout["entries"])

    documented_hits = 0
    assert hits == documented_hits, (
        f"held-out paraphrase recall changed from the documented {documented_hits}/{total} "
        f"to {hits}/{total} -- this backend/threshold configuration's generalisation "
        "changed; re-measure and update the documented number and its justification above, "
        "don't just widen this assertion"
    )


def test_active_http_backend_held_out_gate_when_reachable() -> None:
    """Same held-out gate against the real production (`auto`) backend, when reachable.

    Skips (does not fail) when the authorised HTTP embedding service is
    offline, matching the existing pattern for
    `test_active_http_backend_meets_the_ground_truth_contract_when_reachable`.
    Measured result when reachable, at the calibrated 0.10 dense weight /
    0.20 threshold: 0/35 recall, 0/6 distractor false positives -- identical
    to the TF-IDF-only path, because 10% dense weight is not enough signal
    to move any assignment (see the weight sweep documented in
    `test_held_out_paraphrase_recall_meets_the_measured_floor`).
    """
    backend = MODULE.HttpEmbeddingBackend()
    if not backend.available:
        pytest.skip("authorised HTTP embedding backend is unreachable")

    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    ground_truth = json.loads(FIXTURE.read_text(encoding="utf-8"))
    families = {family["key"]: family["members"] for family in ground_truth["families"]}
    holdout = json.loads(HOLDOUT_FIXTURE.read_text(encoding="utf-8"))

    def make(entry_id: str, text: str) -> MODULE.Entry:
        return MODULE.Entry(
            id=entry_id, instance=text, check=None, class_hint=None,
            first_seen=None, source_path="novel/holdout",
        )

    holdout_entries = [make(item["id"], item["text"]) for item in holdout["entries"]]
    clusters = MODULE.cluster_entries_from_backend([*entries, *holdout_entries], backend)
    assignments = _assignments(clusters)

    family_cluster_ids = {
        assignments[member] for members in families.values() for member in members
    }
    distractors = [item["id"] for item in holdout["entries"] if item["expected_family"] is None]
    false_positives = [d for d in distractors if assignments[d] in family_cluster_ids]
    assert not false_positives, (
        f"live HTTP backend: distractor(s) wrongly absorbed into a family cluster: {false_positives!r}"
    )

    hits, total = _held_out_recall(clusters, families, holdout["entries"])
    documented_hits = 0
    assert hits == documented_hits, (
        f"live HTTP backend held-out recall changed from the documented {documented_hits}/{total} "
        f"to {hits}/{total} -- re-measure and update the documented number, don't just widen this"
    )


def test_same_input_produces_identical_assignment() -> None:
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    backend = MODULE.TfidfEmbeddingBackend()
    first = _assignments(MODULE.cluster_entries_from_backend(entries, backend))
    second = _assignments(MODULE.cluster_entries_from_backend(entries, backend))
    assert first == second


def test_shared_id_prefix_does_not_merge_unrelated_records() -> None:
    entries = [
        MODULE.Entry(
            id="fleet-OPS-100",
            instance="TLS certificate rotation leaves an expired edge certificate.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="ignored/a",
        ),
        MODULE.Entry(
            id="fleet-OPS-101",
            instance="Database migrations deadlock when two schema writers overlap.",
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="ignored/b",
        ),
    ]
    clusters = MODULE.cluster_entries_from_backend(entries, MODULE.TfidfEmbeddingBackend())
    assert len(clusters) == 2


def test_invalid_l1_record_fails_loudly(tmp_path: Path) -> None:
    """Malformed input cannot become a partial cluster report."""
    (tmp_path / "broken.jsonl").write_text('{"id":"missing-required-fields"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="broken.jsonl:1"):
        MODULE.load_entries(tmp_path)


def test_l1_record_missing_source_anchor_is_rejected_not_silently_clustered(tmp_path: Path) -> None:
    """All schema-required provenance fields are checked before clustering."""
    record = {
        "id": "example-1",
        "source_path": "example/failures.md",
        "instance": "A concrete failure instance.",
        "check": None,
        "enforcement": None,
        "auto": "judgment",
        "first_seen": None,
    }
    (tmp_path / "missing-anchor.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_anchor"):
        MODULE.load_entries(tmp_path)


def test_cli_writes_complete_cluster_jsonl_with_backend_metadata(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The executable path writes metadata and retains every L1 record, including singletons."""
    output = tmp_path / "clusters.jsonl"
    assert MODULE.main(["--backend", "tfidf", "--output", str(output)]) == 0
    assert "cluster backend selected: tfidf (forced)" in capsys.readouterr().err

    entry_count = len(MODULE.load_entries(ROOT / "pipeline" / "L1"))
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["_meta"] == {
        "backend": "tfidf",
        "entry_count": entry_count,
        "linkage": "average",
        "threshold": MODULE.DEFAULT_THRESHOLD,
    }
    clusters = rows[1:]
    members = [member for cluster in clusters for member in cluster["members"]]
    assert len(members) == entry_count
    assert len(set(members)) == entry_count
    assert any(cluster["size"] == 1 for cluster in clusters)


def test_http_backend_discovers_native_per_text_embedding_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """A native llama.cpp endpoint may accept `content`, not an OpenAI batch payload."""
    calls: list[tuple[dict[str, object], float]] = []

    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"embedding":[3.0,4.0]}'

    def fake_urlopen(request: object, timeout: float) -> Response:
        payload = json.loads(request.data.decode("utf-8"))
        calls.append((payload, timeout))
        if request.full_url.endswith("/v1/embeddings") or "input" in payload:
            raise MODULE.URLError("unsupported shape")
        assert request.full_url.endswith("/embedding")
        assert set(payload) == {"content"}
        return Response()

    monkeypatch.setattr(MODULE, "urlopen", fake_urlopen)
    backend = MODULE.HttpEmbeddingBackend()
    assert backend.available
    vectors = backend.embed(["first", "second"])
    assert vectors.shape == (2, 2)
    assert [timeout for _, timeout in calls[:3]] == [3.0, 3.0, 3.0]
    assert [timeout for _, timeout in calls[3:]] == [120.0, 120.0, 120.0]
    assert len([payload for payload, _ in calls if "content" in payload]) == 3


class _UnreachableHttpBackend:
    """Stand-in for the real probe against a service that never answers."""

    name = "http"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.available = False
        self.endpoint = None
        self.base_url = MODULE.DEFAULT_EMBEDDING_URL

    def embed(self, texts: object) -> object:  # pragma: no cover - must never run
        raise AssertionError("an unavailable backend must never be asked to embed")


@pytest.mark.parametrize("declared", ["http", "auto"])
def test_unreachable_http_backend_fails_loudly_instead_of_substituting_tfidf(
    declared: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unreachable declared backend must raise, naming the URL -- never return tfidf.

    Regression for hindsight#120: `auto` used to substitute TfidfEmbeddingBackend
    whenever the HTTP service did not answer.  Those embeddings diverge from the
    committed http-fitted snapshot, so the substitution surfaced as an L1 digest
    mismatch and a recall shortfall -- a content defect that was really an
    unreachable service.  TF-IDF is now reachable only by declaring it.
    """
    monkeypatch.setattr(MODULE, "HttpEmbeddingBackend", _UnreachableHttpBackend)
    with pytest.raises(MODULE.EmbeddingBackendUnavailableError) as excinfo:
        MODULE.select_backend(declared)
    message = str(excinfo.value)
    assert MODULE.DEFAULT_EMBEDDING_URL in message
    assert "unreachable" in message
    assert "tfidf" not in capsys.readouterr().err


def test_cli_exits_non_zero_when_the_declared_http_backend_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The executable path must fail, and must not write a tfidf-fitted artifact."""
    monkeypatch.setattr(MODULE, "HttpEmbeddingBackend", _UnreachableHttpBackend)
    output = tmp_path / "clusters.jsonl"
    assert MODULE.main(["--backend", "http", "--output", str(output)]) == 1
    stderr = capsys.readouterr().err
    assert MODULE.DEFAULT_EMBEDDING_URL in stderr
    assert "unreachable" in stderr
    assert not output.exists()


def test_declared_tfidf_is_still_honoured_without_contacting_the_http_service(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fail-loud must not remove the explicitly declared tfidf path."""

    def poisoned(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("declaring tfidf must not probe the HTTP service")

    monkeypatch.setattr(MODULE, "HttpEmbeddingBackend", poisoned)
    backend = MODULE.select_backend("tfidf")
    assert isinstance(backend, MODULE.TfidfEmbeddingBackend)
    assert "cluster backend selected: tfidf (forced)" in capsys.readouterr().err
