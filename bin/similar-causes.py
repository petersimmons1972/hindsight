#!/usr/bin/env python3
"""Print safely rendered advisory candidates from L1 failure-mode records.

The command is deliberately a read-only lookup.  Its exit status describes
operational success only; a populated corpus with no overlapping tokens is a
successful lookup with no candidate rows.  Recoverable malformed JSONL lines
are counted on stderr while rendered corpus fields cannot alter output layout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path


HEADER = "Candidates for human review. This tool does not determine duplication."
MAX_CANDIDATES = 10
TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Record:
    """A usable L1 record together with enough provenance for human review."""

    identifier: str
    instance: str
    source: str
    order: int


class CorpusError(Exception):
    """An operational problem loading the requested corpus."""


def tokens(text: str) -> set[str]:
    """Return normalized word tokens using only the standard library."""

    return set(TOKEN_RE.findall(text.casefold()))


def readable(path: Path) -> bool:
    """Check permission bits as well as access, including when tests run as root."""

    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return bool(mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)) and os.access(path, os.R_OK)


def load_records(corpus: Path) -> tuple[list[Record], int]:
    """Load usable ``instance`` strings from immediate ``*.jsonl`` files."""

    if not corpus.exists():
        raise CorpusError(f"Corpus path does not exist: {corpus}")
    if not corpus.is_dir():
        raise CorpusError(f"Corpus path is not a directory: {corpus}")
    if not readable(corpus):
        raise CorpusError(f"Corpus directory is unreadable: {corpus}")

    try:
        files = sorted(path for path in corpus.iterdir() if path.is_file() and path.suffix == ".jsonl")
    except OSError as exc:
        raise CorpusError(f"Cannot read corpus directory {corpus}: {exc}") from exc
    if not files:
        raise CorpusError(f"Corpus is empty: no JSONL files in {corpus}")

    records: list[Record] = []
    skipped = 0
    for file_path in files:
        if not readable(file_path):
            raise CorpusError(f"Corpus file is unreadable: {file_path}")
        try:
            with file_path.open(encoding="utf-8-sig") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        # A valid neighboring record still makes this a useful lookup.
                        skipped += 1
                        continue
                    if not isinstance(value, dict) or not isinstance(value.get("instance"), str):
                        continue
                    instance = value["instance"].strip()
                    if not instance:
                        continue
                    identifier = value.get("id")
                    source = value.get("source_path")
                    records.append(
                        Record(
                            identifier=identifier if isinstance(identifier, str) and identifier else f"{file_path.name}:{line_number}",
                            instance=instance,
                            source=source if isinstance(source, str) and source else file_path.name,
                            order=len(records),
                        )
                    )
        except (OSError, UnicodeError) as exc:
            raise CorpusError(f"Cannot read corpus file {file_path}: {exc}") from exc

    if not records:
        raise CorpusError(f"Corpus has no usable entries: {corpus}")
    return records, skipped


def display_text(value: str) -> str:
    """Escape corpus text that could alter terminal layout or output structure."""

    escaped: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if category.startswith("C") or category in {"Zl", "Zp"}:
            width = 4 if ord(character) <= 0xFFFF else 8
            escaped.append(f"\\u{ord(character):0{width}x}")
        else:
            escaped.append(character)
    return "".join(escaped)


def write_stdout(text: str) -> bool:
    """Write UTF-8 output, returning false when a downstream reader closes."""

    data = text.encode("utf-8", "backslashreplace")
    view = memoryview(data)
    try:
        while view:
            written = os.write(sys.stdout.fileno(), view)
            view = view[written:]
    except BrokenPipeError:
        # Avoid a later interpreter-shutdown flush reporting EPIPE as failure.
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
        return False
    return True


def score(query_tokens: set[str], record: Record) -> float:
    """Score token overlap; positive scores are advisory candidates."""

    candidate_tokens = tokens(record.instance)
    if not candidate_tokens:
        return 0.0
    return len(query_tokens & candidate_tokens) / len(query_tokens | candidate_tokens)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print advisory failure-mode candidates for human review.")
    parser.add_argument("--corpus", type=Path, help="directory containing L1 JSONL records")
    parser.add_argument("query", help="free-text failure-mode description")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        # Do not repeat arbitrary caller-controlled option text.  In particular,
        # a guard-shaped unknown option must not look like a tool verdict.
        parser.error("unknown option")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.query.strip():
        print("Error: query must contain non-whitespace text", file=sys.stderr)
        return 2

    corpus = args.corpus or Path(__file__).resolve().parents[1] / "pipeline" / "L1"
    try:
        records, skipped = load_records(corpus)
    except CorpusError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    query_tokens = tokens(args.query)
    if skipped:
        print(f"Warning: loaded {len(records)} records; skipped {skipped} malformed records.", file=sys.stderr)

    ranked = [(score(query_tokens, record), record) for record in records]
    ranked = [(value, record) for value, record in ranked if value > 0]
    ranked.sort(key=lambda item: (-item[0], item[1].source, item[1].identifier, item[1].order))

    lines = [HEADER]
    for value, record in ranked[:MAX_CANDIDATES]:
        lines.append(
            f"{value:.3f} | {display_text(record.identifier)} | "
            f"source: {display_text(record.source)} | {display_text(record.instance)}"
        )
    if len(ranked) > MAX_CANDIDATES:
        lines.append(f"Showing {MAX_CANDIDATES} of {len(ranked)} candidates.")
    write_stdout("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
