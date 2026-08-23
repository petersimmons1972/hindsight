"""Cluster normalized failure records by their underlying root cause.

The L2 stage makes repeated incidents measurable without grouping by source
identity, which would reproduce the discoverer-coupled dedup defect it exists
to prevent.  Average-link agglomeration is used instead of single-link: a new
member must resemble a cluster as a whole, preventing one vague bridge record
from chaining two otherwise distinct causes together.

Thresholds are calibrated per backend because cosine values from the local
dense service have a much higher baseline than sparse TF-IDF.  On 2026-08-01,
the authorised HTTP endpoint clustered all 458 L1 entries at raw cosine 0.17;
no raw-dense threshold recovered every fixture family without an incorrect
merge.  At the current 683-entry corpus, the 0.10 dense / 0.90 lexical blend
at 0.20 let a 98-member average-link cluster join a completion-signal incident
to shared-checkout incidents.  Raising the HTTP cutoff to 0.22 is the first
measured 0.005 increment that restores every required precision separation
while preserving every recorded HTTP recall baseline; 0.225 regresses
dedup-identity-key recall.  The sparse TF-IDF default remains 0.17.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import numpy as np

BACKEND_DEFAULT_THRESHOLDS = {"tfidf": 0.17, "http": 0.22}
# Retained as the sparse fallback's public compatibility constant.  Call
# default_threshold() for a selected backend rather than reusing this value.
DEFAULT_THRESHOLD = BACKEND_DEFAULT_THRESHOLDS["tfidf"]
DEFAULT_EMBEDDING_URL = "http://leviathan.petersimmons.com:8004"
LINKAGE = "average"
HTTP_DENSE_WEIGHT = 0.10
MAX_CLUSTER_FRACTION = 0.40
# Hard ceiling on how many members one cluster may hold, enforced during
# agglomeration rather than checked afterwards.  A large average-link cluster
# becomes a sink: each accepted member shifts its aggregate similarity surface
# and can make an unrelated boundary member look admissible.  The 40-member
# bound is deliberately absolute: it keeps a recurrence family reviewable as
# the corpus grows, while leaving ample headroom over the seven-member largest
# ground-truth family.
MAX_CLUSTER_MEMBERS = 40
# Seven independent clusters at the hard 40-member ceiling means 280 records
# were stopped by the cap rather than separated by the threshold.  That is a
# threshold failure even if a growing tail of singletons dilutes the aggregate
# fraction below its corpus-relative bound.
MAX_PINNED_CLUSTERS = 6
REQUIRED_FIELDS = frozenset(
    {"id", "source_path", "source_anchor", "instance", "check", "enforcement", "auto", "first_seen"}
)
WORD_SLOTS = 4_096
CHAR_SLOTS = 16_384
TOKEN_RE = re.compile(r"[a-z0-9]+")
SPACE_RE = re.compile(r"\s+")
STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
        "is", "it", "its", "of", "on", "or", "that", "the", "their", "this", "to", "was",
        "were", "with", "when", "while", "will", "would", "not", "no", "only", "all", "any",
    }
)


class InvalidL1RecordError(ValueError):
    """A JSONL value is syntactically valid but violates the L1 contract."""


class EmbeddingProtocolError(ValueError):
    """The optional embedding service returned a response outside its contract."""


SNAPSHOT_SCHEMA = "hindsight.embedding-snapshot/v3"
SNAPSHOT_BACKEND_FIELDS = frozenset({"name", "model", "revision", "dimensions"})
SNAPSHOT_PROVENANCE_FIELDS = frozenset({"l1_sha256", "cluster_sha256"})
HTTP_BACKEND_IDENTITY: dict[str, object] = {
    "name": "http",
    "model": "BAAI/bge-m3",
    "revision": "bge-m3-Q8_0.gguf",
    "dimensions": 1024,
}
CLUSTER_CONFIG: dict[str, object] = {
    "backend_default_thresholds": BACKEND_DEFAULT_THRESHOLDS,
    "linkage": LINKAGE,
    "http_dense_weight": HTTP_DENSE_WEIGHT,
    "max_cluster_fraction": MAX_CLUSTER_FRACTION,
    "max_cluster_members": MAX_CLUSTER_MEMBERS,
    "max_pinned_clusters": MAX_PINNED_CLUSTERS,
}


def default_threshold(backend_name: str) -> float:
    """Return the calibrated threshold for a known backend or sparse fallback."""
    return BACKEND_DEFAULT_THRESHOLDS.get(backend_name, DEFAULT_THRESHOLD)


@dataclass(frozen=True)
class Entry:
    """The L1 fields that are safe and useful for similarity."""

    id: str
    instance: str
    check: str | None
    class_hint: str | None
    first_seen: str | None
    source_path: str


@dataclass(frozen=True)
class Cluster:
    """A stable, serialisable L2 cluster."""

    cluster_id: str
    members: tuple[str, ...]
    source_repos: tuple[str, ...]
    first_seen: str | None
    last_seen: str | None
    representative: str
    label: str

    @property
    def size(self) -> int:
        return len(self.members)

    def as_json(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "size": self.size,
            "members": list(self.members),
            "source_repos": list(self.source_repos),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "representative": self.representative,
            "label": self.label,
        }


class EmbeddingBackend(Protocol):
    """A local vector representation provider."""

    name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return one L2-normalised vector per supplied text."""


