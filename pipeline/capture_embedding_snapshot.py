#!/usr/bin/env python3
"""Capture an HTTP embedding snapshot with verified provenance and atomic replacement."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import numpy as np

MODULE_PATH = Path(__file__).with_name("cluster.py")
SPEC = importlib.util.spec_from_file_location("hindsight_capture_cluster", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery failure
    raise RuntimeError(f"cannot load clustering module from {MODULE_PATH}")
cluster = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cluster
SPEC.loader.exec_module(cluster)

AUTHORIZED_HTTP_HOSTS = frozenset({"leviathan.petersimmons.com"})


class _RejectRedirects(HTTPRedirectHandler):
    """Keep an authorized origin from forwarding corpus text elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _authorized_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in AUTHORIZED_HTTP_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("backend URL must be an authorized plain-HTTP origin")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("backend URL has an invalid port") from exc
    return value.rstrip("/")


def _post_json(base_url: str, endpoint: str, payload: dict[str, object], timeout: float) -> object:
    request = Request(
        f"{base_url}{endpoint}",
        data=json.dumps(payload, allow_nan=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with build_opener(_RejectRedirects).open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _indexed_openai_vectors(payload: object, expected_count: int) -> list[np.ndarray]:
    """Bind standard OpenAI response rows by explicit index, never array position."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("OpenAI embedding response has no vectors data array")
    indexed: dict[int, object] = {}
    for item in payload["data"]:
        if not isinstance(item, dict):
            raise ValueError("OpenAI embedding data entries must be objects")
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("OpenAI embedding data entry has missing or invalid index")
        if index in indexed:
            raise ValueError(f"OpenAI embedding response has duplicate index {index}")
        indexed[index] = item
    expected = set(range(expected_count))
    if set(indexed) != expected:
        raise ValueError(
            "OpenAI embedding response count/index coverage mismatch: "
            f"missing={sorted(expected.difference(indexed))}, "
            f"unexpected={sorted(set(indexed).difference(expected))}"
        )
    ordered_payload = {"data": [indexed[index] for index in range(expected_count)]}
    return cluster.HttpEmbeddingBackend._vectors_from_payload(
        ordered_payload, expected_count=expected_count
    )


def _request_vectors(base_url: str, texts: Sequence[str], timeout: float) -> np.ndarray:
    try:
        payload = _post_json(base_url, "/v1/embeddings", {"input": list(texts)}, timeout)
        vectors = _indexed_openai_vectors(payload, len(texts))
    except HTTPError as exc:
        if exc.code not in {404, 405}:
            raise
        vectors = [
            cluster.HttpEmbeddingBackend._vectors_from_payload(
                _post_json(base_url, "/embedding", {"content": text}, timeout),
                expected_count=1,
            )[0]
            for text in texts
        ]
    return np.vstack(vectors).astype(np.float32, copy=False)


def _fsync_directory(directory: Path) -> None:
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_json(
    output: Path,
    payload: dict[str, object],
    *,
    before_replace: Callable[[], None] | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    prior_bytes = output.read_bytes() if output.is_file() else None
    temporary: Path | None = None
    rollback: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if prior_bytes is not None:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=output.parent,
                prefix=f".{output.name}.", suffix=".recovery", delete=False,
            ) as rollback_handle:
                rollback = Path(rollback_handle.name)
                rollback_handle.write(prior_bytes)
                rollback_handle.flush()
                os.fsync(rollback_handle.fileno())
            _fsync_directory(output.parent)
        if before_replace is not None:
            before_replace()
        os.replace(temporary, output)
        temporary = None
        try:
            if before_replace is not None:
                before_replace()
        except Exception:
            if prior_bytes is None:
                output.unlink(missing_ok=True)
            else:
                assert rollback is not None
                restored = False
                try:
                    os.replace(rollback, output)
                    restored = True
                except OSError:
                    try:
                        os.rename(rollback, output)
                        restored = True
                    except OSError as rollback_exc:
                        output.unlink(missing_ok=True)
                        _fsync_directory(output.parent)
                        raise RuntimeError(
                            f"snapshot rollback failed; prior snapshot preserved at {rollback}"
                        ) from rollback_exc
                finally:
                    if restored:
                        rollback.unlink(missing_ok=True)
                        rollback = None
            _fsync_directory(output.parent)
            raise
        _fsync_directory(output.parent)
        if rollback is not None:
            rollback.unlink(missing_ok=True)
            rollback = None
            _fsync_directory(output.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if rollback is not None and output.is_file() and output.read_bytes() == prior_bytes:
            rollback.unlink(missing_ok=True)


def _reusable_embeddings(
    output: Path,
    backend: dict[str, object],
    similarity_text_sha256: dict[str, str],
) -> dict[str, list[object]]:
    """Return vectors whose format, backend, ID, and embedding text still match.

    A canonical add changes the whole-corpus L1 digest, so reuse is authorized
    per entry instead. Any malformed or differently-versioned prior snapshot
    falls back to a complete recapture rather than being partially trusted.
    """
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != cluster.SNAPSHOT_SCHEMA:
            return {}
        if cluster._validate_backend_identity(payload.get("backend"), source="snapshot") != backend:
            return {}
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, dict) or not all(isinstance(key, str) for key in embeddings):
            return {}
        recorded_text_digests = payload.get("similarity_text_sha256")
        if not isinstance(recorded_text_digests, dict) or set(recorded_text_digests) != set(embeddings):
            return {}
        if any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in recorded_text_digests.values()
        ):
            return {}
        dimensions = int(backend["dimensions"])
        reusable: dict[str, list[object]] = {}
        for entry_id, vector in embeddings.items():
            if not isinstance(vector, list) or len(vector) != dimensions:
                return {}
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
                return {}
            if not np.isfinite(np.asarray(vector, dtype=np.float32)).all():
                return {}
            if recorded_text_digests[entry_id] == similarity_text_sha256.get(entry_id):
                reusable[entry_id] = vector
        return reusable
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).with_name("L1"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("L2") / "embedding-snapshot.json")
    parser.add_argument("--cluster-code", type=Path, default=MODULE_PATH)
    parser.add_argument("--backend-url", default=cluster.DEFAULT_EMBEDDING_URL)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--dimensions", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--refresh-embeddings",
        action="store_true",
        help="ignore reusable vectors and request fresh embeddings for every L1 entry",
    )
    return parser


def capture(args: argparse.Namespace) -> None:
    base_url = _authorized_base_url(args.backend_url)
    if args.dimensions <= 0 or args.timeout <= 0:
        raise ValueError("dimensions and timeout must be positive")
    backend = {
        "name": "http", "model": args.model, "revision": args.revision,
        "dimensions": args.dimensions,
    }
    cluster._validate_backend_identity(backend, source="declared")
    l1_digest = cluster.l1_corpus_digest(args.input_dir)
    cluster_digest = cluster.cluster_code_config_digest(args.cluster_code)
    entries = cluster.load_entries(args.input_dir)
    if (
        cluster.l1_corpus_digest(args.input_dir) != l1_digest
        or cluster.cluster_code_config_digest(args.cluster_code) != cluster_digest
    ):
        raise ValueError("provenance changed while capture inputs were being read")
    text_digests = {entry.id: cluster.similarity_text_digest(entry) for entry in entries}
    reusable = (
        {}
        if args.refresh_embeddings
        else _reusable_embeddings(args.output, backend, text_digests)
    )
    missing_entries = [entry for entry in entries if entry.id not in reusable]
    if missing_entries:
        texts = [cluster.similarity_text(entry) for entry in missing_entries]
        matrix = _request_vectors(base_url, texts, args.timeout)
        if matrix.shape != (len(missing_entries), args.dimensions):
            raise ValueError(
                "embedding dimensions mismatch: "
                f"received shape {matrix.shape}, expected {(len(missing_entries), args.dimensions)}"
            )
        if not np.isfinite(matrix).all():
            raise ValueError("embedding vectors must be finite")
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0):
            raise ValueError("embedding vectors must not be zero")
        matrix = matrix / norms[:, None]
        reusable.update(
            {entry.id: matrix[index].tolist() for index, entry in enumerate(missing_entries)}
        )
    payload: dict[str, object] = {
        "schema": cluster.SNAPSHOT_SCHEMA,
        "provenance": {
            "l1_sha256": l1_digest,
            "cluster_sha256": cluster_digest,
        },
        "backend": backend,
        "embeddings": {entry.id: reusable[entry.id] for entry in entries},
        "similarity_text_sha256": text_digests,
    }

    def verify_provenance_unchanged() -> None:
        if (
            cluster.l1_corpus_digest(args.input_dir) != l1_digest
            or cluster.cluster_code_config_digest(args.cluster_code) != cluster_digest
        ):
            raise ValueError("provenance changed during capture; refusing snapshot replacement")

    _atomic_write_json(args.output, payload, before_replace=verify_provenance_unchanged)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        capture(_parser().parse_args(argv))
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"capture_embedding_snapshot: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
