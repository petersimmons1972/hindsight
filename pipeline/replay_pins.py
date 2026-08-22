#!/usr/bin/env python3
"""Rewrite and directly verify the committed L2 replay pin literals.

This module is intentionally usable with plain ``python3``.  The canonical
write path must not use pytest as the oracle for these literals: pytest's
startup and collection configuration is ambient process state.  Instead, this
module runs the real offline replay, reads the released snapshot, and compares
those artifact-derived values to every literal it knows how to rewrite.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PinSpec:
    """One maintained literal and the artifact-derived value it must equal."""

    name: str
    relative_path: Path
    pattern: re.Pattern[str]
    value_kind: str


# This is the single registry for rewrite *and* verification.  Adding a pin to
# the write transaction means adding it here; ``_expected_values`` refuses any
# unknown value kind, so a fourth rewritten pin cannot be added without a
# verifier derived from a real artifact.
PIN_SPECS = (
    PinSpec(
        "default replay output pin",
        Path("pipeline/tests/test_replay_l2.py"),
        re.compile(
            r'(?P<prefix>assert REPLAY\.main\(\[\]\) == 0 and "PASS: )'
            r'(?P<actual>\d+ entries, \d+ clusters)'
            r'(?P<suffix>" in capsys\.readouterr\(\)\.out)'
        ),
        "replay_output",
    ),
    PinSpec(
        "offline replay stdout pin",
        Path("pipeline/tests/test_replay_l2_mutations.py"),
        re.compile(
            r'(?P<prefix>assert captured\.out == "replay-l2: PASS: )'
            r'(?P<actual>\d+ entries, \d+ clusters)'
            r'(?P<suffix>\\n")'
        ),
        "replay_output",
    ),
    PinSpec(
        "embedding cardinality pin",
        Path("pipeline/tests/test_replay_l2_mutations.py"),
        re.compile(
            r'(?P<prefix>assert len\(payload\["embeddings"\]\) == )'
            r'(?P<actual>\d+)(?P<suffix>)'
        ),
        "embedding_cardinality",
    ),
)


def _load_replay(repo_root: Path):
    path = repo_root / "pipeline" / "replay_l2.py"
    spec = importlib.util.spec_from_file_location("hindsight_replay_pin_oracle", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load replay oracle: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _replay_output(repo_root: Path) -> str:
    replay = _load_replay(repo_root)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        status = replay.main([])
    output = captured.getvalue()
    if status != 0:
        raise RuntimeError(f"offline replay failed with exit {status}")
    match = re.fullmatch(r"replay-l2: PASS: (\d+ entries, \d+ clusters)\n", output)
    if match is None:
        raise RuntimeError(f"offline replay produced an unexpected report: {output!r}")
    return match.group(1)


def _embedding_cardinality(repo_root: Path) -> str:
    snapshot = repo_root / "pipeline" / "L2" / "embedding-snapshot.json"
    try:
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        embeddings = payload["embeddings"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(f"cannot read embedding cardinality from {snapshot}: {exc}") from exc
    if not isinstance(embeddings, dict):
        raise RuntimeError(f"embedding cardinality source is not an object: {snapshot}")
    return str(len(embeddings))


def _expected_values(repo_root: Path) -> dict[str, str]:
    values = {
        "replay_output": _replay_output(repo_root),
        "embedding_cardinality": _embedding_cardinality(repo_root),
    }
    unknown = {spec.value_kind for spec in PIN_SPECS} - values.keys()
    if unknown:
        raise RuntimeError(f"replay pin registry has no verifier for: {sorted(unknown)}")
    return {spec.name: values[spec.value_kind] for spec in PIN_SPECS}


def _match_pin(spec: PinSpec, source: str, path: Path) -> re.Match[str]:
    matches = list(spec.pattern.finditer(source))
    if len(matches) != 1:
        raise RuntimeError(
            f"replay pin {spec.name} is unlocatable or ambiguous in {path}: found {len(matches)} matches"
        )
    return matches[0]


def rewrite(repo_root: Path) -> None:
    """Update every registered literal from the freshly released artifacts."""
    expected = _expected_values(repo_root)
    updates: dict[Path, str] = {}
    for spec in PIN_SPECS:
        path = repo_root / spec.relative_path
        try:
            source = updates.get(path, path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"replay pin {spec.name} is unavailable: {path}: {exc}") from exc
        match = _match_pin(spec, source, path)
        replacement = f"{match.group('prefix')}{expected[spec.name]}{match.group('suffix')}"
        updates[path] = source[:match.start()] + replacement + source[match.end():]
    for path, source in updates.items():
        path.write_text(source, encoding="utf-8")


def verify(repo_root: Path) -> bool:
    """Print all pin comparisons and return whether every literal is correct."""
    expected = _expected_values(repo_root)
    passed = True
    for spec in PIN_SPECS:
        path = repo_root / spec.relative_path
        try:
            actual = _match_pin(spec, path.read_text(encoding="utf-8"), path).group("actual")
        except (OSError, RuntimeError) as exc:
            print(f"replay pin {spec.name}: expected={expected[spec.name]!r} actual=<unreadable: {exc}>")
            passed = False
            continue
        print(f"replay pin {spec.name}: expected={expected[spec.name]!r} actual={actual!r}")
        passed = passed and actual == expected[spec.name]
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("rewrite", "verify"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        if args.command == "rewrite":
            rewrite(repo_root)
            return 0
        return 0 if verify(repo_root) else 1
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