def load_entries(directory: Path) -> list[Entry]:
    """Read every L1 record, rejecting malformed input rather than skipping it."""
    files = sorted(directory.glob("*.jsonl"))
    if not files:
        raise ValueError(f"no JSONL inputs found in {directory}")

    entries: list[Entry] = []
    seen_ids: set[str] = set()
    for path in files:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                raise ValueError(f"{path.name}:{line_number}: blank JSONL line is not permitted")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise InvalidL1RecordError(f"{path.name}:{line_number}: record must be an object")
            missing = REQUIRED_FIELDS.difference(record)
            if missing:
                raise ValueError(f"{path.name}:{line_number}: missing required fields {sorted(missing)}")
            if not isinstance(record["id"], str) or not record["id"]:
                raise ValueError(f"{path.name}:{line_number}: id must be a non-empty string")
            if record["id"] in seen_ids:
                raise ValueError(f"{path.name}:{line_number}: duplicate id {record['id']}")
            if not isinstance(record["instance"], str) or not record["instance"].strip():
                raise ValueError(f"{path.name}:{line_number}: instance must be a non-empty string")
            if not isinstance(record["source_path"], str) or not record["source_path"].strip():
                raise ValueError(f"{path.name}:{line_number}: source_path must be a non-empty string")
            if not isinstance(record["source_anchor"], str) or not record["source_anchor"].strip():
                raise ValueError(f"{path.name}:{line_number}: source_anchor must be a non-empty string")
            for nullable in ("check", "class_hint", "first_seen"):
                if nullable in record and record[nullable] is not None and not isinstance(record[nullable], str):
                    raise ValueError(f"{path.name}:{line_number}: {nullable} must be string or null")
            if record["enforcement"] is not None and not isinstance(record["enforcement"], dict):
                raise ValueError(f"{path.name}:{line_number}: enforcement must be an object or null")
            if record["auto"] not in {"machine", "judgment"}:
                raise ValueError(f"{path.name}:{line_number}: auto must be machine or judgment")
            seen_ids.add(record["id"])
            entries.append(
                Entry(
                    id=record["id"],
                    instance=record["instance"],
                    check=record["check"],
                    class_hint=record.get("class_hint"),
                    first_seen=record["first_seen"],
                    source_path=record["source_path"],
                )
            )
    if not entries:
        raise ValueError(f"no L1 records found in {directory}")
    return sorted(entries, key=lambda entry: entry.id)


