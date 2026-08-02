#!/usr/bin/env python3
"""Validate catalog invariants and expose unverifiable claimed enforcement.

The catalog is a registry, not a record of aspirations.  L1 entries that name
an enforcement file need a cheap reality check, while entries honestly marked
as unbacked must remain visible without being treated as build failures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

ROW_RE = re.compile(r"^\| (FM-(\d{2,3})) \|")
# Legacy schemes are only a defect when used as a ROW ID. The same strings
# appear legitimately as provenance annotations inside the bug-class column
# (e.g. "Container Runtime - Design (FM-RC-01)") and must not be flagged.
HISTORICAL_SCHEME_RE = re.compile(r"^\| *FM-(RC|REC)-\d+ *\|")


@dataclass(frozen=True)
class CatalogRow:
    fm_id: str
    number: int
    line: int


@dataclass
class SourceTotals:
    machine: int = 0
    judgment: int = 0
    unbacked: int = 0
    phantoms: int = 0
    unverifiable: int = 0
    # Incremented once per machine entry that had a non-null enforcement
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


@dataclass
class VerificationRun:
    """The measured outcome of one full --verify-enforcement pass.

    C4g: factored out of main() so --write-attestation can drive the exact
    same real check main() has always run for a human on a workstation --
    never a second, hand-rolled implementation that could quietly drift
    from it -- and capture its measured results for the attestation
    payload. `exit_code` and the printed stderr trail are unchanged from
    before this existed; this is purely an additional return channel.
    """

    exit_code: int
    skipped: bool = False
    report: EnforcementReport | None = None
    mapped_sources_floor: int = 0
    enforcement_floor: int = 0
    checked_floor: int = 0
    total_checked: int = 0
    total_bearing: int = 0
    resolved_count: int = 0
    useful_count: int = 0
    known_count: int = 0
    unlisted_phantoms: list[PhantomEntry] = field(default_factory=list)


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


def default_mapped_sources_floor_path() -> Path:
    return Path(__file__).resolve().parents[1] / "conf" / "mapped-sources-floor.conf"


def default_checked_floor_path() -> Path:
    return Path(__file__).resolve().parents[1] / "conf" / "checked-floor.conf"


def default_unmapped_sources_path() -> Path:
    return Path(__file__).resolve().parents[1] / "conf" / "unmapped-sources.conf"


def load_source_roots(path: Path, projects_dir: Path | None = None) -> dict[str, str]:
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
    validate_source_roots(mapping, path, projects_dir or default_projects_dir())
    return mapping


def validate_source_roots(mapping: dict[str, str], path: Path, projects_dir: Path) -> None:
    """Reject roots that would reopen the cross-repo phantom leak this area
    exists to close, at CONFIG-VALIDATION time -- before any path on disk is
    even looked at, so this fires in every environment including one where
    no source repo is checked out.

    C4e (D3): this MUST resolve each candidate before judging it, never
    compare the raw config string. A lexical check (`relpath == "."`, or
    ancestor comparison over `PurePosixPath` strings built straight from the
    config text) is defeated by anything that isn't already in canonical
    form: `./`, `./.`, `..`, `fleet/..` all resolve to projects_dir itself
    exactly like `.` does, and an ABSOLUTE relpath defeats it completely --
    `(projects_dir / relpath).resolve()` uses pathlib's absolute-join
    semantics, which silently DISCARD the left operand, so an absolute path
    anywhere on the filesystem (inside or outside ~/projects) sailed through
    a lexical `is_relative_to(PurePosixPath("."))`-style check untouched.
    Resolving first and judging the resulting real `Path` closes all of
    these at once, in one place, instead of pattern-matching each string
    shape individually.

    A root that resolves to projects_dir itself (or an ancestor of it, e.g.
    `..`) makes every file under EVERY OTHER mapped repo resolve as
    "enforced" for whichever source carries that root -- a
    substack/README.md entry would pass as an enforced fleet-dispatch
    mechanism. Same for any root resolving OUTSIDE projects_dir entirely
    (an absolute path to a sibling directory, another disk, anywhere): nothing
    scopes what such a root's entries can resolve against. Same defect,
    different shape, if any mapped root is a strict ancestor of another
    mapped root (the ancestor's source could resolve into the descendant's
    files) -- that comparison is now also done on resolved `Path`s, not
    `PurePosixPath` strings built from the raw config text, for the same
    reason. SELF is exempt from both checks: it resolves to this checkout's
    own root via `_repo_root()`, never through `projects_dir`, so it cannot
    be projects_dir, an ancestor of it, or a subdirectory of another mapped
    root's resolved path (and it cannot contain one either -- SELF's root
    is not derived from projects_dir at all).
    """
    projects_root = projects_dir.resolve()
    non_self = {s: r for s, r in mapping.items() if r != SELF_ROOT_TOKEN}

    resolved: dict[str, Path] = {}
    for source, relpath in non_self.items():
        candidate = (projects_dir / relpath).resolve()
        if (
            candidate == projects_root
            or projects_root.is_relative_to(candidate)
            or not candidate.is_relative_to(projects_root)
        ):
            raise ValueError(
                f"source-roots entry {source!r} in {path} maps to {relpath!r}, which resolves "
                f"to {candidate} -- forbidden: that is not a proper subdirectory strictly "
                f"inside ~/projects ({projects_root}); it is either projects_dir itself, an "
                "ancestor of it, or outside it entirely. This reopens the cross-repo phantom "
                f"leak this check exists to close (any file under {candidate} could resolve "
                f"as enforced for {source!r}). Map to a specific repo subdirectory strictly "
                f"inside ~/projects, or declare {source!r} unmappable in "
                "conf/unmapped-sources.conf with a reason if its enforcement paths genuinely "
                "cannot be scoped to one repo."
            )
        resolved[source] = candidate

    for source_a, path_a in resolved.items():
        for source_b, path_b in resolved.items():
            if source_a == source_b:
                continue
            if path_a == path_b:
                continue
            if path_b.is_relative_to(path_a):
                raise ValueError(
                    f"source-roots entry {source_a!r} ({mapping[source_a]}) in {path}, "
                    f"resolving to {path_a}, is an ancestor of {source_b!r} "
                    f"({mapping[source_b]}, resolving to {path_b}) -- forbidden: "
                    f"{source_a}'s entries could resolve against {source_b}'s files too, "
                    "reopening the cross-repo phantom leak this check exists to close."
                )


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
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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


def load_mapped_sources_floor(path: Path) -> int:
    """Load the minimum acceptable count of mapped entries in source-roots.conf.

    D1: the honesty ratio ROOTS prints (resolved/mapped) has NO floor on its
    own denominator -- shrinking source-roots.conf (deleting a line, or
    reducing it to a single trivially-satisfied entry) makes every phantom
    it used to see UNVERIFIABLE, exits 0, and *improves* the reported ratio,
    because the ratio's denominator shrank along with the numerator. This
    floor makes the map itself falsifiable: it may grow (a new source gets
    mapped) but may not shrink without an explicit, recorded reason here,
    same idiom as conf/enforcement-floor.conf.

    Missing or malformed -> ValueError (fail loud), identical rationale to
    load_enforcement_floor: a floor file that vanished must not read as
    "floor 0, any map size passes."
    """
    if not path.is_file():
        raise ValueError(f"mapped-sources floor file not found: {path}")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(lines) != 1:
        raise ValueError(f"mapped-sources floor file must contain exactly one value: {path}")
    try:
        return int(lines[0])
    except ValueError as exc:
        raise ValueError(f"mapped-sources floor value is not an integer: {lines[0]!r}") from exc


def load_checked_floor(path: Path) -> int:
    """Load the minimum acceptable count of entries actually CHECKED.

    D2: `total_enforcement_bearing` is deliberately root-independent (see its
    docstring) so it is computable in any environment -- but that same
    property makes it paddable: a new machine entry with a non-null
    enforcement value in an UNMAPPED (or not-checked-out) source raises the
    bearing total by 1 without ever being checked, pre-paying floor headroom
    that could later offset deleting a genuinely CHECKED entry elsewhere.
    This floor is on `checked` specifically -- units actually run through
    the exists() test, wherever roots resolve -- so padding an unverifiable
    source cannot buy cover for shrinking real, verified coverage.

    Unlike the enforcement-bearing floor, this one is only fully enforced in
    an environment where ~/projects actually exists on disk (see
    `structurally_cannot_check` in main()); an environment where it is
    entirely ABSENT (CI with no source repos checked out at all) legitimately
    has checked == 0 and is exempted for that specific, narrow reason -- see
    main()'s CHECKED-FLOOR block. C4e (finding 2): this is deliberately
    narrower than "useful_count == 0" -- a workstation that HAS ~/projects
    but was configured (via source-roots.conf / unmapped-sources.conf edits)
    to check nothing is NOT exempt; only the directory's outright absence is.

    Missing or malformed -> ValueError (fail loud), same idiom as the other
    floor loaders.
    """
    if not path.is_file():
        raise ValueError(f"checked floor file not found: {path}")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(lines) != 1:
        raise ValueError(f"checked floor file must contain exactly one value: {path}")
    try:
        return int(lines[0])
    except ValueError as exc:
        raise ValueError(f"checked floor value is not an integer: {lines[0]!r}") from exc


def default_git_ref() -> str:
    """The git ref floor files are ratcheted against.

    `origin/main`, not `HEAD~1`: floors must only grow relative to the
    branch this work will land on. A `HEAD~1` comparison would miss an
    unauthorized decrease made one commit earlier on the SAME feature
    branch (that decrease would already be "the previous commit" by the
    time anyone re-runs this).
    """
    return "origin/main"


def _read_floor_int_at_revision(repo_root: Path, relpath: Path, revision: str) -> int | None:
    """`git show <revision>:<relpath>`, parsed as a single floor integer, or
    None on any failure (bad revision, path absent at that revision,
    unparseable content). Never raises."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{revision}:{relpath.as_posix()}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(lines) != 1:
        return None
    try:
        return int(lines[0])
    except ValueError:
        return None


