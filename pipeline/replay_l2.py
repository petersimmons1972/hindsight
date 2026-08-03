#!/usr/bin/env python3
"""Replay committed L2 clustering from its embedding snapshot, without HTTP."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

def _load_cluster(path: Path, code_bytes: bytes | None = None) -> ModuleType:
    module = ModuleType("hindsight_replay_cluster")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(path.read_bytes() if code_bytes is None else code_bytes, str(path), "exec"), module.__dict__)
    return module

def _canonical(groups: Sequence[Sequence[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted(tuple(sorted(group)) for group in groups))

def _load_expected(path: Path, *, l1_ids: set[str], backend: str, threshold: float,
                   entry_count: int, linkage: str) -> tuple[tuple[str, ...], ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path}: clusters JSONL is empty")
    rows: list[object] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"{path}:{line_number}: blank JSONL line is not permitted")
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
    wanted = {"backend": backend, "threshold": threshold, "entry_count": entry_count,
              "linkage": linkage}
    if not isinstance(rows[0], dict) or set(rows[0]) != {"_meta"}:
        raise ValueError(f"{path}:1: first row must be exactly one _meta object")
    metadata = rows[0]["_meta"]
    if not isinstance(metadata, dict) or set(metadata) != set(wanted):
        raise ValueError(f"{path}:1: metadata must be exactly an object with fields {sorted(wanted)}")
    validators = {
        "backend": lambda value: isinstance(value, str),
        "threshold": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        "entry_count": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "linkage": lambda value: isinstance(value, str),
    }
    for field, valid in validators.items():
        if not valid(metadata[field]) or metadata[field] != wanted[field]:
            raise ValueError(
                f"{path}:1: metadata mismatch: metadata {field} must exactly match {wanted[field]!r} "
                f"with the required type; actual={metadata[field]!r}"
            )
    groups: list[list[str]] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for line_number, row in enumerate(rows[1:], start=2):
        if not isinstance(row, dict):
            raise TypeError(f"{path}:{line_number}: cluster row must be an object")
        members = row.get("members")
        if (not isinstance(members, list) or not members or
                any(not isinstance(member, str) or not member for member in members)):
            raise ValueError(f"{path}:{line_number}: members must be a nonempty list of nonempty strings")
        for member in members:
            if member in seen:
                duplicates.add(member)
            seen.add(member)
        groups.append(members)
    if duplicates:
        raise ValueError(f"{path}: duplicate member IDs: {sorted(duplicates)}")
    missing, unexpected = sorted(l1_ids - seen), sorted(seen - l1_ids)
    if missing or unexpected:
        raise ValueError(f"{path}: committed L2 member mismatch: missing={missing}, unexpected={unexpected}")
    return _canonical(groups)

def _mapping(partition: Sequence[Sequence[str]], members: set[str]) -> dict[str, tuple[str, ...]]:
    return {member: tuple(group) for group in partition for member in group if member in members}

def replay(input_dir: Path, snapshot: Path, clusters_path: Path, cluster_code: Path) -> tuple[int, int]:
    code_bytes = cluster_code.read_bytes()
    cluster = _load_cluster(cluster_code, code_bytes)
    l1_digest = cluster.l1_corpus_digest(input_dir)
    entries = cluster.load_entries(input_dir)
    if cluster.l1_corpus_digest(input_dir) != l1_digest:
        raise RuntimeError("L1 changed during replay")
    cluster_digest = cluster.cluster_code_config_digest(cluster_code)
    if cluster_code.read_bytes() != code_bytes:
        raise RuntimeError("cluster code/config changed during replay")
    matrix = cluster.load_embedding_snapshot(
        snapshot, entries, cluster.HTTP_BACKEND_IDENTITY,
        expected_l1_digest=l1_digest,
        expected_cluster_digest=cluster_digest,
    )
    threshold = cluster.default_threshold("http")
    expected = _load_expected(clusters_path, l1_ids={entry.id for entry in entries}, backend="http",
                              threshold=threshold, entry_count=len(entries), linkage=cluster.LINKAGE)
    actual_clusters = cluster.cluster_entries(
        entries, matrix, backend_name="http", threshold=threshold
    )
    actual = _canonical([item.members for item in actual_clusters])
    if cluster.l1_corpus_digest(input_dir) != l1_digest:
        raise RuntimeError("L1 changed during replay")
    if (cluster.cluster_code_config_digest(cluster_code) != cluster_digest or
            cluster_code.read_bytes() != code_bytes):
        raise RuntimeError("cluster code/config changed during replay")
    if expected != actual:
        expected_only = tuple(group for group in expected if group not in actual)
        replay_only = tuple(group for group in actual if group not in expected)
        changed = set(member for group in (*expected_only, *replay_only) for member in group)
        raise RuntimeError(
            "partition mismatch: "
            f"expected-only={expected_only!r}, replay-only={replay_only!r}, "
            f"expected-members={_mapping(expected, changed)!r}, replay-members={_mapping(actual, changed)!r}"
        )
    return len(entries), len(actual)

def main(argv: Sequence[str] | None = None) -> int:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=root / "L1")
    parser.add_argument("--snapshot", type=Path, default=root / "L2" / "embedding-snapshot.json")
    parser.add_argument("--clusters", type=Path, default=root / "L2" / "clusters.jsonl")
    parser.add_argument("--cluster-code", type=Path, default=root / "cluster.py")
    args = parser.parse_args(argv)
    try:
        entries, clusters = replay(args.input_dir, args.snapshot, args.clusters, args.cluster_code)
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"replay-l2: error: {exc}", file=sys.stderr)
        return 1
    print(f"replay-l2: PASS: {entries} entries, {clusters} clusters")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