def _digest_named_bytes(items: Sequence[tuple[str, bytes]]) -> str:
    """Hash unambiguous path/content frames in caller-provided canonical order."""
    digest = hashlib.sha256()
    for name, content in items:
        name_bytes = name.encode("utf-8")
        digest.update(len(name_bytes).to_bytes(8, "big"))
        digest.update(name_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def l1_corpus_digest(directory: Path) -> str:
    """Digest every canonical on-disk L1 JSONL input, including its filename."""
    files = sorted(directory.glob("*.jsonl"))
    if not files:
        raise ValueError(f"no JSONL inputs found in {directory}")
    return _digest_named_bytes([(path.name, path.read_bytes()) for path in files])


def cluster_code_config_digest(cluster_code: Path) -> str:
    """Digest clustering implementation bytes and its explicit canonical config."""
    config = json.dumps(CLUSTER_CONFIG, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return _digest_named_bytes([("cluster.py", cluster_code.read_bytes()), ("cluster-config.json", config)])


def similarity_text(entry: Entry) -> str:
    """Weight incident descriptions above checks without using source identity."""
    # Do not add id or source_path here.  They are metadata, not evidence of a
    # common cause, and would make source-local records spuriously look related.
    parts = [entry.instance, entry.instance, entry.instance]
    if entry.check:
        parts.append(entry.check)
    if entry.class_hint:
        parts.append(entry.class_hint)
    # TF-IDF cannot infer that several strongly different surface descriptions
    # all mean a reported state disagreed with an observed result.  Add a few
    # narrow, text-derived cause-shape markers to bridge those expressions.  The
    # rules deliberately inspect only the permitted text fields; IDs and source
    # paths are never consulted or encoded.
    markers = _cause_shape_markers(" ".join(parts))
    parts.extend(marker for marker in markers for _ in range(12))
    return " ".join(parts)


def similarity_text_digest(entry: Entry) -> str:
    """Identify the exact text whose dense vector the snapshot records."""
    return hashlib.sha256(similarity_text(entry).encode("utf-8")).hexdigest()


MARKER_TEXT_FRAGMENTS: list[str] = []


def _lit(*fragments: str) -> tuple[str, ...]:
    """Declare the literal regex alternatives one marker condition requires.

    Every fragment declared here is registered in `MARKER_TEXT_FRAGMENTS` and
    is checked by `test_corpus_grounds_every_marker_alternative` in
    `test_cluster.py` against the real `instance`/`check`/`class_hint` text of
    every `pipeline/L1/*.jsonl` record -- the only fields a marker is ever
    allowed to read.  A fragment grounded nowhere in that corpus can only have
    been authored to match a sentence in the test suite rather than a real
    incident: an adversarial review (C1d, 2026-08-01) found exactly that --
    `zero new`, `painted`, `stayed empty`, and `never got opened`/`committed`
    occurred zero times across all 463 corpus entries and existed solely to
    satisfy sentences the review itself had written in `test_cluster.py`. They
    have been removed below, not widened; do not re-add an alternative here
    without it clearing the grounding test on real L1 text first.

    Write each fragment as a complete, self-contained regex (its own `\b`
    boundaries) so the grounding test can search it independently, and so the
    same fragment is what the runtime actually matches -- one source of
    truth, not a registry that can drift from the matcher.
    """
    MARKER_TEXT_FRAGMENTS.extend(fragments)
    return fragments


def _any(fragments: Sequence[str], text: str) -> bool:
    return any(re.search(fragment, text) for fragment in fragments)


_EXIT_ARTIFACT = _lit(r"\bembedded\s+0\b", r"\bartifact\b", r"\bledger\b")
_FORCED_STATE = _lit(r"\bforced.early\b", r"\bwrong.state\b")
_NO_DELIVERABLE = _lit(r"\bno deliverable\b", r"\bnothing\b")
_RESUME_SILENT = _lit(r"\bnothing\b", r"\bnever\b", r"\bno output\b", r"\bsilent\b", r"\blogged only\b")
_DEAD_LATE = _lit(r"\blate\b", r"\boverwrit")
_CLAIM_WORDS = _lit(r"\bclaimed\b", r"\bannounced\b", r"\bsaid\b", r"\bprinted\b", r"\breported\b", r"\blogged\b")
_DONE_WORDS = _lit(r"\bfinished\b", r"\bdone\b", r"\bcomplete\b", r"\bsuccess\b", r"\bgreen\b")
# `opened`/`committed` and `stayed empty`/`zero new` were the exact ungrounded
# branches H2 named -- removed, leaving only the one nested variant
# (`appeared`) that is genuinely present in the corpus (fleet-CI-1).
_ABSENT_DELIVERABLE = _lit(r"\bnever\s+(got\s+)?appeared\b", r"\babsent\b", r"\bempty\b", r"\bnothing\b")

_EXIT_FAIL_STATUS = _lit(r"\bfail\b", r"\bstatus\b")
_DEP_CODE = _lit(r"\b404\b", r"\bunreachable\b")
# `not.quite.matching` was ungrounded -- it only ever occurred in an L1
# `source_anchor` field, which markers never read; removed.
_GATE_UNPARSEABLE = _lit(r"\bunparseable\b", r"\bnever appeared\b")
_CRASH_WORDS = _lit(r"\bcrash\b", r"\bcrashed\b")
# `painted` was ungrounded -- removed.
_GREEN_WORDS = _lit(r"\bgreen\b", r"\bpassed\b")
# Prefix, not `\b(swallow|swallowed)\b`: the trailing boundary in the original
# regex could never match "swallowed" (no boundary between "swallow" and
# "ed"), so the alternative was silently dead weight. One prefix fragment
# covers both real inflections without adding a second, narrower literal.
_SWALLOW_WORD = _lit(r"\bswallow")

_CLAIM_DOCTRINE = _lit(r"\bclaim\b", r"\bdoctrine\b")
_INDEP_SHARED = _lit(r"\bindependent\b", r"\bshared\b")


def _cause_shape_markers(text: str) -> tuple[str, ...]:
    """Return conservative semantic normalisations for recurring cause shapes.

    These are a declared hybrid, not pure embedding similarity: TF-IDF alone
    cannot infer that several very differently-worded incidents share one
    root cause, so a short list of conservative, multi-condition regexes
    bridges that gap.  Every OR-alternative used below is declared through
    `_lit()` and mechanically checked against real corpus text (see
    `MARKER_TEXT_FRAGMENTS` and its docstring) -- a condition that only ever
    matched sentences in this test suite is the exact defect an adversarial
    review (H2, C1d) found and this refactor exists to close.
    """
    lower = text.lower()
    markers: list[str] = []
    completion_gap = (
        (re.search(r"\bexit(?:ed)?\s+0\b", lower) and _any(_EXIT_ARTIFACT, lower)) or
        (re.search(r"\breport\b", lower) and _any(_FORCED_STATE, lower)) or
        (re.search(r"\bcompletion", lower) and _any(_NO_DELIVERABLE, lower)) or
        (re.search(r"\bresume\b", lower) and re.search(r"\bheadless\b", lower) and
         _any(_RESUME_SILENT, lower)) or
        (re.search(r"\bdeemed dead\b", lower) and _any(_DEAD_LATE, lower)) or
        # The family's own stated shape: a claimed-done signal contradicted
        # by a deliverable that never materialised.  Written from that
        # definition, not from any one incident's wording -- it must also
        # catch paraphrases nobody tuned it against.
        (_any(_CLAIM_WORDS, lower) and _any(_DONE_WORDS, lower) and _any(_ABSENT_DELIVERABLE, lower))
    )
    if completion_gap:
        markers.append("latentcompletiongap")

    broken_gate = (
        re.search(r"\bran_ok\b", lower) or
        (re.search(r"\bexit(?:ed)?\s+0\b", lower) and _any(_EXIT_FAIL_STATUS, lower)) or
        (re.search(r"\bdependency\b", lower) and _any(_DEP_CODE, lower) and
         re.search(r"\breject\b", lower)) or
        (re.search(r"\bgate\b", lower) and _any(_GATE_UNPARSEABLE, lower)) or
        # A failure was observed (crash/error, or swallowed and downgraded
        # to a soft skip) but the reported/displayed result stayed green --
        # the family's stated shape, not a single incident's exact prose.
        (_any(_CRASH_WORDS, lower) and _any(_GREEN_WORDS, lower)) or
        (_any(_SWALLOW_WORD, lower) and re.search(r"\bskip\b", lower) and
         re.search(r"\bnot\b.*\b(red|fail)\b", lower))
    )
    if broken_gate:
        markers.append("latentbrokengate")

    nonindependent_evidence = (
        (re.search(r"\bnegative.search\b", lower) and _any(_CLAIM_DOCTRINE, lower)) or
        (re.search(r"\bconverg", lower) and _any(_INDEP_SHARED, lower))
    )
    if nonindependent_evidence:
        markers.append("latentnonindependentevidence")
    return tuple(markers)


def _stable_slot(prefix: str, value: str, slots: int) -> int:
    digest = hashlib.blake2b(f"{prefix}:{value}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % slots


def _normalise_token(token: str) -> str:
    """Use deliberately small stemming to align ordinary inflections."""
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


class TfidfEmbeddingBackend:
    """Dependency-free hashed character and word TF-IDF representation."""

    name = "tfidf"

    def _feature_counts(self, text: str) -> dict[int, float]:
        lower = SPACE_RE.sub(" ", text.lower())
        counts: dict[int, float] = {}
        for token in TOKEN_RE.findall(lower):
            token = _normalise_token(token)
            if token in STOP_WORDS or len(token) < 2:
                continue
            slot = _stable_slot("word", token, WORD_SLOTS)
            counts[slot] = counts.get(slot, 0.0) + 1.0

        compact = re.sub(r"[^a-z0-9 ]", " ", lower)
        for width in range(3, 6):
            for start in range(max(0, len(compact) - width + 1)):
                ngram = compact[start:start + width]
                if ngram.isspace():
                    continue
                slot = WORD_SLOTS + _stable_slot("char", ngram, CHAR_SLOTS)
                counts[slot] = counts.get(slot, 0.0) + 0.22
        return counts

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, WORD_SLOTS + CHAR_SLOTS), dtype=np.float32)
        counts_by_text = [self._feature_counts(text) for text in texts]
        dimensions = WORD_SLOTS + CHAR_SLOTS
        document_frequency = np.zeros(dimensions, dtype=np.int32)
        for counts in counts_by_text:
            document_frequency[list(counts)] += 1
        idf = np.log((len(texts) + 1) / (document_frequency + 1)) + 1.0
        matrix = np.zeros((len(texts), dimensions), dtype=np.float32)
        for row, counts in enumerate(counts_by_text):
            slots = list(counts)
            matrix[row, slots] = [math.log1p(counts[slot]) * idf[slot] for slot in slots]
        norms = np.linalg.norm(matrix, axis=1)
        nonzero = norms > 0
        matrix[nonzero] /= norms[nonzero, None]
        return matrix


class HttpEmbeddingBackend:
    """Best-effort adapter for the authorised local embedding service.

    Construction probes the two supported endpoint shapes and leaves the object
    unavailable on every network or protocol failure.  That makes auto-selection
    explicit rather than turning an unavailable optional service into a pipeline
    crash.
    """

    name = "http"

    def __init__(
        self,
        base_url: str = DEFAULT_EMBEDDING_URL,
        timeout: float = 3.0,
        request_timeout: float = 120.0,
    ) -> None:
        parsed = urlsplit(base_url)
        self.available = False
        self.endpoint: str | None = None
        self.base_url = base_url.rstrip("/")
        # Liveness must be cheap: an unreachable host should not stall startup,
        # but a real embedding can legitimately take longer than a connection
        # probe.  Keep those budgets separate (hindsight#147).
        self.probe_timeout = min(max(timeout, 0.1), 3.0)
        self.request_timeout = max(request_timeout, self.probe_timeout)
        if parsed.scheme != "http" or parsed.hostname != "leviathan.petersimmons.com":
            return
        if self._models_available():
            self.endpoint = "/v1/embeddings"
            self.available = True
            return
        # The OpenAI-compatible endpoint has no native fallback: if its batch
        # request is not accepted, probe the native endpoint separately.
        # This makes the discovery budget exactly three short POSTs (one
        # OpenAI, then native batch and native per-text) after /v1/models.
        try:
            vectors = self._vectors_from_payload(
                self._post(
                    "/v1/embeddings",
                    {"input": ["hindsight embedding probe"]},
                    self.probe_timeout,
                ),
                expected_count=1,
            )
        except (OSError, ValueError, URLError):
            vectors = []
        if len(vectors) == 1 and vectors[0].size:
            self.endpoint = "/v1/embeddings"
            self.available = True
            return
        for endpoint in ("/embedding",):
            try:
                vectors = self._request(endpoint, ["hindsight embedding probe"], timeout=self.probe_timeout)
            except (OSError, ValueError, URLError):
                continue
            if len(vectors) == 1 and vectors[0].size:
                self.endpoint = endpoint
                self.available = True
                return

    def _models_available(self) -> bool:
        """Check the OpenAI-compatible liveness endpoint without embedding work."""
        request = Request(f"{self.base_url}/v1/models", method="GET")
        try:
            with urlopen(request, timeout=self.probe_timeout) as response:
                response.read()
        except (OSError, ValueError, URLError):
            return False
        return True

    def _request(self, endpoint: str, texts: Sequence[str], timeout: float | None = None) -> list[np.ndarray]:
        try:
            return self._vectors_from_payload(
                self._post(endpoint, {"input": list(texts)}, timeout), expected_count=len(texts)
            )
        except (OSError, ValueError, URLError):
            if endpoint != "/embedding":
                raise
        # llama.cpp's native endpoint commonly accepts one `content` string at a
        # time rather than the OpenAI batch shape.  Retain batching for OpenAI,
        # but fall back to this documented native protocol when needed.
        return [
            self._vectors_from_payload(self._post(endpoint, {"content": text}, timeout), expected_count=1)[0]
            for text in texts
        ]

    def _post(self, endpoint: str, payload: dict[str, object], timeout: float | None = None) -> object:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout or self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _vectors_from_payload(payload: object, expected_count: int) -> list[np.ndarray]:
        if not isinstance(payload, dict):
            raise EmbeddingProtocolError("embedding response must be an object")
        raw_vectors: object
        if isinstance(payload.get("data"), list):
            raw_vectors = [item.get("embedding") for item in payload["data"] if isinstance(item, dict)]
        elif isinstance(payload.get("embedding"), list):
            raw_vectors = payload["embedding"]
            if raw_vectors and isinstance(raw_vectors[0], (int, float)):
                raw_vectors = [raw_vectors]
        else:
            raise EmbeddingProtocolError("embedding response has no vectors")
        if not isinstance(raw_vectors, list) or len(raw_vectors) != expected_count:
            raise ValueError("embedding response count does not match request")
        vectors: list[np.ndarray] = []
        for vector in raw_vectors:
            if not isinstance(vector, list) or not vector:
                raise ValueError("embedding vector must be a non-empty list")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
                raise ValueError("embedding vector must contain only numeric values")
            array = np.asarray(vector, dtype=np.float32)
            if array.ndim != 1 or not np.isfinite(array).all():
                raise ValueError("embedding vector must be finite and one-dimensional")
            vectors.append(array)
        if len({vector.shape for vector in vectors}) != 1:
            raise ValueError("embedding dimensions differ")
        return vectors

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not self.available or self.endpoint is None:
            raise RuntimeError("HTTP embedding backend is unavailable")
        vectors = self._request(self.endpoint, texts)
        matrix = np.vstack(vectors).astype(np.float32, copy=False)
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0):
            raise RuntimeError("HTTP embedding backend returned a zero vector")
        return matrix / norms[:, None]