def previous_floor_value(path: Path, ref: str) -> int | None:
    """Best-effort high-water mark of a floor file's value, for ratchet
    enforcement (C4e, finding 3).

    Computed as the MAXIMUM ever committed across two sources: (1) the
    content at `ref` (origin/main -- the branch this work will eventually
    land on), and (2) every commit reachable from HEAD that touched this
    exact file (this branch's OWN history). (2) matters on its own: a
    brand-new floor file (like conf/checked-floor.conf and
    conf/mapped-sources-floor.conf, both introduced mid-campaign and not
    yet on `ref` at all) would otherwise have NO ratchet protection for as
    long as its introducing PR stays unmerged -- any later commit on the
    SAME still-open branch could silently re-lower a value that branch
    itself already committed, and a `ref`-only comparison would see no
    history at all and wave it through. Walking this branch's own log
    closes that: the value C4d already committed here is caught the
    moment C4e tries to lower it further, with no dependency on C4d having
    merged first.

    Returns None -- never raises -- only when NEITHER source yields a
    single resolvable integer anywhere: this checkout isn't a git
    repository, git isn't installed, or the file has no history at all on
    either `ref` or HEAD (freshly created, uncommitted).

    C4f (HIGH-1): `None` used to mean "ratchet enforcement is skipped for
    this run, silently" -- but a real CI run demonstrated exactly why that
    is wrong: a shallow (`fetch-depth: 1`) checkout has no `origin/main`
    remote-tracking ref at all (this function's first source), AND its
    single-commit history means the HEAD-log fallback (its second source)
    can only ever find the checked-out tip commit -- whose committed value
    IS the current value. That shape doesn't even reach this "return None"
    branch; it silently returns a *value* (current, disguised as
    previous), which is arguably worse. This docstring's caller,
    `check_floor_ratchet`, now treats `None` as "I could not verify this
    did not shrink" and refuses to pass silently (see its own docstring) --
    "could not check" must never read as "checked and fine". The real fix
    for the shallow-checkout shape is giving the checkout real history
    (`.github/workflows/guard.yml`'s `fetch-depth: 0`); this function's
    contract (never raise, return None when truly undeterminable) is
    unchanged -- only what the caller DOES with a `None` result changed.
    """
    try:
        repo_root = _repo_root()
        relpath = path.resolve().relative_to(repo_root)
    except (OSError, ValueError):
        return None

    candidates: list[int] = []

    ref_value = _read_floor_int_at_revision(repo_root, relpath, ref)
    if ref_value is not None:
        candidates.append(ref_value)

    try:
        log = subprocess.run(
            ["git", "-C", str(repo_root), "log", "--format=%H", "HEAD", "--", relpath.as_posix()],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        log = None
    if log is not None and log.returncode == 0:
        for commit_hash in log.stdout.split():
            value = _read_floor_int_at_revision(repo_root, relpath, commit_hash)
            if value is not None:
                candidates.append(value)

    return max(candidates) if candidates else None


def parse_floor_decrease_flags(raw: list[str]) -> dict[str, str]:
    """Parse repeated `--allow-floor-decrease NAME=REASON` values.

    Fails loud on a malformed entry (no `=`, or an empty name/reason) --
    same idiom as every other config parser in this file: a flag that
    silently did nothing would be worse than not having the escape hatch
    at all, because it would look like the reason was recorded when it
    wasn't.
    """
    parsed: dict[str, str] = {}
    for entry in raw:
        name, sep, reason = entry.partition("=")
        name = name.strip()
        reason = reason.strip()
        if not sep or not name or not reason:
            raise ValueError(
                f"malformed --allow-floor-decrease value {entry!r}: expected NAME=REASON "
                "with both halves non-empty"
            )
        parsed[name] = reason
    return parsed


def check_floor_ratchet(
    label: str,
    path: Path,
    current: int,
    previous: int | None,
    decrease_reasons: dict[str, str],
) -> tuple[bool, str | None]:
    """Returns (ok, message). `ok` is True with no message ONLY when a
    previous value was actually determined AND `current >= previous` --
    the one case that is genuinely, silently fine.

    `ok` is False for a SILENT, unauthorized decrease, exactly as before --
    but ALSO, C4f (HIGH-1/MEDIUM-3), for an INDETERMINATE `previous`
    (`previous is None`), unless explicitly overridden via
    `--allow-floor-decrease`. The old behavior treated `previous is None`
    identically to "confirmed not a decrease" and returned `(True, None)`
    -- completely silent, no ERROR, no WARNING, nothing printed. That is
    this repo's one forbidden move: "I could not check" read as "it is
    fine". It also means a real bug (a shallow CI checkout whose
    `previous_floor_value` genuinely cannot resolve `origin/main` or real
    history) produced a green run with zero diagnostic trace that the
    ratchet never actually evaluated. An authorized override (label present
    in `decrease_reasons`) is `ok = True` but still returns a loud message,
    same idiom as an authorized decrease: permission to proceed without
    verification must never be quiet just because it was granted.
    """
    if previous is None:
        reason = decrease_reasons.get(label)
        if reason is None:
            return False, (
                f"{label} in {path}: could not determine the previous committed value at "
                f"{default_git_ref()} or anywhere in this branch's own history, so it is "
                "impossible to confirm this run did not silently shrink it -- 'could not "
                "check' is never 'it is fine'. This usually means the checkout lacks the git "
                "history the ratchet needs (e.g. a shallow clone with no origin/main "
                "remote-tracking ref -- fetch-depth: 0 on actions/checkout fixes that) rather "
                "than a genuine absence of any prior value. If you have manually confirmed "
                f"this is not a real decrease, pass --allow-floor-decrease {label}=\"<reason>\" "
                "to proceed anyway."
            )
        return True, (
            f"WARNING: {label} in {path}: previous committed value could not be determined "
            f"(see check_floor_ratchet for why) -- proceeding WITHOUT ratchet verification, "
            f"authorized via --allow-floor-decrease with reason: {reason!r}. This flag does "
            "not persist -- the reason must also be recorded in the conf file's own comments "
            "before this lands."
        )
    if current >= previous:
        return True, None
    reason = decrease_reasons.get(label)
    if reason is None:
        return False, (
            f"{label} dropped from {previous} (at {default_git_ref()}) to {current} in "
            f"{path} without --allow-floor-decrease {label}=\"<reason>\" -- floors may only "
            "shrink as an explicit, deliberate, loud act, never as a silent side effect of "
            "an unrelated edit. If this decrease is genuinely intended, pass "
            f"--allow-floor-decrease {label}=\"<reason>\" and record the same reason in "
            f"{path}'s own comments."
        )
    return True, (
        f"WARNING: {label} dropped from {previous} to {current} in {path}, authorized via "
        f"--allow-floor-decrease with reason: {reason!r}. This flag does not persist -- the "
        "reason must also be recorded in the conf file's own comments before this lands."
    )


def load_unmapped_sources(path: Path) -> dict[str, dict[str, str]]:
    """Load the ledger of L1 sources explicitly declared unmappable.

    D2 (other half): an L1 source with no line in source-roots.conf was
    previously a silent, undocumented free pass -- nothing forced anyone to
    say WHY it has no root, and a brand-new source could sit unmapped
    forever with no record that anyone ever noticed. Every L1 source must
    now be either mapped, or listed here with a reason (this is enforced by
    `validate_source_coverage`, called from main() against the live L1
    directory listing). Declaring a source here does not make its entries
    enforced or checked -- they remain UNVERIFIABLE forever, by design.

    Missing file -> ValueError (fail loud), same idiom as
    load_known_phantoms: a declarations file that silently vanished must not
    read as "nothing declared, so nothing to check" -- that is
    indistinguishable from the coverage requirement never having existed.
    An EMPTY (but present) file is valid only if every L1 source happens to
    be mapped; `validate_source_coverage` is what actually enforces that.
    """
    if not path.is_file():
        raise ValueError(f"unmapped-sources declarations not found: {path}")
    declared: dict[str, dict[str, str]] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed unmapped-sources line {path}:{line_number}: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"unmapped-sources line {path}:{line_number} is not an object")
        for field in ("source", "reason"):
            if not isinstance(record.get(field), str) or not record[field]:
                raise ValueError(
                    f"unmapped-sources line {path}:{line_number} missing required field {field!r}"
                )
        declared[record["source"]] = record
    return declared


