#!/usr/bin/env python3
"""Capture an HTTP embedding snapshot with verified provenance and atomic replacement."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import numpy as np

MODULE_PATH = Path(__file__).with_name("cluster.py")
SPEC = importlib.util.spec_from_file_location("hindsight_capture_cluster", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery failure
    raise RuntimeError(f"cannot load clustering module from {MODULE_PATH}")
cluster = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cluster
SPEC.loader.exec_module(cluster)

AUTHORIZED_HTTP_HOSTS = frozenset({"192.168.0.98"})


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


def _request_vectors(base_url: str, texts: Sequence[str], timeout: float) -> np.ndarray:
    request = Request(
        f"{base_url}/v1/embeddings",
        data=json.dumps({"input": list(texts)}, allow_nan=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    vectors = cluster.HttpEmbeddingBackend._vectors_from_payload(payload, expected_count=len(texts))
    return np.vstack(vectors).astype(np.float32, copy=False)


def _atomic_write_json(output: Path, payload: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
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
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    entries = cluster.load_entries(args.input_dir)
    texts = [cluster.similarity_text(entry) for entry in entries]
    matrix = _request_vectors(base_url, texts, args.timeout)
    if matrix.shape != (len(entries), args.dimensions):
        raise ValueError(
            f"embedding dimensions mismatch: received shape {matrix.shape}, expected {(len(entries), args.dimensions)}"
        )
    if not np.isfinite(matrix).all():
        raise ValueError("embedding vectors must be finite")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms == 0):
        raise ValueError("embedding vectors must not be zero")
    matrix = matrix / norms[:, None]
    payload: dict[str, object] = {
        "schema": cluster.SNAPSHOT_SCHEMA,
        "provenance": {
            "l1_sha256": cluster.l1_corpus_digest(args.input_dir),
            "cluster_sha256": cluster.cluster_code_config_digest(args.cluster_code),
        },
        "backend": backend,
        "embeddings": {
            entry.id: matrix[index].tolist() for index, entry in enumerate(entries)
        },
    }
    _atomic_write_json(args.output, payload)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        capture(_parser().parse_args(argv))
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"capture_embedding_snapshot: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