class EmbeddingBackendUnavailableError(RuntimeError):
    """The declared HTTP embedding backend could not be reached.

    A distinct type so callers can tell "the declared backend is down" apart
    from every other RuntimeError, and so no code path can quietly convert it
    into a TF-IDF run.
    """


def select_backend(requested: str = "auto") -> EmbeddingBackend:
    """Return the DECLARED backend, or fail loudly -- never a silent substitute.

    TF-IDF is returned only when the caller declared ``tfidf``.  When the
    declared backend is HTTP (``http``, or ``auto`` which prefers it) and the
    service does not answer, this raises instead of substituting TF-IDF:
    TF-IDF embeddings diverge from the committed HTTP-fitted snapshot, so a
    silent substitution produced digest mismatches and recall shortfalls that
    read as content defects rather than as an unreachable service
    (hindsight#120).
    """
    if requested not in {"auto", "http", "tfidf"}:
        raise ValueError(f"unknown backend {requested!r}")
    if requested == "tfidf":
        print("cluster backend selected: tfidf (forced)", file=sys.stderr)
        return TfidfEmbeddingBackend()
    http = HttpEmbeddingBackend()
    if http.available:
        print("cluster backend selected: http", file=sys.stderr)
        return http
    raise EmbeddingBackendUnavailableError(
        f"declared embedding backend 'http' is unreachable at {http.base_url} "
        f"(requested={requested!r}); refusing to substitute the tfidf backend, whose "
        "embeddings diverge from the committed http-fitted snapshot. Declare "
        "--backend tfidf explicitly if a tfidf run is what you want."
    )