def validate_source_coverage(
    l1_dir: Path, source_roots: dict[str, str], unmapped_sources: dict[str, dict[str, str]]
) -> None:
    """Every L1 source must be mapped, or declared unmappable -- never neither.

    D2: an L1 source that is neither mapped nor declared was a free pass --
    a new phantom placed there is UNVERIFIABLE, exits 0, AND raises the
    enforcement-bearing floor, pre-paying for a later deletion elsewhere.
    Closing this half does not by itself stop the padding (see
    load_checked_floor for that); it stops the silence -- an unmapped source
    must now be a recorded, deliberate decision, not an omission nobody
    documented.
    """
    if not l1_dir.is_dir():
        raise ValueError(f"L1 directory not found: {l1_dir}")
    for jsonl_path in sorted(l1_dir.glob("*.jsonl")):
        source = jsonl_path.stem
        mapped = source in source_roots
        declared = source in unmapped_sources
        if mapped and declared:
            raise ValueError(
                f"L1 source {source!r} is BOTH mapped in source-roots.conf AND declared "
                "unmappable in conf/unmapped-sources.conf -- these are contradictory; remove "
                "one."
            )
        if not mapped and not declared:
            raise ValueError(
                f"L1 source {source!r} has no root mapping in conf/source-roots.conf and is "
                "not declared unmappable in conf/unmapped-sources.conf -- every L1 source must "
                "be explicitly accounted for. An unmapped, undeclared source is a free pass: a "
                "new phantom placed there is UNVERIFIABLE, exits 0, and inflates the "
                "enforcement-bearing floor without the entry ever being checked."
            )


