"""Acceptance tests for root-cause clustering.

The coordinator-authored fixture is deliberately read here rather than mirrored
in test data so this suite cannot silently grade a different contract.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Self

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "pipeline" / "tests" / "fixtures" / "recurrence_ground_truth.json"
MODULE_PATH = ROOT / "pipeline" / "cluster.py"
SPEC = importlib.util.spec_from_file_location("hindsight_cluster", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_clustering_engine_exists() -> None:
    """The L2 engine is an explicit pipeline stage, not an implicit script."""
    assert (ROOT / "pipeline" / "cluster.py").is_file()


def _assignments(clusters: list[object]) -> dict[str, str]:
    return {
        member: cluster.cluster_id
        for cluster in clusters
        for member in cluster.members
    }


def _assert_fixture_contract(clusters: list[object]) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assignments = _assignments(clusters)
    families = {family["key"]: family["members"] for family in fixture["families"]}

    for family, members in families.items():
        assigned = [assignments[member] for member in members]
        largest = max(assigned.count(cluster_id) for cluster_id in set(assigned))
        assert largest / len(members) >= fixture["assertions"]["recall"]["min_fraction_together"], family

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
    clusters = MODULE.cluster_entries(entries, MODULE.TfidfEmbeddingBackend())
    _assert_fixture_contract(clusters)


def test_each_backend_has_an_explicit_calibrated_default_threshold() -> None:
    """A dense embedding backend must not inherit sparse TF-IDF's cutoff."""
    assert MODULE.default_threshold("tfidf") == 0.17
    assert MODULE.default_threshold("http") == 0.20


def test_active_http_backend_meets_the_ground_truth_contract_when_reachable() -> None:
    """The live backend is exercised, or visibly reported as untested when offline."""
    backend = MODULE.HttpEmbeddingBackend()
    if not backend.available:
        pytest.skip("authorised HTTP embedding backend is unreachable")

    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    clusters = MODULE.cluster_entries(entries, backend)
    _assert_fixture_contract(clusters)


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
        MODULE.cluster_entries(entries, UniformEmbeddingBackend())


def test_same_input_produces_identical_assignment() -> None:
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    backend = MODULE.TfidfEmbeddingBackend()
    first = _assignments(MODULE.cluster_entries(entries, backend))
    second = _assignments(MODULE.cluster_entries(entries, backend))
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
    clusters = MODULE.cluster_entries(entries, MODULE.TfidfEmbeddingBackend())
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

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["_meta"] == {
        "backend": "tfidf",
        "entry_count": 458,
        "linkage": "average",
        "threshold": MODULE.DEFAULT_THRESHOLD,
    }
    clusters = rows[1:]
    members = [member for cluster in clusters for member in cluster["members"]]
    assert len(members) == 458
    assert len(set(members)) == 458
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
