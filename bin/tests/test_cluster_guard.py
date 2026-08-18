"""Runaway-cluster guard for the L2 clustering engine (hindsight#118).

Diagnosis under test (issue #118, 2026-08-18): linkage on a *fixed absolute*
similarity threshold chains records together, and the chaining accelerates as
the corpus grows -- the largest emitted cluster went from 26 members at 582
L1 entries to 83 at 671.  The visible symptom is recall (a ground-truth family
scattered across the wreckage); the quieter symptom is precision (two
hand-verified families welded into one cluster), which the existing contract
test masked because its recall assertion fired first.

This file asserts the *shape* invariants that a scale/density-aware linkage or
a cluster-diameter cap has to satisfy.  It deliberately does NOT assert a
threshold value, a linkage name, a constant name, or any other implementation
detail -- the issue rules out "lower the threshold" as the fix, so a test that
pinned the threshold would be grading the wrong thing.

Everything here is derived at runtime from two evidence sources:

  * ``pipeline/L1/*.jsonl``                       -- the live corpus
  * ``pipeline/tests/fixtures/recurrence_ground_truth.json``
                                                  -- the coordinator-authored
                                                     family fixture

If either evidence source is missing, incomplete, or (for the HTTP path)
unreachable, the affected test FAILS.  It never skips: a guard that quietly
stands down when it cannot see is indistinguishable from a guard that passed.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "pipeline" / "cluster.py"
L1_DIR = ROOT / "pipeline" / "L1"
FIXTURE = ROOT / "pipeline" / "tests" / "fixtures" / "recurrence_ground_truth.json"

_SPEC = importlib.util.spec_from_file_location("hindsight_cluster_guard_target", MODULE_PATH)
assert _SPEC and _SPEC.loader
MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = MODULE
_SPEC.loader.exec_module(MODULE)


# --------------------------------------------------------------------------
# Guard constants.
#
# Both bounds are expressed relative to evidence read at runtime, never as a
# literal cluster size, so they keep their meaning as the corpus grows -- which
# is the whole point of issue #118.
#
# SIZE: the largest family a human verified by reading the corpus has 7
# members.  A cluster five times larger than the biggest hand-verified family,
# or occupying more than 8% of the entire corpus, is not a recurrence family;
# it is the chaining artefact.  The looser of the two bounds is used so a
# genuinely large future family is not punished on a small corpus.
#
# DOMINANCE: chaining produces ONE runaway cluster while the rest of the
# partition stays sane, so the largest cluster towering over the second largest
# is the signature.  A healthy partition has a smooth head.  This bound is
# fully scale-free: it mentions neither the corpus size nor the fixture.
# --------------------------------------------------------------------------
GUARD_FAMILY_MULTIPLE = 5
GUARD_CORPUS_FRACTION = 0.08
GUARD_DOMINANCE_RATIO = 3.0


def _size_cap(entry_count: int, largest_ground_truth_family: int) -> int:
    return max(
        GUARD_FAMILY_MULTIPLE * largest_ground_truth_family,
        math.ceil(GUARD_CORPUS_FRACTION * entry_count),
    )


@lru_cache(maxsize=1)
def _fixture() -> dict:
    if not FIXTURE.is_file():
        pytest.fail(f"ground-truth fixture is missing: {FIXTURE}")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _families() -> dict[str, tuple[str, ...]]:
    families = {
        family["key"]: tuple(family["members"]) for family in _fixture()["families"]
    }
    if not families:
        pytest.fail("ground-truth fixture declares no families; the guard has no evidence")
    return families


@lru_cache(maxsize=1)
def _entries() -> tuple:
    if not L1_DIR.is_dir():
        pytest.fail(f"L1 corpus directory is missing: {L1_DIR}")
    entries = tuple(MODULE.load_entries(L1_DIR))
    if not entries:
        pytest.fail(f"L1 corpus at {L1_DIR} is empty; the guard has no evidence")
    return entries


@lru_cache(maxsize=1)
def _tfidf_clusters() -> tuple:
    return tuple(
        MODULE.cluster_entries_from_backend(list(_entries()), MODULE.TfidfEmbeddingBackend())
    )


# The backend's own liveness probe is capped at 3s by design, which a
# cold-started model server loses to.  Warm the endpoint with a generous
# timeout first so "unavailable" means genuinely unreachable rather than
# "slow to wake" -- otherwise this guard would report a flaky red instead of a
# real one.  Never the reverse: a warm-up that fails leaves the backend
# unavailable and the dependent tests fail.
HTTP_WARMUP_TIMEOUT = 90.0
HTTP_WARMUP_ATTEMPTS = 3


def _warm_http_endpoint() -> None:
    from urllib.request import Request, urlopen

    url = MODULE.DEFAULT_EMBEDDING_URL.rstrip("/") + "/v1/embeddings"
    payload = json.dumps({"input": ["hindsight cluster guard warm-up"]}).encode()
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=HTTP_WARMUP_TIMEOUT) as response:  # noqa: S310
        response.read()


@lru_cache(maxsize=1)
def _http_backend():
    backend = MODULE.HttpEmbeddingBackend()
    for _ in range(HTTP_WARMUP_ATTEMPTS):
        if getattr(backend, "available", False):
            return backend
        try:
            _warm_http_endpoint()
        except Exception:  # noqa: BLE001 - any failure means "still not up"
            pass
        backend = MODULE.HttpEmbeddingBackend()
    return backend


@lru_cache(maxsize=1)
def _http_clusters() -> tuple:
    backend = _http_backend()
    if not getattr(backend, "available", False):
        pytest.fail(
            "the HTTP embedding backend is unreachable, so the HTTP clustering path "
            "cannot be graded; this is an untested path, not a passing one"
        )
    return tuple(MODULE.cluster_entries_from_backend(list(_entries()), backend))


def _assignments(clusters) -> dict[str, str]:
    return {member: cluster.cluster_id for cluster in clusters for member in cluster.members}


def _sizes(clusters) -> list[int]:
    return sorted((cluster.size for cluster in clusters), reverse=True)


def _assert_precision_separations(clusters, backend_label: str) -> None:
    """Families the fixture says must stay apart may not share a cluster.

    Asserted BEFORE any size or recall statement so a precision violation is
    reported on its own terms instead of being masked by an earlier failure.
    """
    assignments = _assignments(clusters)
    families = _families()
    pairs = _fixture()["assertions"]["precision"]["must_not_merge"]
    assert pairs, "fixture declares no precision separations; the guard has no evidence"
    violations = []
    for left, right in pairs:
        left_ids = {assignments[member] for member in families[left]}
        right_ids = {assignments[member] for member in families[right]}
        shared = left_ids & right_ids
        if shared:
            violations.append((left, right, sorted(shared)))
    assert not violations, (
        f"[{backend_label}] distinct ground-truth causes were merged into one cluster: "
        f"{violations}"
    )


def _assert_no_runaway_cluster(clusters, backend_label: str) -> None:
    sizes = _sizes(clusters)
    entry_count = len(_entries())
    assert sum(sizes) == entry_count, (
        f"[{backend_label}] partition covers {sum(sizes)} of {entry_count} entries"
    )
    cap = _size_cap(entry_count, max(len(members) for members in _families().values()))
    assert sizes[0] <= cap, (
        f"[{backend_label}] largest cluster is {sizes[0]}/{entry_count} "
        f"({sizes[0] / entry_count:.1%}), above the runaway cap of {cap}"
    )


def _assert_head_is_not_dominated(clusters, backend_label: str) -> None:
    sizes = _sizes(clusters)
    assert len(sizes) >= 2, f"[{backend_label}] only one cluster emitted"
    if sizes[1] < 2:
        # Nothing but singletons behind the head: any multi-member head is by
        # definition a lone runaway.
        assert sizes[0] < 2, (
            f"[{backend_label}] a single cluster of {sizes[0]} sits on top of singletons"
        )
        return
    assert sizes[0] <= GUARD_DOMINANCE_RATIO * sizes[1], (
        f"[{backend_label}] largest cluster {sizes[0]} dwarfs the second largest "
        f"{sizes[1]} (ratio {sizes[0] / sizes[1]:.1f}x, limit {GUARD_DOMINANCE_RATIO}x); "
        "one runaway cluster over a healthy tail is the chaining signature"
    )


# --------------------------------------------------------------------------
# Evidence availability -- these must FAIL, never skip, when the guard is blind
# --------------------------------------------------------------------------
def test_guard_evidence_sources_are_present_and_complete() -> None:
    """Every ground-truth member must still exist in the corpus being graded.

    If a family member disappeared from L1, every assertion below would grade a
    silently shrunken contract and pass for the wrong reason.
    """
    entries = _entries()
    known = {entry.id for entry in entries}
    missing = {
        key: [member for member in members if member not in known]
        for key, members in _families().items()
    }
    missing = {key: value for key, value in missing.items() if value}
    assert not missing, f"ground-truth members absent from the L1 corpus: {missing}"
    assert len(known) == len(entries), "duplicate L1 ids would make assignments ambiguous"


def test_http_backend_evidence_source_is_reachable() -> None:
    """The HTTP path is one of the two paths #118 must hold on.

    An unreachable backend means that path was never graded.  Reporting that as
    a skip turns "we did not look" into a green tick, so it is a failure.
    """
    backend = _http_backend()
    assert getattr(backend, "available", False), (
        "authorised HTTP embedding backend is unreachable; the HTTP clustering "
        "path is UNTESTED, which this guard reports as a failure rather than a skip"
    )


# --------------------------------------------------------------------------
# Real corpus, offline TF-IDF path
# --------------------------------------------------------------------------
def test_tfidf_path_keeps_distinct_ground_truth_causes_apart() -> None:
    _assert_precision_separations(_tfidf_clusters(), "tfidf")


def test_tfidf_path_emits_no_runaway_cluster() -> None:
    _assert_no_runaway_cluster(_tfidf_clusters(), "tfidf")


def test_tfidf_path_head_is_not_dominated_by_one_cluster() -> None:
    _assert_head_is_not_dominated(_tfidf_clusters(), "tfidf")


# --------------------------------------------------------------------------
# Real corpus, HTTP backend path
# --------------------------------------------------------------------------
def test_http_path_keeps_distinct_ground_truth_causes_apart() -> None:
    _assert_precision_separations(_http_clusters(), "http")


def test_http_path_emits_no_runaway_cluster() -> None:
    _assert_no_runaway_cluster(_http_clusters(), "http")


def test_http_path_head_is_not_dominated_by_one_cluster() -> None:
    _assert_head_is_not_dominated(_http_clusters(), "http")


# --------------------------------------------------------------------------
# Synthetic geometry -- the mechanism, isolated from any corpus or backend
# --------------------------------------------------------------------------
def _synthetic(
    family_count: int,
    per_family: int,
    singletons: int,
    intra: float,
    inter: float,
) -> tuple[list, np.ndarray, list[str]]:
    """Build unit vectors with an exactly specified similarity structure.

    Each member is ``sqrt(inter) * common + sqrt(intra - inter) * family_axis +
    sqrt(1 - intra) * own_axis`` over orthonormal axes, so two members of the
    same family have cosine ``intra``, two members of different families have
    cosine ``inter``, and the padding singletons are orthogonal to everything.
    """
    assert 0.0 < inter < intra < 1.0
    common_w = math.sqrt(inter)
    family_w = math.sqrt(intra - inter)
    own_w = math.sqrt(1.0 - intra)
    total = family_count * per_family + singletons
    dimensions = 1 + family_count + total
    vectors = np.zeros((total, dimensions), dtype=np.float64)
    names: list[str] = []
    row = 0
    for family in range(family_count):
        for member in range(per_family):
            vectors[row, 0] = common_w
            vectors[row, 1 + family] = family_w
            vectors[row, 1 + family_count + row] = own_w
            names.append(f"fam{family:02d}-{member:03d}")
            row += 1
    for index in range(singletons):
        vectors[row, 1 + family_count + row] = 1.0
        names.append(f"zzz-solo-{index:04d}")
        row += 1

    order = sorted(range(total), key=lambda position: names[position])
    vectors = vectors[order]
    names = [names[position] for position in order]
    entries = [
        MODULE.Entry(
            id=name,
            instance=f"synthetic root cause record {name}",
            check=None,
            class_hint=None,
            first_seen="2026-01-01",
            source_path="synthetic/records.jsonl",
        )
        for name in names
    ]
    return entries, vectors, names


def _synthetic_partition(
    family_count: int,
    per_family: int = 10,
    intra: float = 0.90,
    inter: float = 0.18,
    occupancy: float = 0.35,
    expect_above_threshold: bool = True,
):
    """Cluster a synthetic corpus, padded so the existing degeneracy cap cannot
    be what does the work: even total collapse of every family stays at
    ``occupancy`` of the corpus, well inside the engine's own coarse bound."""
    families_total = family_count * per_family
    singletons = max(0, math.ceil(families_total / occupancy) - families_total)
    entries, vectors, _ = _synthetic(family_count, per_family, singletons, intra, inter)
    threshold = MODULE.default_threshold("tfidf")
    assert (inter > threshold) is expect_above_threshold, (
        "the synthetic geometry must sit on the intended side of the absolute "
        f"threshold {threshold}; inter-family similarity is {inter}"
    )
    return MODULE.cluster_entries(entries, vectors, "tfidf", threshold)