def total_enforcement_bearing(report: EnforcementReport) -> int:
    """Machine entries with a non-null enforcement value, across all sources.

    Deliberately root-independent (machine - unbacked, not phantoms +
    checked): an unmapped/absent-root source still counts its non-null
    entries here even though it can't be resolved, so this total is
    computable -- and thus a real, always-on gate -- in ANY environment,
    including a CI runner with none of the source repos checked out.
    """
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


def validate_catalog(text: str, rows: list[CatalogRow]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

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

    for previous, current in pairwise(rows):
        if current.number < previous.number:
            warnings.append(
                f"catalog rows out of order: {previous.fm_id} (line {previous.line}) "
                f"precedes {current.fm_id} (line {current.line})"
            )

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
    """Check that machine-entry enforcement paths resolve within their OWN source's root.

    Each L1 source was extracted from a different repo. A path is:
      - enforced      -- that source's root is known and present, and the path resolves.
      - phantom       -- that source's root is known and present, and the path does NOT
                          resolve. This is the only class that is FATAL.
      - UNVERIFIABLE  -- that source's root is unknown, or known but not checked out on
                          this machine. Reported loudly with a count; never silently
                          folded into "enforced" -- it is an admission, not a pass.

    A resolved path establishes only that a claimed mechanism still exists; it
    intentionally makes no claim about whether that file enforces its lesson.
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
                continue
            else:
                raise ValueError(
                    f"invalid auto value in {jsonl_path}:{line_number}: {auto!r}"
                )

            enforcement = record.get("enforcement")
            if enforcement is None:
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
            if not resolved.is_relative_to(source_root) or not resolved.exists():
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


def print_enforcement_report(
    report: EnforcementReport, unmapped_sources: dict[str, dict[str, str]]
) -> None:
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
            f"enforcement-verifier: UNVERIFIABLE: {unverifiable_count} machine entries could "
            "not be checked (source root unknown or not present on this machine) -- this is "
            "an admission, not a pass:",
            file=sys.stderr,
        )
        for line in report.unverifiable:
            print(f"enforcement-verifier: {line}", file=sys.stderr)

    for phantom in report.phantoms:
        print(f"enforcement-verifier: {phantom.format()}", file=sys.stderr)

    print(
        "enforcement-verifier: summary (source machine judgment unbacked phantoms unverifiable checked)",
        file=sys.stderr,
    )
    for source, totals in report.sources.items():
        print(
            f"  {source}: {totals.machine} {totals.judgment} "
            f"{totals.unbacked} {totals.phantoms} {totals.unverifiable} {totals.checked}",
            file=sys.stderr,
        )

    # D7: the denominator here counts MAPPED sources only. Previously an
    # entirely unmapped source (no line in source-roots.conf at all) still
    # landed in roots_unresolved and printed directly beneath a "100%"
    # banner about mapped roots, reading as if a mapped root had failed --
    # it hadn't; it was never mapped in the first place. Split the two.
    mapped_unresolved = {
        source: reason
        for source, reason in report.roots_unresolved.items()
        if source not in unmapped_sources
    }
    print(
        f"enforcement-verifier: ROOTS: {len(report.roots_resolved)}/{report.mapped_sources} "
        "mapped source roots are present on this machine:",
        file=sys.stderr,
    )
    for source in sorted(mapped_unresolved):
        print(f"  {source}: {mapped_unresolved[source]}", file=sys.stderr)

    if unmapped_sources:
        print(
            f"enforcement-verifier: DECLARED-UNMAPPABLE: {len(unmapped_sources)} L1 source(s) "
            "excluded from the ROOTS fraction above by design (conf/unmapped-sources.conf) -- "
            "their entries are always UNVERIFIABLE, never enforced:",
            file=sys.stderr,
        )
        for source in sorted(unmapped_sources):
            print(f"  {source}: {unmapped_sources[source]['reason']}", file=sys.stderr)

    print(
        "enforcement-verifier: SCOPE: checks path existence only; a resolving path "
        "is necessary, not sufficient evidence that it enforces the claimed lesson. "
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
        help="verify that machine L1 enforcement paths exist under their own source's repo root",
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
    parser.add_argument(
        "--ci-no-source-repos",
        action="store_true",
        help=(
            "C4f (HIGH-2): explicitly declare that THIS run's environment structurally has "
            "no mapped source repos checked out at all (e.g. a CI runner that checks out "
            "only this one repo) -- the sole thing that exempts conf/checked-floor.conf from "
            "failing when zero entries were checked. This must be a pinned, committed, "
            "reviewable flag in .github/workflows/guard.yml, never inferred from environment "
            "state (an absent ~/projects, an unset $HOME) that a caller can trivially "
            "reproduce on a fully populated workstation with zero config or code edits. "
            "Default: not set, i.e. this environment is assumed capable of checking source "
            "repos and the checked-floor is fully enforced."
        ),
    )
    parser.add_argument(
        "--write-attestation",
        action="store_true",
        help=(
            "C4g: perform the full local verification (source repos must actually be "
            "checked out -- refuses if --ci-no-source-repos is set, the run would be "
            "SKIPPED, or undocumented phantoms are present even under --accept-phantom) "
            "and, only on a genuinely clean result, write "
            "attestation/enforcement-attestation.json recording a config_digest over "
            "every scope-defining input (conf/source-roots.conf, "
            "conf/unmapped-sources.conf, the three floor files, conf/known-phantoms.conf, "
            "pipeline/L1/*.jsonl) plus the measured results. Run this whenever any of "
            "those files change (.githooks/pre-commit does it automatically) and commit "
            "the result."
        ),
    )
    parser.add_argument(
        "--verify-attestation",
        action="store_true",
        help=(
            "C4g: verify attestation/enforcement-attestation.json instead of running the "
            "enforcement check directly -- for CI, which has no mapped source repos "
            "checked out and cannot perform the real check itself. Fails if the "
            "attestation is missing, unparseable, older than "
            "--max-attestation-age-days, its config_digest does not match what the "
            "current working tree computes, or its recorded results violate the current "
            "floors (checked count below checked-floor, undocumented phantoms, etc.)."
        ),
    )
    parser.add_argument(
        "--max-attestation-age-days",
        type=int,
        default=DEFAULT_ATTESTATION_MAX_AGE_DAYS,
        metavar="N",
        help=(
            "--verify-attestation rejects an attestation older than this many days "
            f"(default {DEFAULT_ATTESTATION_MAX_AGE_DAYS}). A gate that never expires is "
            "a gate that can be satisfied once and then forgotten."
        ),
    )
    parser.add_argument(
        "--allow-floor-decrease",
        action="append",
        default=[],
        metavar="NAME=REASON",
        help=(
            "C4e (finding 3): floors (mapped-sources-floor, enforcement-floor, checked-floor) "
            "may only ever increase relative to conf.default_git_ref() (origin/main) -- a "
            "decrease is otherwise a hard ERROR, never silent. Pass this once per floor being "
            "deliberately lowered, e.g. --allow-floor-decrease checked-floor=\"demapped a "
            "source, see PR body\". Does not persist anything -- record the same reason in "
            "the conf file's own comments before merging. NAME must be one of "
            "mapped-sources-floor, enforcement-floor, checked-floor."
        ),
    )
    return parser


def run_verification(args: argparse.Namespace) -> VerificationRun:
    # ---------------------------------------------------------------
    # Load and validate EVERY config input that decides what gets
    # checked, up front, unconditionally -- before any root-resolution
    # or "can this environment check anything at all" branching below.
    # This is deliberate: every one of these files controls the SCOPE
    # of the check (which sources are mapped, which sources are
    # excused, how low the debt floors may go, which phantoms are
    # already known) and a scope input that only gets read on the
    # "happy path" is exactly how D4 let known-phantoms.conf go missing
    # invisibly on CI -- the SKIPPED return used to happen before its
    # load. Loading everything here means a config file vanishing
    # fails loud in EVERY environment, including one that structurally
    # cannot verify a single path (no source repos checked out).
    try:
        source_roots = load_source_roots(default_source_roots_path(), default_projects_dir())
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    try:
        mapped_sources_floor = load_mapped_sources_floor(default_mapped_sources_floor_path())
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    try:
        unmapped_sources = load_unmapped_sources(default_unmapped_sources_path())
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    try:
        validate_source_coverage(default_l1_dir(), source_roots, unmapped_sources)
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    try:
        floor = load_enforcement_floor(default_enforcement_floor_path())
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    try:
        checked_floor = load_checked_floor(default_checked_floor_path())
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    try:
        known = load_known_phantoms(default_known_phantoms_path())
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    try:
        decrease_reasons = parse_floor_decrease_flags(args.allow_floor_decrease)
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    git_ref = default_git_ref()

    # C4e (finding 3): "a floor the same change can lower is not a
    # floor." Every floor file may only ever increase relative to what
    # was committed at `git_ref` (origin/main) -- a decrease is a hard
    # ERROR unless explicitly authorized via --allow-floor-decrease,
    # which still prints loudly (never a silent pass). This runs
    # before any of the floors are actually applied below, so a
    # decrease is caught regardless of which specific gate would have
    # been affected by it.
    for label, floor_path, current_value in (
        ("mapped-sources-floor", default_mapped_sources_floor_path(), mapped_sources_floor),
        ("enforcement-floor", default_enforcement_floor_path(), floor),
        ("checked-floor", default_checked_floor_path(), checked_floor),
    ):
        previous_value = previous_floor_value(floor_path, git_ref)
        ok, message = check_floor_ratchet(
            label, floor_path, current_value, previous_value, decrease_reasons
        )
        if message is not None:
            prefix = "enforcement-verifier: " if ok else "enforcement-verifier: ERROR: "
            print(f"{prefix}{message}", file=sys.stderr)
        if not ok:
            return VerificationRun(exit_code=1)

    # 0. D1: the map that decides what gets checked must itself be
    #    gated. Computed straight off the loaded mapping -- no
    #    dependency on any root resolving -- so, like the
    #    enforcement-bearing floor below, this is a real check that
    #    runs identically everywhere. Without it, deleting a
    #    source-roots.conf line (or reducing the whole file to one
    #    trivially-satisfied entry) makes its phantoms UNVERIFIABLE,
    #    exits 0, and *improves* the ROOTS ratio, because the
    #    denominator shrinks along with the numerator.
    mapped_count = len(source_roots)
    print(
        f"enforcement-verifier: MAPPED-SOURCES-FLOOR: {mapped_count} sources mapped in "
        f"conf/source-roots.conf (floor {mapped_sources_floor})",
        file=sys.stderr,
    )
    if mapped_count < mapped_sources_floor:
        print(
            f"enforcement-verifier: ERROR: mapped source count dropped to {mapped_count}, "
            f"below floor {mapped_sources_floor} -- a source-roots.conf line was deleted "
            "(or the whole map shrunk) instead of a source being fixed or explicitly "
            "declared unmappable. Restore the mapping, or lower the floor explicitly in "
            "conf/mapped-sources-floor.conf with a recorded reason.",
            file=sys.stderr,
        )
        return VerificationRun(exit_code=1)

    try:
        report = verify_enforcement(default_l1_dir(), default_projects_dir(), source_roots)
    except (TypeError, ValueError) as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return VerificationRun(exit_code=1)
    print_enforcement_report(report, unmapped_sources)

    # 1. Universal, root-independent floor: total enforcement-bearing
    #    entries must never shrink. Computed straight from the corpus,
    #    so this is a REAL check that runs identically everywhere,
    #    including a CI runner with none of the source repos present --
    #    unlike everything below, which needs a resolved root to mean
    #    anything. This is the fleet#152 defense: a debt ledger can
    #    shrink because a phantom was genuinely fixed, or because the
    #    flagged record was quietly deleted. Only the corpus-wide count
    #    not dropping distinguishes the two.
    total_bearing = total_enforcement_bearing(report)
    print(
        f"enforcement-verifier: DEBT-FLOOR: {total_bearing} total enforcement-bearing "
        f"entries (floor {floor})",
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
        return VerificationRun(exit_code=1)

    # 2. The root floor, made falsifiable: only roots that actually
    #    verified >=1 entry count as "present" for --require-roots.
    resolved_count = len(report.roots_resolved)
    useful_sources = {
        source
        for source, totals in report.sources.items()
        if source in report.roots_resolved and totals.checked > 0
    }
    useful_count = len(useful_sources)

    if resolved_count == 0:
        print(
            f"enforcement-verifier: ERROR: 0 of {report.mapped_sources} mapped source "
            "roots are present on this machine at all; refusing to report success on a "
            "check that could not see any of its own inputs.",
            file=sys.stderr,
        )
        return VerificationRun(exit_code=1)

    # 2b. C4e (finding 2): the CHECKED-FLOOR must be evaluated here, in
    # EVERY environment, BEFORE the SKIPPED decision below -- not after
    # it. The old position (after the `useful_count == 0` return) meant
    # this floor was dead code whenever nothing got checked, for ANY
    # reason. That is exactly the exploit: reduce source-roots.conf
    # until every remaining mapped root has checked == 0, and the run
    # takes the same SKIPPED, exit-0 branch a genuinely CI-shaped
    # runner takes -- with the config edit, none of it real config, on
    # a fully populated workstation with all repos checked out.
    #
    # `useful_count == 0` alone cannot tell those two apart -- it is
    # identical in both. C4f (HIGH-2): what DOES differ is no longer
    # keyed on whether ~/projects happens to exist on disk --
    # `default_projects_dir()` is `Path.home()/"projects"`, and
    # `Path.home()` reads `$HOME`; a caller can reproduce "this
    # directory is absent" on a fully populated workstation with zero
    # config or code edits at all (e.g. `HOME=/tmp/nohomehere`), which
    # makes directory-absence a caller-controlled signal, not a
    # trustworthy proxy for "this is really CI". The exemption is now
    # keyed on `--ci-no-source-repos`: an explicit, committed,
    # reviewable flag pinned in .github/workflows/guard.yml, never an
    # environment accident. Without it, the floor is fully enforced
    # regardless of whether ~/projects exists (including the
    # degenerate case where it exists but is empty, or doesn't exist
    # at all but nobody declared why).
    structurally_cannot_check = args.ci_no_source_repos
    total_checked = sum(totals.checked for totals in report.sources.values())
    print(
        f"enforcement-verifier: CHECKED-FLOOR: {total_checked} entries actually verified "
        f"against a resolved root (floor {checked_floor})",
        file=sys.stderr,
    )
    if total_checked < checked_floor:
        if structurally_cannot_check:
            print(
                "enforcement-verifier: CHECKED-FLOOR: exempted this run -- "
                "--ci-no-source-repos was passed, an explicit declaration that this "
                "environment structurally has no source repos checked out at all (e.g. "
                "the CI runner, which checks out only this one repo). Real coverage is "
                "only verified where ~/projects is populated and this flag is NOT passed.",
                file=sys.stderr,
            )
        else:
            print(
                f"enforcement-verifier: ERROR: checked entry count dropped to "
                f"{total_checked}, below floor {checked_floor} -- fewer entries were "
                "actually run through the exists() check than before, even though the "
                "enforcement-bearing total above may look unchanged (e.g. offset by "
                "entries in an unmapped or not-checked-out source, which were never "
                "verified at all). --ci-no-source-repos was not passed, so this "
                "environment is assumed capable of checking source repos and there is no "
                "exemption. Restore real checked coverage; or, if this environment "
                "genuinely cannot check anything by construction, pass "
                "--ci-no-source-repos from a pinned, reviewable CI config (never inferred "
                "from ~/projects being absent); or lower the floor explicitly (with "
                "--allow-floor-decrease checked-floor=\"<reason>\") and record the reason "
                "in conf/checked-floor.conf.",
                file=sys.stderr,
            )
            return VerificationRun(exit_code=1)

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
        return VerificationRun(
            exit_code=0,
            skipped=True,
            report=report,
            mapped_sources_floor=mapped_sources_floor,
            enforcement_floor=floor,
            checked_floor=checked_floor,
            total_checked=total_checked,
            total_bearing=total_bearing,
            resolved_count=resolved_count,
            useful_count=0,
            known_count=len(known),
        )

    if useful_count < args.require_roots:
        print(
            f"enforcement-verifier: ERROR: only {useful_count} of "
            f"{report.mapped_sources} mapped source roots actually verified an entry on "
            f"this machine (require >= {args.require_roots}); refusing to report success "
            "on a check that could not see enough of its own inputs.",
            file=sys.stderr,
        )
        return VerificationRun(exit_code=1)

    # 3. Phantom debt ledger: undocumented (new) phantoms are fatal;
    #    documented ones are visible debt, not a silent allowlist.
    unlisted = [phantom for phantom in report.phantoms if phantom.key() not in known]
    print(
        f"enforcement-verifier: DEBT: {len(known)} known phantom(s) documented in "
        f"conf/known-phantoms.conf -- this number should shame us into fixing them, "
        "not sit as a silent allowlist.",
        file=sys.stderr,
    )
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
            return VerificationRun(exit_code=1)
        print(
            "enforcement-verifier: WARNING: --accept-phantom set -- allowing "
            f"{len(unlisted)} undocumented phantom(s) through THIS RUN ONLY. Add them to "
            "conf/known-phantoms.conf before merging.",
            file=sys.stderr,
        )

    return VerificationRun(
        exit_code=0,
        skipped=False,
        report=report,
        mapped_sources_floor=mapped_sources_floor,
        enforcement_floor=floor,
        checked_floor=checked_floor,
        total_checked=total_checked,
        total_bearing=total_bearing,
        resolved_count=resolved_count,
        useful_count=useful_count,
        known_count=len(known),
        unlisted_phantoms=unlisted,
    )


# ---------------------------------------------------------------------------
# C4g: attestation -- CI cannot check out the source repos, so it cannot run
# the real check itself. A workstation that DOES have them runs
# run_verification() above and, on a clean result, writes a signed record of
# what it measured (--write-attestation); CI verifies that record instead of
# faking the run (--verify-attestation).
# ---------------------------------------------------------------------------

DEFAULT_ATTESTATION_MAX_AGE_DAYS = 14


def default_attestation_path() -> Path:
    return Path(__file__).resolve().parents[1] / "attestation" / "enforcement-attestation.json"


def compute_config_digest(
    l1_dir: Path,
    source_roots_path: Path,
    unmapped_sources_path: Path,
    enforcement_floor_path: Path,
    mapped_sources_floor_path: Path,
    checked_floor_path: Path,
    known_phantoms_path: Path,
) -> str:
    """A hash over the exact bytes of every input that determines the SCOPE
    of the enforcement check: which sources are mapped
    (source-roots.conf), which are declared unmappable
    (unmapped-sources.conf), how low each floor may go (the three floor
    files), which phantoms are already documented (known-phantoms.conf),
    and the full corpus of claimed enforcement paths itself (l1_dir's
    *.jsonl files).

    This -- not the attestation's recorded commit or timestamp -- is the
    property CI actually gates on in --verify-attestation. The one-file
    decoy-roots attack this design exists to close edits
    conf/source-roots.conf; that changes this digest, so a stale attestation
    immediately reads as MISMATCH regardless of how convincing its recorded
    numbers look. An ordinary, honest edit to any of these files (fixing a
    root, adding a floor headroom, documenting a phantom, extracting a new
    L1 record) changes the digest too -- that is the point: it forces a
    fresh --write-attestation before the next CI run will pass, so
    regenerating is the path of least resistance, never an afterthought.

    Deliberately does NOT hash catalog/failure-modes.md, guard/, bin/, or
    .githooks/ -- none of those change WHICH entries get checked or how low
    a floor may go, so hashing them would force needless churn without
    closing anything.

    Takes explicit paths (mirroring every other loader in this file, all of
    which take a `path` rather than reaching for the real repo layout
    directly) rather than a repo root plus hardcoded relative paths, so
    tests can sandbox it exactly like load_source_roots/load_known_phantoms/
    etc. -- and production callers simply pass the real default_*_path()
    functions' results, unchanged.

    Raises ValueError (never silently hashes a partial input set) if any
    required file is missing -- a digest computed over less than the full
    scope would look complete while actually being wrong.
    """
    hasher = hashlib.sha256()
    hasher.update(b"hindsight-config-digest-v1\0")

    labeled_paths: list[tuple[str, Path]] = [
        ("source-roots.conf", source_roots_path),
        ("unmapped-sources.conf", unmapped_sources_path),
        ("enforcement-floor.conf", enforcement_floor_path),
        ("mapped-sources-floor.conf", mapped_sources_floor_path),
        ("checked-floor.conf", checked_floor_path),
        ("known-phantoms.conf", known_phantoms_path),
    ]

    if not l1_dir.is_dir():
        raise ValueError(f"config_digest: L1 directory not found: {l1_dir}")
    l1_paths = sorted(l1_dir.glob("*.jsonl"))
    if not l1_paths:
        raise ValueError(f"config_digest: no *.jsonl files found under {l1_dir}")
    labeled_paths.extend((f"L1/{jsonl_path.name}", jsonl_path) for jsonl_path in l1_paths)

    for label, file_path in labeled_paths:
        if not file_path.is_file():
            raise ValueError(f"config_digest: required scope input missing: {file_path}")
        data = file_path.read_bytes()
        hasher.update(label.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(len(data)).encode("ascii"))
        hasher.update(b"\0")
        hasher.update(data)
        hasher.update(b"\0")

    return f"sha256:{hasher.hexdigest()}"


def _current_config_digest() -> str:
    """compute_config_digest() driven by the real default_*_path() /
    default_l1_dir() functions -- the production entry point both
    write_attestation() and verify_attestation() call. Factored out once so
    both share the exact same input set with no risk of the two drifting
    apart from each other.
    """
    return compute_config_digest(
        default_l1_dir(),
        default_source_roots_path(),
        default_unmapped_sources_path(),
        default_enforcement_floor_path(),
        default_mapped_sources_floor_path(),
        default_checked_floor_path(),
        default_known_phantoms_path(),
    )


def _current_commit(repo_root: Path) -> str | None:
    """`git rev-parse HEAD`, or None on any failure. Never raises."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_attestation(args: argparse.Namespace) -> int:
    """Run the real, full verification and -- only on a genuinely clean
    result -- write attestation/enforcement-attestation.json.

    Deliberately refuses to write (never writes a partial or compromised
    record) when: this environment declared itself unable to check source
    repos (--ci-no-source-repos -- an attestation must come from a REAL
    run); the run was SKIPPED (verified nothing); the run failed outright;
    or undocumented phantoms are present even if --accept-phantom forced
    the exit code to 0 -- an attestation is a claim that a clean run
    happened, and --accept-phantom's whole contract is "let this one run
    through, but never pretend the debt wasn't there."
    """
    if args.ci_no_source_repos:
        print(
            "enforcement-verifier: ERROR: --write-attestation cannot be combined with "
            "--ci-no-source-repos -- an attestation must be written from a real run where "
            "the mapped source repos are actually checked out, never a declared "
            "can't-check environment.",
            file=sys.stderr,
        )
        return 1

    run = run_verification(args)
    if run.exit_code != 0:
        print(
            "enforcement-verifier: ERROR: not writing attestation -- the underlying "
            "verification failed (see errors above). Fix them, then re-run.",
            file=sys.stderr,
        )
        return run.exit_code
    if run.skipped:
        print(
            "enforcement-verifier: ERROR: not writing attestation -- this run verified "
            "nothing (SKIPPED: no mapped root had a single checkable entry on this "
            "machine). Run --write-attestation where the mapped source repos are "
            "actually checked out (a dev workstation with ~/projects populated).",
            file=sys.stderr,
        )
        return 1
    if run.unlisted_phantoms:
        print(
            f"enforcement-verifier: ERROR: not writing attestation -- "
            f"{len(run.unlisted_phantoms)} undocumented phantom(s) are present (this run "
            "only reached exit 0 because --accept-phantom was passed). Add them to "
            "conf/known-phantoms.conf with evidence and a disposition first: an "
            "attestation is a claim that a real, CLEAN run happened, not a run that was "
            "forced through.",
            file=sys.stderr,
        )
        return 1

    report = run.report
    assert report is not None  # exit_code == 0 and not skipped guarantees this

    try:
        digest = _current_config_digest()
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return 1

    commit = _current_commit(_repo_root())
    if commit is None:
        print(
            "enforcement-verifier: ERROR: could not determine the current git commit ('git "
            "rev-parse HEAD' failed) -- an attestation not bound to a specific commit is "
            "meaningless.",
            file=sys.stderr,
        )
        return 1

    per_source = {
        source: {
            "machine": totals.machine,
            "judgment": totals.judgment,
            "unbacked": totals.unbacked,
            "phantoms": totals.phantoms,
            "unverifiable": totals.unverifiable,
            "checked": totals.checked,
        }
        for source, totals in sorted(report.sources.items())
    }
    payload = {
        "version": 1,
        "generated_at": _utc_now_iso(),
        "hostname": socket.gethostname(),
        "commit": commit,
        "config_digest": digest,
        "results": {
            "mapped_sources": report.mapped_sources,
            "roots_resolved": run.resolved_count,
            "total_checked": run.total_checked,
            "total_enforcement_bearing": run.total_bearing,
            "phantom_count": len(report.phantoms),
            "unlisted_phantom_count": len(run.unlisted_phantoms),
            "known_phantom_count": run.known_count,
            "per_source": per_source,
        },
        "floors": {
            "mapped_sources_floor": run.mapped_sources_floor,
            "enforcement_floor": run.enforcement_floor,
            "checked_floor": run.checked_floor,
        },
    }

    attestation_path = default_attestation_path()
    attestation_path.parent.mkdir(parents=True, exist_ok=True)
    attestation_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"enforcement-verifier: ATTESTATION: wrote {attestation_path} -- commit {commit}, "
        f"{run.total_checked} entries checked, config_digest {digest}. Stage it as part of "
        "this commit (.githooks/pre-commit does this automatically when a scope-defining "
        "config file is staged).",
        file=sys.stderr,
    )
    return 0


