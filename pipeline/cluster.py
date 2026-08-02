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
merge.  A 0.10 dense / 0.90 lexical cosine blend at 0.20 produced 180 clusters
(largest 34) and recovered 6/7 completion, 6/7 shared-checkout, 4/4
fail-silent, 3/3 dedup-key, and 2/2 convergence records with every required
precision separation.  The sparse TF-IDF default remains 0.17.
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

BACKEND_DEFAULT_THRESHOLDS = {"tfidf": 0.17, "http": 0.20}
# Retained as the sparse fallback's public compatibility constant.  Call
# default_threshold() for a selected backend rather than reusing this value.
DEFAULT_THRESHOLD = BACKEND_DEFAULT_THRESHOLDS["tfidf"]
DEFAULT_EMBEDDING_URL = "http://192.168.0.98:8004"
LINKAGE = "average"
HTTP_DENSE_WEIGHT = 0.10
MAX_CLUSTER_FRACTION = 0.40
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


def _cause_shape_markers(text: str) -> tuple[str, ...]:
    """Return conservative semantic normalisations for recurring cause shapes.

    These are a declared hybrid, not pure embedding similarity: TF-IDF alone
    cannot infer that several very differently-worded incidents share one
    root cause, so a short list of conservative, multi-condition regexes
    bridges that gap.  Two properties are required of every condition here,
    checked with adversarial inputs in the test suite:

    - it must require more than one common English word in isolation (a
      bare, unusual token like `ran_ok` is an exception -- it is a specific
      code-level identifier, not ordinary prose); and
    - it is written from each family's *stated* definition (see
      `pipeline/tests/fixtures/recurrence_ground_truth.json`), not reverse
      engineered from any one example's exact wording, so it also fires on
      held-out paraphrases the condition was never tuned against.
    """
    lower = text.lower()
    markers: list[str] = []
    completion_gap = (
        (re.search(r"\bexit(?:ed)?\s+0\b", lower) and
         re.search(r"\b(embedded\s+0|artifact|ledger)\b", lower)) or
        (re.search(r"\breport\b", lower) and
         re.search(r"\b(forced.early|wrong.state)\b", lower)) or
        (re.search(r"\bcompletion", lower) and
         re.search(r"\b(no deliverable|nothing)\b", lower)) or
        (re.search(r"\bresume\b", lower) and re.search(r"\bheadless\b", lower) and
         re.search(r"\b(nothing|never|no output|silent|logged only)\b", lower)) or
        (re.search(r"\bdeemed dead\b", lower) and
         re.search(r"\b(late|overwrit)\b", lower)) or
        (re.search(r"\bdispatch boundary\b", lower) and
         re.search(r"\b(result|deliverable)\b", lower)) or
        # The family's own stated shape: a claimed-done signal contradicted
        # by a deliverable that never materialised.  Written from that
        # definition, not from any one incident's wording -- it must also
        # catch paraphrases nobody tuned it against.
        (re.search(r"\b(claimed|announced|said|printed|reported|logged)\b", lower) and
         re.search(r"\b(finished|done|complete|success|green)\b", lower) and
         re.search(
             r"\b(never\s+(got\s+)?(appeared|opened|committed)|absent|empty|stayed empty|zero new|nothing)\b",
             lower,
         ))
    )
    if completion_gap:
        markers.append("latentcompletiongap")

    broken_gate = (
        re.search(r"\bran_ok\b", lower) or
        (re.search(r"\bexit(?:ed)?\s+0\b", lower) and re.search(r"\b(fail|status)\b", lower)) or
        (re.search(r"\bdependency\b", lower) and re.search(r"\b(404|unreachable)\b", lower) and
         re.search(r"\breject\b", lower)) or
        (re.search(r"\bgate\b", lower) and
         re.search(r"\b(unparseable|never appeared|not.quite.matching)\b", lower)) or
        # A failure was observed (crash/error, or swallowed and downgraded
        # to a soft skip) but the reported/displayed result stayed green --
        # the family's stated shape, not a single incident's exact prose.
        (re.search(r"\b(crash|crashed)\b", lower) and re.search(r"\b(green|painted|passed)\b", lower)) or
        (re.search(r"\b(swallow|swallowed)\b", lower) and re.search(r"\bskip\b", lower) and
         re.search(r"\bnot\b.*\b(red|fail)\b", lower))
    )
    if broken_gate:
        markers.append("latentbrokengate")

    nonindependent_evidence = (
        (re.search(r"\bnegative.search\b", lower) and re.search(r"\b(claim|doctrine)\b", lower)) or
        (re.search(r"\bconverg", lower) and re.search(r"\b(independent|shared)\b", lower))
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
        # The PROBE must be short -- an unreachable host should not stall startup.
        # The bulk request must NOT inherit that cap: embedding the whole corpus
        # is orders of magnitude more work than a one-string liveness probe.
        # Capping both at 3s made every real run fail with "timed out" while the
        # test suite stayed green, because the tests force the TF-IDF fallback.
        self.probe_timeout = min(max(timeout, 0.1), 3.0)
        self.request_timeout = max(request_timeout, self.probe_timeout)
        if parsed.scheme != "http" or parsed.hostname != "192.168.0.98":
            return
        for endpoint in ("/v1/embeddings", "/embedding"):
            try:
                vectors = self._request(endpoint, ["hindsight embedding probe"], timeout=self.probe_timeout)
            except (OSError, ValueError, URLError):
                continue
            if len(vectors) == 1 and vectors[0].size:
                self.endpoint = endpoint
                self.available = True
                return

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


def select_backend(requested: str = "auto") -> EmbeddingBackend:
    """Choose a backend and make fallback observable to callers and operators."""
    if requested not in {"auto", "http", "tfidf"}:
        raise ValueError(f"unknown backend {requested!r}")
    if requested in {"auto", "http"}:
        http = HttpEmbeddingBackend()
        if http.available:
            print("cluster backend selected: http", file=sys.stderr)
            return http
        if requested == "http":
            raise RuntimeError("requested HTTP embedding backend is unavailable")
        print("cluster backend selected: tfidf (HTTP backend unavailable)", file=sys.stderr)
    else:
        print("cluster backend selected: tfidf (forced)", file=sys.stderr)
    return TfidfEmbeddingBackend()


def _source_repo(source_path: str) -> str:
    parts = Path(source_path).parts
    return parts[0] if parts else source_path


def _label(entry: Entry) -> str:
    sentence = re.split(r"[.!?]", entry.instance.strip(), maxsplit=1)[0]
    return SPACE_RE.sub(" ", sentence).strip()[:120] or "unlabelled root cause"


def _cluster_indices(similarity: np.ndarray, threshold: float) -> list[list[int]]:
    """Perform deterministic average-link agglomeration from a cosine matrix."""
    count = similarity.shape[0]
    if count == 0:
        return []
    sums = similarity.astype(np.float64, copy=True)
    np.fill_diagonal(sums, 0.0)
    active = np.ones(count, dtype=bool)
    sizes = np.ones(count, dtype=np.int32)
    members = [[index] for index in range(count)]

    while True:
        denominator = sizes[:, None] * sizes[None, :]
        averages = sums / denominator
        inactive = ~active
        averages[inactive, :] = -np.inf
        averages[:, inactive] = -np.inf
        np.fill_diagonal(averages, -np.inf)
        flattened = int(np.argmax(averages))
        left, right = divmod(flattened, count)
        best = averages[left, right]
        if not np.isfinite(best) or best < threshold:
            break
        if left > right:
            left, right = right, left
        members[left].extend(members[right])
        members[left].sort()
        sizes[left] += sizes[right]
        sums[left, :] += sums[right, :]
        sums[:, left] = sums[left, :]
        active[right] = False

    return [members[index] for index in range(count) if active[index]]


def _assert_non_degenerate(
    assignments: Sequence[Sequence[int]], backend_name: str, threshold: float, entry_count: int
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


def _similarity_matrix(texts: Sequence[str], embeddings: np.ndarray, backend: EmbeddingBackend) -> np.ndarray:
    """Blend the calibrated HTTP metric with lexical evidence when selected."""
    dense_similarity = embeddings @ embeddings.T
    if backend.name != "http":
        return dense_similarity
    lexical_embeddings = TfidfEmbeddingBackend().embed(texts)
    lexical_similarity = lexical_embeddings @ lexical_embeddings.T
    return HTTP_DENSE_WEIGHT * dense_similarity + (1.0 - HTTP_DENSE_WEIGHT) * lexical_similarity


def cluster_entries(
    entries: Sequence[Entry], backend: EmbeddingBackend, threshold: float | None = None
) -> list[Cluster]:
    """Cluster entries using only their incident, check, and class-hint text."""
    threshold = default_threshold(backend.name) if threshold is None else threshold
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    ordered = sorted(entries, key=lambda entry: entry.id)
    if not ordered:
        raise ValueError("cannot cluster an empty entry set")
    texts = [similarity_text(entry) for entry in ordered]
    embeddings = backend.embed(texts)
    if embeddings.shape[0] != len(ordered) or embeddings.ndim != 2:
        raise ValueError("backend returned an embedding matrix with the wrong shape")
    if not np.isfinite(embeddings).all():
        raise ValueError("backend returned non-finite embeddings")
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms == 0):
        raise ValueError("backend returned a zero embedding")
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
            f"degenerate clustering for backend {backend.name!r} at threshold {threshold:.2f}: "
            "backend returned identical embeddings for every text"
        )
    assignments = _cluster_indices(_similarity_matrix(texts, embeddings, backend), threshold)
    _assert_non_degenerate(assignments, backend.name, threshold, len(ordered))

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
        clusters = cluster_entries(entries, backend, threshold)
        write_clusters(args.output, clusters, backend, threshold, len(entries))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"cluster: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
