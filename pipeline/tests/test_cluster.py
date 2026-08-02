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


def test_plausible_low_threshold_is_rejected_not_silently_written(tmp_path: Path) -> None:
    """A threshold in the tuned neighbourhood that swallows the corpus must fail loud.

    The prior degeneracy guard only fired on absurd inputs (0, -0.1, 1.5).
    0.05 is the same order of magnitude as the calibrated 0.17 default and is
    exactly the kind of "plausible but wrong" value an operator might pass;
    it must exit non-zero and must not write a partial/wrong output file.
    """
    output = tmp_path / "clusters.jsonl"
    exit_code = MODULE.main(
        ["--backend", "tfidf", "--threshold", "0.05", "--output", str(output)]
    )
    assert exit_code == 1
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
        clusters = MODULE.cluster_entries(entries, MODULE.TfidfEmbeddingBackend())
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
    clusters = MODULE.cluster_entries(
        [*entries, novel_session_confusion, novel_control], MODULE.TfidfEmbeddingBackend()
    )
    assignments = _assignments(clusters)
    _assert_fixture_contract(clusters)

    completion_cluster_ids = {assignments[member] for member in families["completion-signal"]}
    assert assignments["novel-SES-1"] not in completion_cluster_ids
    assert assignments["novel-CTRL-1"] not in completion_cluster_ids
    for members in families.values():
        assert assignments["novel-CTRL-1"] not in {assignments[member] for member in members}


def test_false_negative_paraphrased_family_members_still_join_their_family() -> None:
    """Reviewer-supplied inversion 2: known duplicate shapes must not read as novel.

    These paraphrase the completion-signal and fail-silent-gate definitions
    (a claimed-done signal contradicted by an absent deliverable; a real
    failure silently reported as green) without using any of the reviewer's
    or fixture's exact wording -- `held-COMP-*` in particular were authored
    fresh for this test, never used to tune `_cause_shape_markers`.
    """
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    families = {family["key"]: family["members"] for family in fixture["families"]}

    def make(entry_id: str, instance: str) -> MODULE.Entry:
        return MODULE.Entry(
            id=entry_id,
            instance=instance,
            check=None,
            class_hint=None,
            first_seen=None,
            source_path="novel/paraphrase",
        )

    paraphrases = [
        make(
            "fn-COMP-1",
            "The agent claimed the task was finished, but the file it was "
            "supposed to create never appeared on disk.",
        ),
        make(
            "fn-COMP-2",
            "Automation said success while the expected output directory "
            "stayed empty the whole time.",
        ),
        make(
            "fn-COMP-3",
            "Worker process announced done; the promised patch set was "
            "absent from the branch.",
        ),
        make(
            "fn-COMP-4",
            "Subagent printed complete in the log, yet the PR body it owed "
            "never got opened.",
        ),
        make(
            "fn-GATE-1",
            "Missing credentials made the checker crash; dashboard painted "
            "the cell green anyway.",
        ),
        make(
            "fn-GATE-2",
            "Network blip during the probe was swallowed; operators saw "
            "only a soft skip, not a red failure.",
        ),
        # Held-out: authored independently of the reviewer's wording, to
        # prove this generalises from the family's stated definition rather
        # than being tuned to these exact sentences.
        make(
            "held-COMP-1",
            "The pipeline reported the export as finished, yet the "
            "destination bucket had zero new objects.",
        ),
        make(
            "held-COMP-2",
            "The runner logged a green summary line although the changelog "
            "entry it promised was never committed.",
        ),
    ]

    clusters = MODULE.cluster_entries([*entries, *paraphrases], MODULE.TfidfEmbeddingBackend())
    assignments = _assignments(clusters)
    _assert_fixture_contract(clusters)

    completion = families["completion-signal"]
    comp_cluster = max(
        (assignments[member] for member in completion),
        key=lambda cluster_id: sum(assignments[member] == cluster_id for member in completion),
    )
    gate = families["fail-silent-gate"]
    gate_cluster = max(
        (assignments[member] for member in gate),
        key=lambda cluster_id: sum(assignments[member] == cluster_id for member in gate),
    )

    for entry_id in ("fn-COMP-1", "fn-COMP-2", "fn-COMP-3", "fn-COMP-4", "held-COMP-1", "held-COMP-2"):
        assert assignments[entry_id] == comp_cluster, entry_id
    for entry_id in ("fn-GATE-1", "fn-GATE-2"):
        assert assignments[entry_id] == gate_cluster, entry_id


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