def verify_attestation(args: argparse.Namespace) -> int:
    """CI's replacement for running the real check it cannot run: verify a
    committed attestation instead of faking the check itself.

    Fails (never a bare, silent pass) when: the attestation is missing or
    unparseable; its config_digest does not match what the CURRENT working
    tree computes (a scope-defining config file changed since it was
    generated); it is older than --max-attestation-age-days; or its
    recorded results violate the floors loaded fresh from the CURRENT conf
    files (never the attestation's own "floors" section, which -- unlike
    config_digest -- is not bound to anything and could be hand-edited
    without touching a single config file's bytes) or contain any
    undocumented phantom.
    """
    path = default_attestation_path()
    if not path.is_file():
        print(
            f"enforcement-verifier: ERROR: no attestation at {path} -- CI cannot verify "
            "enforcement without one (it has no mapped source repos checked out and cannot "
            "run the real check itself). Run `python3 guard/failure_mode_catalog_guard.py "
            "--write-attestation` on a workstation with the mapped source repos checked "
            "out, then commit the result (.githooks/pre-commit does this automatically "
            "when scope-defining config changes).",
            file=sys.stderr,
        )
        return 1

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"enforcement-verifier: ERROR: attestation at {path} is unparseable: {exc}",
            file=sys.stderr,
        )
        return 1
    if not isinstance(data, dict):
        print(
            f"enforcement-verifier: ERROR: attestation at {path} is not a JSON object",
            file=sys.stderr,
        )
        return 1

    try:
        generated_at = data["generated_at"]
        hostname = data["hostname"]
        commit = data["commit"]
        config_digest = data["config_digest"]
        results = data["results"]
        total_checked = int(results["total_checked"])
        total_bearing = int(results["total_enforcement_bearing"])
        mapped_sources = int(results["mapped_sources"])
        unlisted_phantom_count = int(results["unlisted_phantom_count"])
        if not isinstance(generated_at, str) or not isinstance(config_digest, str):
            raise TypeError("generated_at/config_digest must be strings")
    except (KeyError, TypeError, ValueError) as exc:
        print(
            f"enforcement-verifier: ERROR: attestation at {path} is missing or has a "
            f"malformed required field: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        current_digest = _current_config_digest()
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return 1

    if config_digest != current_digest:
        print(
            f"enforcement-verifier: ERROR: attestation config_digest MISMATCH -- "
            f"attestation has {config_digest}, current working tree computes "
            f"{current_digest}. A scope-defining config file (conf/source-roots.conf, "
            "conf/unmapped-sources.conf, the three floor files, "
            "conf/known-phantoms.conf, or pipeline/L1/*.jsonl) changed since this "
            "attestation was generated, without regenerating it. Run `python3 "
            "guard/failure_mode_catalog_guard.py --write-attestation` and commit the "
            "result.",
            file=sys.stderr,
        )
        return 1

    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        print(
            f"enforcement-verifier: ERROR: attestation generated_at {generated_at!r} is "
            "not a parseable ISO-8601 timestamp",
            file=sys.stderr,
        )
        return 1
    if generated_dt.tzinfo is None:
        generated_dt = generated_dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - generated_dt
    max_age = timedelta(days=args.max_attestation_age_days)
    if age > max_age:
        print(
            f"enforcement-verifier: ERROR: attestation is {age} old, past the "
            f"{args.max_attestation_age_days}-day max age -- regenerate it: `python3 "
            "guard/failure_mode_catalog_guard.py --write-attestation`.",
            file=sys.stderr,
        )
        return 1

    # Recompute current floors fresh from conf/*.conf -- never trust the
    # attestation's own "floors" section, which is not bound to anything by
    # config_digest (only conf/*.conf and pipeline/L1/*.jsonl bytes are).
    try:
        mapped_sources_floor = load_mapped_sources_floor(default_mapped_sources_floor_path())
        enforcement_floor = load_enforcement_floor(default_enforcement_floor_path())
        checked_floor = load_checked_floor(default_checked_floor_path())
    except ValueError as exc:
        print(f"enforcement-verifier: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = []
    if mapped_sources < mapped_sources_floor:
        failures.append(
            f"recorded mapped_sources {mapped_sources} below mapped-sources-floor "
            f"{mapped_sources_floor}"
        )
    if total_bearing < enforcement_floor:
        failures.append(
            f"recorded total_enforcement_bearing {total_bearing} below enforcement-floor "
            f"{enforcement_floor}"
        )
    if total_checked < checked_floor:
        failures.append(
            f"recorded total_checked {total_checked} below checked-floor {checked_floor}"
        )
    if unlisted_phantom_count != 0:
        failures.append(
            f"recorded {unlisted_phantom_count} undocumented phantom(s) not in the ledger"
        )

    if failures:
        print(
            "enforcement-verifier: ERROR: attestation's recorded results violate the "
            "current floors:",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"enforcement-verifier: ATTESTATION: from {hostname} at {generated_at}, commit "
        f"{commit}, {total_checked} entries checked ({total_bearing} enforcement-bearing, "
        f"{mapped_sources} mapped sources), digest MATCHES current config, age {age} <= "
        f"{args.max_attestation_age_days}d, floors satisfied (mapped-sources-floor "
        f"{mapped_sources_floor}, enforcement-floor {enforcement_floor}, checked-floor "
        f"{checked_floor}), 0 undocumented phantoms.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.write_attestation:
        return write_attestation(args)
    if args.verify_attestation:
        return verify_attestation(args)
    if args.verify_enforcement:
        return run_verification(args).exit_code

    catalog_path: Path = args.catalog

    try:
        text = catalog_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    rows = parse_rows(text)
    errors, warnings = validate_catalog(text, rows)
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
