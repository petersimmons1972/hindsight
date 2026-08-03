"""Acceptance tests for root-cause clustering.

The coordinator-authored fixture is deliberately read here rather than mirrored
in test data so this suite cannot silently grade a different contract.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Self

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


def _write_snapshot(path: Path, *, backend: dict[str, object], vectors: dict[str, list[float]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "hindsight.embedding-snapshot/v1",
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

    replay_matrix = MODULE.load_embedding_snapshot(snapshot, entries, identity)
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
        MODULE.load_embedding_snapshot(snapshot, entries, identity)


def test_snapshot_zero_overlap_alarms_and_names_both_id_sets(tmp_path: Path) -> None:
    entries = _snapshot_entries()
    identity = {"name": "http", "model": "model", "revision": "rev", "dimensions": 2}
    snapshot = tmp_path / "embedding-snapshot.json"
    _write_snapshot(snapshot, backend=identity, vectors={"foreign-a": [1.0, 0.0], "foreign-b": [0.0, 1.0]})

    with pytest.raises(
        ValueError,
        match=r"ALARM: zero ID overlap.*snapshot-a.*snapshot-b.*snapshot-c.*foreign-a.*foreign-b",
    ):
        MODULE.load_embedding_snapshot(snapshot, entries, identity)


def test_committed_snapshot_covers_the_current_l1_corpus_exactly() -> None:
    entries = MODULE.load_entries(ROOT / "pipeline" / "L1")
    matrix = MODULE.load_embedding_snapshot(
        ROOT / "pipeline" / "L2" / "embedding-snapshot.json",
        entries,
        MODULE.HTTP_BACKEND_IDENTITY,
    )

    assert matrix.shape == (len(entries), 1024)


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
    clusters = MODULE.cluster_entries_from_backend(entries, MODULE.TfidfEmbeddingBackend())
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
    clusters = MODULE.cluster_entries_from_backend(entries, backend)
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
        MODULE.cluster_entries_from_backend(entries, UniformEmbeddingBackend())


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
    _assert_fixture_contract(clusters)

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