def _family_of(member: str) -> str | None:
    return member.split("-")[0] if member.startswith("fam") else None


def test_a_weak_absolute_link_does_not_fuse_strongly_distinct_causes() -> None:
    """Members 5x more similar to their own family than to any other family
    must not share a cluster, even though the cross-family similarity clears
    the fixed absolute threshold. This is the precision half of #118 in
    isolation: the threshold is absolute, the evidence is relative."""
    clusters = _synthetic_partition(family_count=8)
    mixed = {
        cluster.cluster_id: sorted(
            {label for label in map(_family_of, cluster.members) if label}
        )
        for cluster in clusters
    }
    mixed = {key: value for key, value in mixed.items() if len(value) > 1}
    assert not mixed, (
        "clusters fused distinct synthetic causes whose intra-family similarity "
        f"is five times their inter-family similarity: {mixed}"
    )


def test_adding_more_distinct_causes_does_not_enlarge_the_largest_cluster() -> None:
    """The scale half of #118, with nothing hardcoded about today's corpus.

    Each added family is a genuinely different cause. Growing the corpus with
    different causes must grow the NUMBER of clusters, never the size of the
    biggest one. A fixed absolute threshold fails this by construction: every
    new family is swallowed by the same runaway cluster.
    """
    measurements = {
        family_count: max(cluster.size for cluster in _synthetic_partition(family_count))
        for family_count in (2, 4, 8)
    }
    smallest_corpus = measurements[2]
    largest_corpus = measurements[8]
    assert largest_corpus <= smallest_corpus, (
        "largest cluster grew as unrelated causes were added to the corpus "
        f"(largest cluster by family count: {measurements}); clustering is "
        "chaining on corpus density rather than on evidence"
    )


def test_the_synthetic_probe_can_report_a_clean_partition() -> None:
    """Anti-vacuity control: the same probe, with the cross-family similarity
    moved BELOW the absolute threshold, must report no mixing and no growth --
    proving the two assertions above can be satisfied and are measuring the
    geometry rather than always failing."""
    clean = {
        family_count: _synthetic_partition(
            family_count=family_count, inter=0.02, expect_above_threshold=False
        )
        for family_count in (2, 8)
    }
    for family_count, clusters in clean.items():
        labels = Counter()
        for cluster in clusters:
            found = {label for label in map(_family_of, cluster.members) if label}
            assert len(found) <= 1, (
                f"control probe mixed families at family_count={family_count}: {found}"
            )
            labels.update(found)
        assert set(labels) == {f"fam{index:02d}" for index in range(family_count)}
    assert max(c.size for c in clean[8]) <= max(c.size for c in clean[2])