def _validate_backend_identity(identity: object, *, source: str) -> dict[str, object]:
    """Validate the backend/model identity used to authorize snapshot replay."""
    if not isinstance(identity, dict):
        raise TypeError(f"{source} backend identity must be an object")
    if set(identity) != SNAPSHOT_BACKEND_FIELDS:
        missing = sorted(SNAPSHOT_BACKEND_FIELDS.difference(identity))
        unexpected = sorted(set(identity).difference(SNAPSHOT_BACKEND_FIELDS))
        raise ValueError(
            f"{source} backend identity fields do not match schema: "
            f"missing={missing}, unexpected={unexpected}"
        )
    for field in ("name", "model", "revision"):
        if not isinstance(identity[field], str) or not identity[field]:
            raise ValueError(f"{source} backend identity {field} must be a non-empty string")
    dimensions = identity["dimensions"]
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
        raise ValueError(f"{source} backend identity dimensions must be a positive integer")
    return identity


def load_embedding_snapshot(
    path: Path,
    entries: Sequence[Entry],
    expected_backend: dict[str, object],
    *,
    expected_l1_digest: str,
    expected_cluster_digest: str,
) -> np.ndarray:
    """Load an ID-keyed snapshot only when provenance and corpus IDs match exactly."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{path}: snapshot must be an object")
    if payload.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"{path}: unsupported snapshot schema {payload.get('schema')!r}")
    expected_fields = {
        "schema", "provenance", "backend", "embeddings", "similarity_text_sha256",
    }
    if set(payload) != expected_fields:
        raise ValueError(
            f"{path}: snapshot fields do not match schema: "
            f"missing={sorted(expected_fields.difference(payload))}, "
            f"unexpected={sorted(set(payload).difference(expected_fields))}"
        )

    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != SNAPSHOT_PROVENANCE_FIELDS:
        raise ValueError(f"{path}: provenance must contain exactly {sorted(SNAPSHOT_PROVENANCE_FIELDS)}")
    for field in SNAPSHOT_PROVENANCE_FIELDS:
        value = provenance[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"{path}: provenance {field} must be a lowercase SHA-256 digest")
    if provenance["l1_sha256"] != expected_l1_digest:
        raise ValueError(
            f"L1 digest mismatch: snapshot={provenance['l1_sha256']}, declared={expected_l1_digest}"
        )
    if provenance["cluster_sha256"] != expected_cluster_digest:
        raise ValueError(
            "cluster code/config digest mismatch: "
            f"snapshot={provenance['cluster_sha256']}, declared={expected_cluster_digest}"
        )

    actual_backend = _validate_backend_identity(payload.get("backend"), source="snapshot")
    declared_backend = _validate_backend_identity(expected_backend, source="declared")
    if actual_backend != declared_backend:
        differences = ", ".join(
            f"{field}: snapshot={actual_backend[field]!r}, declared={declared_backend[field]!r}"
            for field in sorted(SNAPSHOT_BACKEND_FIELDS)
            if actual_backend[field] != declared_backend[field]
        )
        raise ValueError(f"snapshot backend identity mismatch: {differences}")

    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, dict) or not all(isinstance(key, str) for key in embeddings):
        raise ValueError(f"{path}: embeddings must be an object keyed by L1 id")
    corpus_ids = {entry.id for entry in entries}
    snapshot_ids = set(embeddings)
    if not corpus_ids.intersection(snapshot_ids):
        raise ValueError(
            "ALARM: zero ID overlap between corpus and embedding snapshot: "
            f"corpus_ids={sorted(corpus_ids)}, snapshot_ids={sorted(snapshot_ids)}"
        )
    missing = sorted(corpus_ids.difference(snapshot_ids))
    unexpected = sorted(snapshot_ids.difference(corpus_ids))
    if missing or unexpected:
        raise ValueError(f"embedding snapshot ID mismatch: missing={missing}, unexpected={unexpected}")

    text_digests = payload.get("similarity_text_sha256")
    if not isinstance(text_digests, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in text_digests.items()
    ):
        raise ValueError(f"{path}: similarity_text_sha256 must be an object keyed by L1 id")
    digest_ids = set(text_digests)
    missing_digests = sorted(corpus_ids.difference(digest_ids))
    unexpected_digests = sorted(digest_ids.difference(corpus_ids))
    if missing_digests or unexpected_digests:
        raise ValueError(
            "similarity-text digest ID mismatch: "
            f"missing={missing_digests}, unexpected={unexpected_digests}"
        )
    for entry in entries:
        recorded_digest = text_digests[entry.id]
        if re.fullmatch(r"[0-9a-f]{64}", recorded_digest) is None:
            raise ValueError(
                f"embedding snapshot id {entry.id!r} similarity-text digest "
                "must be a lowercase SHA-256 digest"
            )
        expected_digest = similarity_text_digest(entry)
        if recorded_digest != expected_digest:
            raise ValueError(
                f"embedding snapshot id {entry.id!r} similarity-text digest mismatch: "
                f"snapshot={recorded_digest}, declared={expected_digest}"
            )

    dimensions = int(actual_backend["dimensions"])
    ordered_ids = [entry.id for entry in sorted(entries, key=lambda entry: entry.id)]
    vectors: list[np.ndarray] = []
    for entry_id in ordered_ids:
        vector = embeddings[entry_id]
        if not isinstance(vector, list):
            raise TypeError(f"embedding snapshot id {entry_id!r} vector must be a list")
        if not vector or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
            raise ValueError(f"embedding snapshot id {entry_id!r} vector must contain only numbers")
        try:
            array = np.asarray(vector, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"embedding snapshot id {entry_id!r} vector must be numeric") from exc
        if array.shape != (dimensions,):
            raise ValueError(
                f"embedding snapshot id {entry_id!r} has dimensions {array.size}, expected {dimensions}"
            )
        if not np.isfinite(array).all():
            raise ValueError(f"embedding snapshot id {entry_id!r} vector must be finite")
        vectors.append(array)
    return np.vstack(vectors)


def _source_repo(source_path: str) -> str:
    parts = Path(source_path).parts
    return parts[0] if parts else source_path


def _label(entry: Entry) -> str:
    sentence = re.split(r"[.!?]", entry.instance.strip(), maxsplit=1)[0]
    return SPACE_RE.sub(" ", sentence).strip()[:120] or "unlabelled root cause"


def _cluster_indices(
    similarity: np.ndarray, threshold: float, max_members: int | None = MAX_CLUSTER_MEMBERS
) -> list[list[int]]:
    """Perform deterministic average-link agglomeration from a cosine matrix.

    A merge that would exceed ``max_members`` is permanently refused while the
    remaining candidate pairs continue to be considered.  Refusal is safe to
    retain because cluster sizes only grow.
    """
    count = similarity.shape[0]
    if count == 0:
        return []
    sums = similarity.astype(np.float64, copy=True)
    np.fill_diagonal(sums, 0.0)
    active = np.ones(count, dtype=bool)
    sizes = np.ones(count, dtype=np.int32)
    blocked = np.zeros((count, count), dtype=bool)
    members = [[index] for index in range(count)]

    while True:
        denominator = sizes[:, None] * sizes[None, :]
        averages = sums / denominator
        inactive = ~active
        averages[inactive, :] = -np.inf
        averages[:, inactive] = -np.inf
        np.fill_diagonal(averages, -np.inf)
        averages[blocked] = -np.inf
        flattened = int(np.argmax(averages))
        left, right = divmod(flattened, count)
        best = averages[left, right]
        if not np.isfinite(best) or best < threshold:
            break
        if left > right:
            left, right = right, left
        if max_members is not None and sizes[left] + sizes[right] > max_members:
            blocked[left, right] = True
            blocked[right, left] = True
            continue
        members[left].extend(members[right])
        members[left].sort()
        sizes[left] += sizes[right]
        sums[left, :] += sums[right, :]
        sums[:, left] = sums[left, :]
        active[right] = False

    return [members[index] for index in range(count) if active[index]]


def _assert_non_degenerate(
    assignments: Sequence[Sequence[int]],
    backend_name: str,
    threshold: float,
    entry_count: int,
    max_members: int | None = MAX_CLUSTER_MEMBERS,
) -> None:
    """Reject collapse patterns that turn recurrence output into empty signal.

    This is a real, unconditional bound: the single largest cluster may not
    exceed MAX_CLUSTER_FRACTION of the corpus, full stop.  An earlier version
    of this guard only fired when the *entire* corpus collapsed into exactly
    one cluster (or exactly one cluster had more than one member), which let
    a plausible-looking low threshold (e.g. 0.05) write a 440+/458 mega
    cluster alongside a handful of untouched singletons -- exit 0, corrupt
    L2 output. A degeneracy guard that only catches absurd inputs (threshold
    0, -0.1, 1.5) is decorative; this must catch plausible ones too.
    """
    # A cap can mask a bad threshold by dividing a swallowed corpus into many
    # clusters pinned at the ceiling.  Measure that saturation in aggregate,
    # so the cap remains a brake rather than an escape hatch for degeneracy.
    if max_members is not None:
        pinned_clusters = sum(1 for group in assignments if len(group) >= max_members)
        saturated = sum(len(group) for group in assignments if len(group) >= max_members)
        saturated_fraction = saturated / entry_count
        if saturated_fraction > MAX_CLUSTER_FRACTION:
            raise RuntimeError(
                "degenerate clustering for backend "
                f"{backend_name!r} at threshold {threshold:.2f}: "
                f"{saturated}/{entry_count} ({saturated_fraction:.1%}) of the corpus sits in "
                f"clusters pinned at the {max_members}-member cap, exceeding the "
                f"{MAX_CLUSTER_FRACTION:.0%} bound"
            )
        if pinned_clusters > MAX_PINNED_CLUSTERS:
            raise RuntimeError(
                "degenerate clustering for backend "
                f"{backend_name!r} at threshold {threshold:.2f}: "
                f"{pinned_clusters} clusters are pinned at the {max_members}-member cap, "
                f"exceeding the {MAX_PINNED_CLUSTERS}-cluster bound"
            )

    largest_cluster = max(len(group) for group in assignments)
    largest_fraction = largest_cluster / entry_count
    # A singleton can never be "degenerate" regardless of what fraction of a
    # tiny corpus it represents (two records, correctly left unmerged, are
    # 50% of the corpus each) -- only an actual multi-member mega-cluster
    # counts.
    if largest_cluster > 1 and largest_fraction > MAX_CLUSTER_FRACTION:
        raise RuntimeError(
            "degenerate clustering for backend "
            f"{backend_name!r} at threshold {threshold:.2f}: "
            f"largest cluster is {largest_cluster}/{entry_count} ({largest_fraction:.1%}), "
            f"exceeding the {MAX_CLUSTER_FRACTION:.0%} cap"
        )


def _similarity_matrix(texts: Sequence[str], embeddings: np.ndarray, backend_name: str) -> np.ndarray:
    """Blend the calibrated HTTP metric with lexical evidence when selected."""
    dense_similarity = embeddings @ embeddings.T
    if backend_name != "http":
        return dense_similarity
    lexical_embeddings = TfidfEmbeddingBackend().embed(texts)
    lexical_similarity = lexical_embeddings @ lexical_embeddings.T
    return HTTP_DENSE_WEIGHT * dense_similarity + (1.0 - HTTP_DENSE_WEIGHT) * lexical_similarity


def cluster_entries(
    entries: Sequence[Entry], embeddings: np.ndarray, backend_name: str, threshold: float | None = None
) -> list[Cluster]:
    """Cluster ID-sorted entries from a same-order matrix without contacting a backend."""
    threshold = default_threshold(backend_name) if threshold is None else threshold
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    ordered = sorted(entries, key=lambda entry: entry.id)
    if not ordered:
        raise ValueError("cannot cluster an empty entry set")
    if [entry.id for entry in entries] != [entry.id for entry in ordered]:
        raise ValueError(
            "entries must be sorted by L1 id so pre-computed matrix row order is unambiguous"
        )
    texts = [similarity_text(entry) for entry in ordered]
    if embeddings.shape[0] != len(ordered) or embeddings.ndim != 2:
        raise ValueError("pre-computed embedding matrix has the wrong shape")
    if not np.isfinite(embeddings).all():
        raise ValueError("pre-computed embedding matrix contains non-finite values")
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms == 0):
        raise ValueError("pre-computed embedding matrix contains a zero embedding")
    embeddings = embeddings / norms[:, None]
    if len(ordered) > 1 and np.allclose(embeddings, embeddings[0], atol=1e-9):
        # A broken backend that returns the same vector for every text is
        # invisible to the cluster-size invariant below when it is the HTTP
        # backend: the calibrated similarity blend gives constant dense
        # vectors only 10% weight, so genuinely varied lexical similarity
        # masks the failure and produces plausible-looking (but HTTP-blind)
        # output at exit 0.  Catch the degenerate input directly, before any
        # blending, regardless of which backend produced it.
        raise RuntimeError(
            f"degenerate clustering for backend {backend_name!r} at threshold {threshold:.2f}: "
            "backend returned identical embeddings for every text"
        )
    assignments = _cluster_indices(_similarity_matrix(texts, embeddings, backend_name), threshold)
    _assert_non_degenerate(assignments, backend_name, threshold, len(ordered))

    groups = [[ordered[index] for index in group] for group in assignments]
    groups.sort(key=lambda group: group[0].id)
    clusters: list[Cluster] = []
    for number, group in enumerate(groups, start=1):
        dates = sorted(entry.first_seen for entry in group if entry.first_seen)
        representative = min(group, key=lambda entry: (-len(entry.instance), entry.id))
        clusters.append(
            Cluster(
                cluster_id=f"c-{number:03d}",
                members=tuple(entry.id for entry in group),
                source_repos=tuple(sorted({_source_repo(entry.source_path) for entry in group})),
                first_seen=dates[0] if dates else None,
                last_seen=dates[-1] if dates else None,
                representative=representative.id,
                label=_label(representative),
            )
        )
    return clusters


def cluster_entries_from_backend(
    entries: Sequence[Entry], backend: EmbeddingBackend, threshold: float | None = None
) -> list[Cluster]:
    """Keep the live path intact while the clustering core remains backend-free."""
    ordered = sorted(entries, key=lambda entry: entry.id)
    texts = [similarity_text(entry) for entry in ordered]
    embeddings = backend.embed(texts)
    return cluster_entries(ordered, embeddings, backend.name, threshold)


def write_clusters(
    output: Path, clusters: Sequence[Cluster], backend: EmbeddingBackend, threshold: float, entry_count: int
) -> None:
    """Write a complete JSONL report with machine-readable selection metadata."""
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "_meta": {
            "backend": backend.name,
            "threshold": threshold,
            "entry_count": entry_count,
            "linkage": LINKAGE,
        }
    }
    lines = [json.dumps(metadata, sort_keys=True)]
    lines.extend(json.dumps(cluster.as_json(), sort_keys=True) for cluster in clusters)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    parser.add_argument("--input-dir", type=Path, default=root / "L1")
    parser.add_argument("--output", type=Path, default=root / "L2" / "clusters.jsonl")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--backend", choices=("auto", "http", "tfidf"), default="auto")
    args = parser.parse_args(argv)
    try:
        entries = load_entries(args.input_dir)
        backend = select_backend(args.backend)
        threshold = args.threshold if args.threshold is not None else default_threshold(backend.name)
        clusters = cluster_entries_from_backend(entries, backend, threshold)
        write_clusters(args.output, clusters, backend, threshold, len(entries))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"cluster: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
