#!/usr/bin/env python3
"""Validate catalog invariants and expose unverifiable claimed enforcement.

The catalog is a registry, not a record of aspirations.  L1 entries that name
an enforcement file need a cheap reality check, while entries honestly marked
as unbacked must remain visible without being treated as build failures.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

ROW_RE = re.compile(r"^\| (FM-(\d{2,3})) \|")
# Legacy schemes are only a defect when used as a ROW ID. The same strings
# appear legitimately as provenance annotations inside the bug-class column
# (e.g. "Container Runtime - Design (FM-RC-01)") and must not be flagged.
HISTORICAL_SCHEME_RE = re.compile(r"^\| *FM-(RC|REC)-\d+ *\|")
OPENING_DELIMITERS = {"(": ")", "{": "}", "[": "]"}
CLOSING_DELIMITERS = {closing: opening for opening, closing in OPENING_DELIMITERS.items()}


def _read_regular_utf8(path: Path) -> str | None:
    """Read one regular UTF-8 file, failing closed at the narrow I/O boundary."""
    try:
        with path.open("r", encoding="utf-8") as source_file:
            source = source_file.read()
            if not stat.S_ISREG(os.fstat(source_file.fileno()).st_mode):
                return None
    except (OSError, UnicodeError):
        return None
    return source


def _is_runner_managed_test_source(path: Path) -> bool:
    """Recognize bounded, structurally plausible non-executable runner sources.

    A runner may execute its source input without an execute bit. Accepted
    shapes are Pytest ``.py`` modules, Bats ``.bats`` files, and JavaScript
    ``*.test.js`` files. Each format uses a structural probe, never a suffix
    or substring alone.
    """
    if path.suffix == ".py":
        return _is_pytest_source(path)
    if path.suffix == ".bats":
        return _is_bats_source(path)
    if path.name.endswith(".test.js"):
        return _is_javascript_test_source(path)
    return False


def _is_pytest_source(path: Path) -> bool:
    """Accept Python only when its AST contains an actual Pytest test node."""
    source = _read_regular_utf8(path)
    if source is None:
        return False
    try:
        module = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False

    def is_test_function(node: ast.stmt) -> bool:
        return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")

    return any(
        is_test_function(node)
        or (
            isinstance(node, ast.ClassDef)
            and node.name.startswith("Test")
            and any(is_test_function(child) for child in node.body)
        )
        for node in module.body
    )


def _is_bats_source(path: Path) -> bool:
    """Recognize bounded whole-file Bats structural plausibility.

    This intentionally small lexer skips shell comments and quoted strings so
    decorative ``@test`` text cannot become enforcement evidence. It validates
    exactly nested ``()``, ``{}``, and ``[]`` delimiters through EOF and
    requires at least one complete, non-empty ``@test \"name\" { ... }`` block.
    This is not a complete shell or Bats parser.
    """
    source = _read_regular_utf8(path)
    if source is None:
        return False

    def skip_quoted(index: int) -> int | None:
        quote = source[index]
        index += 1
        while index < len(source):
            if source[index] == "\\":
                index += 2
            elif source[index] == quote:
                return index + 1
            else:
                index += 1
        return None

    delimiters: list[str] = []
    candidate_depth: int | None = None
    candidate_has_command = False
    candidate_found = False
    index = 0
    line_start = True
    while index < len(source):
        char = source[index]
        if char == "#":
            newline = source.find("\n", index + 1)
            if newline == -1:
                index = len(source)
                continue
            index = newline + 1
            line_start = True
            continue
        if char in "'\"":
            end = skip_quoted(index)
            if end is None:
                return False
            line_start = False
            index = end
            continue
        if char == "\\":
            if index + 1 == len(source):
                return False
            if candidate_depth is not None:
                candidate_has_command = True
            line_start = source[index + 1] == "\n"
            index += 2
            continue
        if char == "\n":
            line_start = True
            index += 1
            continue
        if char.isspace():
            index += 1
            continue
        if not (line_start and source.startswith("@test", index)):
            if char in OPENING_DELIMITERS:
                delimiters.append(char)
                if candidate_depth is not None and char != "{":
                    candidate_has_command = True
            elif char in CLOSING_DELIMITERS:
                if not delimiters or delimiters[-1] != CLOSING_DELIMITERS[char]:
                    return False
                closes_candidate = candidate_depth == len(delimiters) and char == "}"
                delimiters.pop()
                if closes_candidate:
                    if not candidate_has_command:
                        return False
                    candidate_found = True
                    candidate_depth = None
                    candidate_has_command = False
            elif candidate_depth is not None and char != ";":
                candidate_has_command = True
            line_start = False
            index += 1
            continue

        after_marker = index + len("@test")
        if after_marker == len(source) or not source[after_marker].isspace():
            line_start = False
            index += 1
            continue
        if candidate_depth is not None:
            return False
        index = after_marker
        while index < len(source) and source[index].isspace():
            index += 1
        if index == len(source) or source[index] not in "'\"":
            return False
        quoted_end = skip_quoted(index)
        if quoted_end is None:
            return False
        index = quoted_end
        while index < len(source) and source[index].isspace():
            index += 1
        if index == len(source) or source[index] != "{":
            return False
        delimiters.append("{")
        candidate_depth = len(delimiters)
        candidate_has_command = False
        line_start = False
        index += 1

    return candidate_found and candidate_depth is None and not delimiters


def _is_javascript_test_source(path: Path) -> bool:
    """Recognize bounded whole-file JavaScript structural plausibility.

    The fleet runner imports ``*.test.js`` files, so they need not be
    executable. This lexer validates exactly nested ``()``, ``{}``, and ``[]``
    delimiters through EOF, skips complete comments and literals, and requires
    at least one ``test(<quoted name>, [async] (...) => {...})`` candidate.
    Every encountered bare ``test(`` must have that bounded form; property
    calls such as a regular expression's ``.test(...)`` are ordinary source.
    This is structural plausibility, not a complete JavaScript parser.
    """
    source = _read_regular_utf8(path)
    if source is None:
        return False

    tokens: list[tuple[str, str]] = []
    delimiter_stack: list[tuple[str, int]] = []
    matching_delimiters: dict[int, int] = {}

    def append_punctuation(char: str) -> bool:
        token_index = len(tokens)
        tokens.append(("punctuation", char))
        if char in OPENING_DELIMITERS:
            delimiter_stack.append((char, token_index))
        elif char in CLOSING_DELIMITERS:
            if not delimiter_stack or delimiter_stack[-1][0] != CLOSING_DELIMITERS[char]:
                return False
            _, opening_index = delimiter_stack.pop()
            matching_delimiters[opening_index] = token_index
            matching_delimiters[token_index] = opening_index
        return True

    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
        elif source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline == -1 else newline + 1
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end == -1:
                return False
            index = end + 2
        elif char in "'\"`":
            quote = char
            index += 1
            while index < len(source) and source[index] != quote:
                if source[index] == "\\":
                    index += 2
                elif quote != "`" and source[index] in "\r\n":
                    return False
                else:
                    index += 1
            if index >= len(source):
                return False
            tokens.append(("string", ""))
            index += 1
        elif char.isidentifier() or char in "$_":
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] in "$_"):
                end += 1
            tokens.append(("identifier", source[index:end]))
            index = end
        else:
            if not append_punctuation(char):
                return False
            index += 1

    if delimiter_stack:
        return False

    candidate_found = False
    for token_index, token in enumerate(tokens[:-1]):
        if token != ("identifier", "test") or tokens[token_index + 1] != ("punctuation", "("):
            continue
        if token_index and tokens[token_index - 1] == ("punctuation", "."):
            continue
        call_open = token_index + 1
        call_close = matching_delimiters[call_open]
        cursor = token_index + 2
        if cursor >= call_close or tokens[cursor][0] != "string":
            return False
        cursor += 1
        if cursor >= call_close or tokens[cursor] != ("punctuation", ","):
            return False
        cursor += 1
        if cursor < call_close and tokens[cursor] == ("identifier", "async"):
            cursor += 1
        if cursor >= call_close or tokens[cursor] != ("punctuation", "("):
            return False
        parameters_close = matching_delimiters[cursor]
        cursor = parameters_close + 1
        if cursor + 2 >= call_close or tokens[cursor : cursor + 2] != [
            ("punctuation", "="),
            ("punctuation", ">"),
        ]:
            return False
        cursor += 2
        if tokens[cursor] != ("punctuation", "{"):
            return False
        body_close = matching_delimiters[cursor]
        if body_close + 1 != call_close:
            return False
        candidate_found = True

    return candidate_found


@dataclass(frozen=True)
class CatalogRow:
    fm_id: str
    number: int
    line: int


@dataclass
class SourceTotals:
    machine: int = 0
    judgment: int = 0
    # Machine rows with enforcement: null remain an honest, separately
    # reported lack of a claimed mechanism; judgment rows are not warnings.
    unbacked: int = 0
    # All rows with a non-null enforcement value, irrespective of auto.
    # This root-independent count backs the corpus-wide debt floor.
    enforcement_bearing: int = 0
    phantoms: int = 0
    unverifiable: int = 0
    # Incremented once per entry that had a non-null enforcement
    # value AND a resolved source root -- i.e. an entry that was actually
    # run through the exists() check, regardless of whether it passed
    # (enforced) or failed (phantom). This is what makes the root floor
    # falsifiable: a root can resolve (its directory exists) while every
    # single entry that could have used it is unbacked, in which case it
    # verified nothing and must not count toward "roots present".
    checked: int = 0


@dataclass(frozen=True)
class PhantomEntry:
    source: str
    entry_id: str
    enforcement_file: str
    location: str  # "<jsonl_path>:<line_number>"

    def key(self) -> tuple[str, str, str]:
        return (self.source, self.entry_id, self.enforcement_file)

    def format(self) -> str:
        return (
            f"phantom: {self.enforcement_file} "
            f"({self.source}:{self.entry_id}, {self.location})"
        )


@dataclass
class EnforcementReport:
    sources: dict[str, SourceTotals]
    phantoms: list[PhantomEntry]
    unverifiable: list[str]
    roots_resolved: dict[str, Path]
    roots_unresolved: dict[str, str]
    mapped_sources: int


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "catalog" / "failure-modes.md"


def default_l1_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "pipeline" / "L1"


def default_projects_dir() -> Path:
    return Path.home() / "projects"


def default_source_roots_path() -> Path:
    return Path(__file__).resolve().parents[1] / "conf" / "source-roots.conf"


def default_known_phantoms_path() -> Path:
    return Path(__file__).resolve().parents[1] / "conf" / "known-phantoms.conf"


def default_enforcement_floor_path() -> Path:
    return Path(__file__).resolve().parents[1] / "conf" / "enforcement-floor.conf"


def load_source_roots(path: Path) -> dict[str, str]:
    """Load the source -> repo-root mapping. Fails loud, never "no map, so all fine".

    An L1 source with no entry here is not an error by itself -- it falls
    into UNVERIFIABLE, exactly like a mapped-but-absent root does. What IS an
    error is the map file itself being missing or empty: that would silently
    make every single source unverifiable, which is indistinguishable from
    "nobody bothered to write the map" and must not pass as if it were a
    deliberate, evidenced decision.
    """
    if not path.is_file():
        raise ValueError(f"source-roots map not found: {path}")
    mapping: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"malformed source-roots line {path}:{line_number}: {raw_line!r}")
        source, _, relpath = line.partition(":")
        source = source.strip()
        relpath = relpath.strip()
        if not source or not relpath:
            raise ValueError(f"malformed source-roots line {path}:{line_number}: {raw_line!r}")
        mapping[source] = relpath
    if not mapping:
        raise ValueError(f"source-roots map is empty: {path}")
    return mapping


def load_known_phantoms(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    """Load the debt ledger of already-documented phantoms.

    A phantom record is proof that someone once claimed an enforcement
    mechanism that does not exist -- the single most valuable artifact this
    project produces. It must never be nulled away in L1 (that destroys the
    evidence); instead it lives here, keyed on (source, id, claimed path),
    with the evidence checked and a disposition recorded.

    Missing file -> ValueError (fail loud), same idiom as load_source_roots:
    a debt ledger that silently vanished must not be read as "0 known
    debts, so nothing to gate on" -- that is indistinguishable from nobody
    ever having looked, and would let new phantoms land unchallenged the
    moment the file goes missing. An EMPTY (but present) file is a valid,
    meaningful state -- "no undocumented debt" -- and is not an error.
    """
    if not path.is_file():
        raise ValueError(f"known-phantoms ledger not found: {path}")
    known: dict[tuple[str, str, str], dict[str, str]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"known-phantoms ledger unreadable: {path}: {exc}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed known-phantoms line {path}:{line_number}: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"known-phantoms line {path}:{line_number} is not an object")
        for field in ("source", "id", "claimed_path", "evidence", "disposition"):
            if not isinstance(record.get(field), str) or not record[field]:
                raise ValueError(
                    f"known-phantoms line {path}:{line_number} missing required field {field!r}"
                )
        key = (record["source"], record["id"], record["claimed_path"])
        known[key] = record
    return known


def load_enforcement_floor(path: Path) -> int:
    """Load the minimum acceptable count of enforcement-bearing entries.

    This is the fleet#152 defense: a debt ledger (known-phantoms.conf) can
    legitimately shrink when a phantom is genuinely fixed, but it can also
    "shrink" because someone deleted the L1 record that was flagged --
    hiding debt instead of paying it. The floor is keyed on the TOTAL count
    of `auto: machine` entries carrying a non-null enforcement value
    (enforced + phantom + unverifiable), computed straight from the L1
    corpus with NO dependency on any root resolving -- so it is a real
    check that runs the same way on every machine, CI included, unlike the
    root-scoped phantom search itself.

    Missing or malformed (non-integer) -> ValueError (fail loud): a floor
    file that silently vanished must not be read as "floor 0, anything
    passes" -- see load_known_phantoms for the identical rationale.
    """
    if not path.is_file():
        raise ValueError(f"enforcement floor file not found: {path}")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(lines) != 1:
        raise ValueError(f"enforcement floor file must contain exactly one value: {path}")
    try:
        return int(lines[0])
    except ValueError as exc:
        raise ValueError(f"enforcement floor value is not an integer: {lines[0]!r}") from exc


def total_enforcement_bearing(report: EnforcementReport) -> int:
    """All entries with a non-null enforcement value, across all sources.

    Deliberately root-independent: an unmapped/absent-root source still
    counts its non-null entries here even though it can't be resolved, so this total is
    computable -- and thus a real, always-on gate -- in ANY environment,
    including a CI runner with none of the source repos checked out.
    """
    return sum(totals.enforcement_bearing for totals in report.sources.values())


def machine_enforcement_bearing(report: EnforcementReport) -> int:
    """Pre-issue-31 machine-only subtotal, retained solely for visible migration output."""
    return sum(totals.machine - totals.unbacked for totals in report.sources.values())


def parse_rows(text: str) -> list[CatalogRow]:
    rows: list[CatalogRow] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = ROW_RE.match(line)
        if not match:
            continue
        rows.append(
            CatalogRow(
                fm_id=match.group(1),
                number=int(match.group(2)),
                line=line_number,
            )
        )
    return rows


# Sentinel meaning "this call is not evaluating the append-only invariant".
# It exists ONLY so unit tests of unrelated rules need not construct a ledger.
# The real entry point in main() always passes a real value (or None when the
# ledger could not be read), so the gate itself is never skipped by default --
# a fail-open default here would defeat the entire invariant.
LEDGER_NOT_REQUESTED = object()

ID_LEDGER_RE = re.compile(r"^FM-\d+$")


def load_known_ids(path: Path) -> set[str] | None:
    """Every canonical ID that has ever existed.

    Returns None when the ledger is ABSENT -- deliberately distinct from an
    empty set. "The baseline is missing" and "the baseline says nothing was
    ever here" are different defects and both are fatal, but conflating them
    would hide which one occurred.

    Raises ValueError on a malformed line rather than skipping it: a dropped
    line silently shrinks the baseline, which is the very thing this guards.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None

    ids: set[str] = set()
    for number, line in enumerate(raw.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if not ID_LEDGER_RE.match(entry):
            raise ValueError(f"{path}:{number}: malformed ledger entry: {entry!r}")
        ids.add(entry)
    return ids


def validate_catalog(
    text: str,
    rows: list[CatalogRow],
    known_ids: set[str] | None | object = LEDGER_NOT_REQUESTED,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not rows and known_ids is LEDGER_NOT_REQUESTED:
        errors.append("no canonical FM rows found")
        return errors, warnings

    # --- append-only ID-set invariant (G3) ---------------------------------
    # Replaces the advisory ordering rule, which fired five times per run on a
    # catalog with zero gaps and zero duplicates and never once indicated a
    # defect. Ordering was never the property anyone cared about; not LOSING a
    # row is -- CLAUDE.md names it a non-negotiable because deleting rows to
    # satisfy a validator nearly lost FM-REC-01..11.
    if known_ids is not LEDGER_NOT_REQUESTED:
        if known_ids is None:
            errors.append(
                "id ledger could not be read; refusing to certify the catalog. "
                "A gate that cannot find its baseline must refuse, never pass."
            )
        elif not known_ids:
            errors.append(
                "id ledger is empty; 'nothing was removed' would be vacuously "
                "true. Refusing to certify the catalog on an empty baseline."
            )
        else:
            present = {row.fm_id for row in rows}
            missing = sorted(
                known_ids - present,
                key=lambda i: int(i.split("-")[1]),
            )
            if missing:
                errors.append(
                    "canonical IDs removed from the catalog: "
                    f"{', '.join(missing)}. Rows are append-only -- renumber or "
                    "fix the rule, never delete the data (the rule is younger "
                    "than the data)."
                )

    if not rows:
        errors.append("no canonical FM rows found")
        return errors, warnings

    duplicate_lines: dict[str, list[int]] = {}
    for row in rows:
        duplicate_lines.setdefault(row.fm_id, []).append(row.line)
    for fm_id, lines in sorted(duplicate_lines.items()):
        if len(lines) > 1:
            errors.append(
                f"duplicate canonical ID {fm_id} on lines {', '.join(map(str, lines))}"
            )

    # G3: the advisory ordering rule was REMOVED here, not demoted again.
    # Measured on 150 rows: zero gaps, zero duplicates, five out-of-order
    # transitions -- so it fired five times a run and never once indicated a
    # defect. Noise on a gate trains people to ignore the gate. Its replacement
    # is the append-only invariant above, which pins a property that matters.
    # Pinned in both directions by guard/tests/test_append_only.py.

    for line_number, line in enumerate(text.splitlines(), start=1):
        match = HISTORICAL_SCHEME_RE.search(line)
        if match:
            errors.append(
                f"historical alias scheme {match.group(0)} appears in canonical catalog on line {line_number}"
            )

    return errors, warnings


def next_id(rows: list[CatalogRow]) -> str:
    next_number = max(row.number for row in rows) + 1
    return f"FM-{next_number:02d}"


SELF_ROOT_TOKEN = "SELF"


def _repo_root() -> Path:
    """This checkout's own root -- present in ANY environment running this
    file, unlike ~/projects/<name>, which only exists on a machine that
    happens to have that repo cloned there (true on a dev workstation,
    false on a CI runner that checks out only this one repo)."""
    return Path(__file__).resolve().parents[1]


def _resolve_source_root(
    source: str, source_roots: dict[str, str], projects_dir: Path
) -> tuple[Path | None, str | None]:
    """Return (root, None) if resolvable, or (None, reason) if not.

    Two distinct UNVERIFIABLE reasons, kept distinguishable in the reason
    string: no mapping was ever established (root unknown), vs a mapping
    exists but the target directory isn't checked out on this machine.

    The SELF_ROOT_TOKEN maps to this checkout's own root regardless of
    projects_dir -- for the one L1 source (homelab-canon) whose "repo" IS
    this repo, so it resolves everywhere this script runs, CI included.
    """
    relpath = source_roots.get(source)
    if relpath is None:
        return None, "no root mapping for this source in source-roots.conf"
    candidate = _repo_root() if relpath == SELF_ROOT_TOKEN else (projects_dir / relpath).resolve()
    if not candidate.is_dir():
        return None, f"root not present on this machine: {candidate}"
    return candidate, None


def verify_enforcement(
    l1_dir: Path, projects_dir: Path, source_roots: dict[str, str]
) -> EnforcementReport:
    """Check that every claimed enforcement path resolves within its OWN source's root.

    Each L1 source was extracted from a different repo. A path is:
      - enforced      -- that source's root is known and present, and the path resolves.
      - phantom       -- that source's root is known and present, and the path does NOT
                          resolve. This is the only class that is FATAL.
      - UNVERIFIABLE  -- that source's root is unknown, or known but not checked out on
                          this machine. Reported loudly with a count; never silently
                          folded into "enforced" -- it is an admission, not a pass.

    A resolved path establishes only that a claimed mechanism still exists.
    A ``hook`` must be a regular executable file. A ``test`` must be regular
    and executable, except for runner-managed Pytest sources with a valid test
    AST or Bats/``*.test.js`` sources with bounded whole-file structural
    plausibility. A present, non-executable stub is a phantom. The verifier
    intentionally makes no broader claim that a plausible file enforces its
    recorded lesson, and the Bats/JavaScript recognizers are not full parsers.
    """
    if not l1_dir.is_dir():
        raise ValueError(f"L1 directory not found: {l1_dir}")

    projects_root = projects_dir.resolve()
    sources: dict[str, SourceTotals] = {}
    phantoms: list[str] = []
    unverifiable: list[str] = []
    roots_resolved: dict[str, Path] = {}
    roots_unresolved: dict[str, str] = {}

    for jsonl_path in sorted(l1_dir.glob("*.jsonl")):
        source = jsonl_path.stem
        totals = sources.setdefault(source, SourceTotals())
        # Resolved once per source, unconditionally -- not lazily on first use.
        # A source whose every entry happens to be unbacked (enforcement: null)
        # still has a real, checkable root, and ROOTS/--require-roots must see
        # that root as present regardless of whether anything needed it yet.
        source_root, root_reason = _resolve_source_root(source, source_roots, projects_root)
        if source_root is not None:
            roots_resolved[source] = source_root
        else:
            roots_unresolved[source] = root_reason or "unresolved"

        for line_number, line in enumerate(
            jsonl_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                raise ValueError(f"blank L1 record in {jsonl_path}:{line_number}")
            try:
                record: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {jsonl_path}:{line_number}: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise TypeError(f"L1 record is not an object in {jsonl_path}:{line_number}")

            auto = record.get("auto")
            if auto == "machine":
                totals.machine += 1
            elif auto == "judgment":
                totals.judgment += 1
            else:
                raise ValueError(
                    f"invalid auto value in {jsonl_path}:{line_number}: {auto!r}"
                )

            enforcement = record.get("enforcement")
            if enforcement is None:
                if auto == "machine":
                    totals.unbacked += 1
                continue
            if not isinstance(enforcement, dict):
                raise TypeError(
                    f"invalid enforcement in {jsonl_path}:{line_number}: expected object or null"
                )
            enforcement_file = enforcement.get("file")
            if not isinstance(enforcement_file, str) or not enforcement_file:
                raise ValueError(
                    f"invalid enforcement.file in {jsonl_path}:{line_number}: expected non-empty string"
                )

            totals.enforcement_bearing += 1

            entry_id = record.get("id", "<missing id>")
            if source_root is None:
                totals.unverifiable += 1
                unverifiable.append(
                    f"unverifiable: {enforcement_file} ({source}:{entry_id}, "
                    f"{jsonl_path}:{line_number}) -- {root_reason}"
                )
                continue

            totals.checked += 1
            resolved = (source_root / enforcement_file).resolve()
            contained = resolved.is_relative_to(source_root)
            resolved_mode: int | None = None
            if contained:
                try:
                    resolved_mode = resolved.stat().st_mode
                except OSError:
                    pass
            if resolved_mode is None:
                totals.phantoms += 1
                phantoms.append(
                    PhantomEntry(
                        source=source,
                        entry_id=str(entry_id),
                        enforcement_file=enforcement_file,
                        location=f"{jsonl_path}:{line_number}",
                    )
                )
                continue

            kind = enforcement.get("kind")
            executable_kind = kind in {"test", "hook"}
            executable_file = stat.S_ISREG(resolved_mode) and bool(
                resolved_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            )
            plausible_mechanism = (
                not executable_kind
                or executable_file
                or (kind == "test" and _is_runner_managed_test_source(resolved))
            )
            if not plausible_mechanism:
                totals.phantoms += 1
                phantoms.append(
                    PhantomEntry(
                        source=source,
                        entry_id=str(entry_id),
                        enforcement_file=enforcement_file,
                        location=f"{jsonl_path}:{line_number}",
                    )
                )

    return EnforcementReport(
        sources=sources,
        phantoms=phantoms,
        unverifiable=unverifiable,
        roots_resolved=roots_resolved,
        roots_unresolved=roots_unresolved,
        mapped_sources=len(source_roots),
    )


def print_enforcement_report(report: EnforcementReport) -> None:
    """Print the verifier's intentionally limited result to stderr."""
    unbacked = sum(total.unbacked for total in report.sources.values())
    if unbacked:
        print(
            f"enforcement-verifier: WARNING: {unbacked} machine entries have no enforcement",
            file=sys.stderr,
        )

    unverifiable_count = sum(total.unverifiable for total in report.sources.values())
    if unverifiable_count:
        print(
            f"enforcement-verifier: UNVERIFIABLE: {unverifiable_count} enforcement-bearing entries could "
            "not be checked (source root unknown or not present on this machine) -- this is "
            "an admission, not a pass:",
            file=sys.stderr,
        )
        for line in report.unverifiable:
            print(f"enforcement-verifier: {line}", file=sys.stderr)

    for phantom in report.phantoms:
        print(f"enforcement-verifier: {phantom.format()}", file=sys.stderr)

    print(
        "enforcement-verifier: summary (source machine judgment unbacked "
        "phantoms[-=not-measured] unverifiable checked)",
        file=sys.stderr,
    )
    for source, totals in report.sources.items():
        phantoms = "-" if totals.checked == 0 else str(totals.phantoms)
        print(
            f"  {source}: {totals.machine} {totals.judgment} "
            f"{totals.unbacked} {phantoms} {totals.unverifiable} {totals.checked}",
            file=sys.stderr,
        )

    print(
        f"enforcement-verifier: ROOTS: {len(report.roots_resolved)}/{report.mapped_sources} "
        "mapped source roots are present on this machine:",
        file=sys.stderr,
    )
    for source in sorted(report.roots_unresolved):
        print(f"  {source}: {report.roots_unresolved[source]}", file=sys.stderr)

    print(
        "enforcement-verifier: SCOPE: checks containment and existence; hooks and tests must be "
        "regular executable files, except runner-managed Pytest (.py) sources with a test AST, or "
        "bounded whole-file structurally plausible Bats (.bats) and *.test.js sources. These are "
        "not full Bats/JavaScript parsers. A plausible path is necessary, not sufficient evidence "
        "that it enforces the claimed lesson. "
        "UNVERIFIABLE entries were not checked at all -- they are neither enforced nor phantom.",
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", nargs="?", type=Path, default=default_catalog_path())
    parser.add_argument(
        "--next-id",
        action="store_true",
        help="print the next canonical FM ID instead of the validation summary",
    )
    parser.add_argument(
        "--verify-enforcement",
        action="store_true",
        help="verify that claimed L1 enforcement paths exist under their own source's repo root",
    )
    parser.add_argument(
        "--require-roots",
        type=int,
        default=1,
        metavar="N",
        help=(
            "fail with ERROR (not phantom, not a pass) if fewer than N mapped source roots "
            "actually verified at least one entry on this machine (a root that merely "
            "resolves but checked zero entries does not count -- see SourceTotals.checked). "
            "Default 1. If literally zero roots resolve at all this is always an ERROR "
            "regardless of this flag; if some roots resolve but none of them verified "
            "anything (the CI-with-only-SELF case), the run is a declared SKIP (exit 0), "
            "not a vacuous pass and not an ERROR -- an environment that structurally cannot "
            "check anything is not the same as one that is misconfigured."
        ),
    )
    parser.add_argument(
        "--accept-phantom",
        action="store_true",
        help=(
            "allow phantoms not yet listed in conf/known-phantoms.conf to pass THIS RUN "
            "ONLY, with a loud WARNING. Does not write the ledger -- add the entry (with "
            "evidence and disposition) to known-phantoms.conf yourself; this flag exists so "
            "growing the debt is always a deliberate, visible act, never silent."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify_enforcement:
        try:
            source_roots = load_source_roots(default_source_roots_path())
        except ValueError as exc:
            print(f"enforcement-verifier: {exc}", file=sys.stderr)
            return 1
        try:
            report = verify_enforcement(default_l1_dir(), default_projects_dir(), source_roots)
        except (TypeError, ValueError) as exc:
            print(f"enforcement-verifier: {exc}", file=sys.stderr)
            return 1

        try:
            known = load_known_phantoms(default_known_phantoms_path())
        except ValueError as exc:
            print(f"enforcement-verifier: {exc}", file=sys.stderr)
            return 1

        print_enforcement_report(report)

        unbacked = sum(totals.unbacked for totals in report.sources.values())
        resolved_count = len(report.roots_resolved)
        useful_sources = {
            source
            for source, totals in report.sources.items()
            if source in report.roots_resolved and totals.checked > 0
        }
        useful_count = len(useful_sources)
        checked_count = sum(totals.checked for totals in report.sources.values())

        print(
            f"enforcement-verifier: PHANTOM-DEBT: {len(known)} documented in "
            "conf/known-phantoms.conf",
            file=sys.stderr,
        )
        print(
            f"enforcement-verifier: DEBT: {len(known)} known phantom(s) documented in "
            "conf/known-phantoms.conf -- this number should shame us into fixing them, "
            "not sit as a silent allowlist.",
            file=sys.stderr,
        )
        print(
            f"enforcement-verifier: UNBACKED: {unbacked} machine entries carry "
            "enforcement: null",
            file=sys.stderr,
        )
        if checked_count == 0:
            print(
                "enforcement-verifier: PHANTOMS-MEASURED: NOT MEASURED HERE "
                f"(ROOTS {resolved_count}/{report.mapped_sources}, 0 entries checked)",
                file=sys.stderr,
            )
        else:
            print(
                f"enforcement-verifier: PHANTOMS-MEASURED: {len(report.phantoms)} "
                f"across {useful_count} source roots",
                file=sys.stderr,
            )

        # 1. Universal, root-independent floor: total enforcement-bearing
        #    entries must never shrink. Computed straight from the corpus,
        #    so this is a REAL check that runs identically everywhere,
        #    including a CI runner with none of the source repos present --
        #    unlike everything below, which needs a resolved root to mean
        #    anything. This is the fleet#152 defense: a debt ledger can
        #    shrink because a phantom was genuinely fixed, or because the
        #    flagged record was quietly deleted. Only the corpus-wide count
        #    not dropping distinguishes the two.
        try:
            floor = load_enforcement_floor(default_enforcement_floor_path())
        except ValueError as exc:
            print(f"enforcement-verifier: {exc}", file=sys.stderr)
            return 1
        total_bearing = total_enforcement_bearing(report)
        old_machine_bearing = machine_enforcement_bearing(report)
        print(
            f"enforcement-verifier: DEBT-FLOOR: {total_bearing} total enforcement-bearing "
            f"entries (was {old_machine_bearing} machine-only; floor {floor})",
            file=sys.stderr,
        )
        if total_bearing < floor:
            print(
                f"enforcement-verifier: ERROR: enforcement-bearing entry count dropped to "
                f"{total_bearing}, below floor {floor} -- an entry was deleted or its "
                "enforcement value was removed rather than the underlying gap being fixed. "
                "Raise real coverage, or lower the floor explicitly in "
                "conf/enforcement-floor.conf with a recorded reason.",
                file=sys.stderr,
            )
            return 1

        # 2. The root floor, made falsifiable: only roots that actually
        #    verified >=1 entry count as "present" for --require-roots.
        if resolved_count == 0:
            print(
                f"enforcement-verifier: ERROR: 0 of {report.mapped_sources} mapped source "
                "roots are present on this machine at all; refusing to report success on a "
                "check that could not see any of its own inputs.",
                file=sys.stderr,
            )
            return 1

        if useful_count == 0:
            print(
                "enforcement-verifier: SKIPPED: roots are present on this machine but NONE "
                "of them had a single machine entry with non-null enforcement to actually "
                "check -- this environment cannot verify ANY enforcement claim right now. "
                "This is a declared skip, not a pass: rerun where the mapped source repos "
                "are checked out (e.g. a dev workstation with ~/projects populated) for a "
                "real phantom-detection signal.",
                file=sys.stderr,
            )
            return 0

        if useful_count < args.require_roots:
            print(
                f"enforcement-verifier: ERROR: only {useful_count} of "
                f"{report.mapped_sources} mapped source roots actually verified an entry on "
                f"this machine (require >= {args.require_roots}); refusing to report success "
                "on a check that could not see enough of its own inputs.",
                file=sys.stderr,
            )
            return 1

        unlisted = [phantom for phantom in report.phantoms if phantom.key() not in known]
        if unlisted:
            print(
                f"enforcement-verifier: {len(unlisted)} phantom(s) are NOT documented in "
                "conf/known-phantoms.conf:",
                file=sys.stderr,
            )
            for phantom in unlisted:
                print(f"enforcement-verifier: undocumented: {phantom.format()}", file=sys.stderr)
            if not args.accept_phantom:
                print(
                    "enforcement-verifier: ERROR: new phantoms cannot land silently. Add each "
                    "one to conf/known-phantoms.conf with evidence and a disposition, or pass "
                    "--accept-phantom to force this run through (does not update the ledger).",
                    file=sys.stderr,
                )
                return 1
            print(
                "enforcement-verifier: WARNING: --accept-phantom set -- allowing "
                f"{len(unlisted)} undocumented phantom(s) through THIS RUN ONLY. Add them to "
                "conf/known-phantoms.conf before merging.",
                file=sys.stderr,
            )

        return 0

    catalog_path: Path = args.catalog

    try:
        text = catalog_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    rows = parse_rows(text)

    # The gate ALWAYS evaluates the append-only invariant. load_known_ids
    # returns None when the ledger is absent, and validate_catalog treats that
    # as fatal -- there is no path through this entry point that skips it.
    ledger_path = catalog_path.parent / "id-ledger.txt"
    try:
        known_ids = load_known_ids(ledger_path)
    except ValueError as exc:
        print(f"failure-mode-catalog: {exc}", file=sys.stderr)
        return 1

    errors, warnings = validate_catalog(text, rows, known_ids=known_ids)
    for warning in warnings:
        print(f"failure-mode-catalog: warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"failure-mode-catalog: {error}", file=sys.stderr)
        return 1

    if args.next_id:
        print(next_id(rows))
    else:
        print(
            f"failure-mode-catalog: OK ({len(rows)} canonical IDs, next {next_id(rows)})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
