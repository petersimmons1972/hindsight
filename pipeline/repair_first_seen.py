#!/usr/bin/env python3
"""Repair missing ``first_seen`` dates on L1 corpus rows (Issue #32).

Why this exists
----------------
242 of 484 L1 rows carry ``"first_seen": null`` -- plan 03 normalises outcomes
per entries logged corpus-wide, so no denominator is trustworthy until the
whole corpus is dated. This tool dates as many of those rows as evidence
allows and leaves the rest honestly undated -- it never fabricates a date.

Two ways a row gets dated, in priority order:

1. ``git-anchor`` -- the row's ``source_path`` / ``source_anchor`` are mapped,
   via the row's SOURCE NAME (its own L1 file's basename) resolved through
   ``conf/source-roots.conf``, to a sibling repo root. The commit that FIRST
   introduced the anchor text into that file (``git log --reverse -S<anchor>``,
   first match) supplies the date. This is the precise measurement: it dates
   the moment the *lesson* entered the *source* repo.

2. ``l1-ingest-fallback`` -- when the anchor lookup can't resolve (root
   absent, path never existed, pickaxe empty), fall back to the first commit
   in THIS checkout that introduced the row's own id into its
   ``pipeline/L1/<source>.jsonl``. This only dates when the entry entered
   HINDSIGHT, which is later (sometimes much later) than when the underlying
   lesson was actually logged at its source -- hence the separate provenance
   tag, so a fallback date is never mistaken for the true first-seen moment.

Rows that already carry a non-null ``first_seen`` are left completely alone:
no rewrite, no provenance key added. Rows that resolve under neither path are
left with no ``first_seen`` and no provenance key -- STILL-UNDATED, never a
guess.

Usage:  python3 repair_first_seen.py [--l1 PATH] [--source-roots PATH]
                                      [--projects-dir PATH] [--self-dir PATH]
                                      [--hindsight-repo PATH] [--clusters PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SELF_ROOT_TOKEN = "SELF"
PROJECTS_ROOT_TOKEN = "."

# The two family sets this packet reports a fairness differential across.
# Membership is corpus-wide (pipeline/L2/clusters.jsonl), read-only.
ARM_B_CLUSTERS = {"c-043", "c-045", "c-063", "c-082", "c-104", "c-191"}
COMPARATOR_CLUSTERS = {
    "c-003", "c-004", "c-007", "c-008", "c-038", "c-044", "c-049", "c-051",
    "c-055", "c-058", "c-070", "c-085", "c-101", "c-117", "c-178",
}


@dataclass
class RepairStats:
    dated_by_anchor: int = 0
    dated_by_fallback: int = 0
    still_undated: int = 0


def parse_source_roots(text: str) -> dict[str, str]:
    """Parse a ``conf/source-roots.conf``-shaped mapping: ``source:relpath``.

    Blank lines and ``#`` comments are skipped. A malformed line, or an empty
    result, is a hard error -- a silently-empty map would make every source
    unverifiable and look identical to "the map was never written".
    """
    mapping: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"malformed source-roots line {line_number}: {raw_line!r}")
        source, _, relpath = line.partition(":")
        source = source.strip()
        relpath = relpath.strip()
        if not source or not relpath:
            raise ValueError(f"malformed source-roots line {line_number}: {raw_line!r}")
        mapping[source] = relpath
    if not mapping:
        raise ValueError("source-roots map is empty")
    return mapping


def _resolve_root(source: str, roots: dict[str, str], projects_dir: Path, self_dir: Path) -> Path | None:
    relpath = roots.get(source)
    if relpath is None:
        return None
    if relpath == SELF_ROOT_TOKEN:
        candidate = self_dir
    elif relpath == PROJECTS_ROOT_TOKEN:
        candidate = projects_dir
    else:
        candidate = projects_dir / relpath
    if not candidate.is_dir():
        return None
    return candidate


def _path_within_root(source_path: str, relpath: str | None) -> str:
    """Strip the leading path component that names the root itself.

    ``source_path`` is always recorded relative to ``projects_dir`` (e.g.
    ``"fleet/FAILURE-MODES.md"``, or ``"hindsight/catalog/failure-modes.md"``
    for the SELF-mapped source) -- one path segment further in than the
    resolved root. The one exception is the ``.`` root (projects_dir itself),
    where source_path is already root-relative and nothing is stripped.
    """
    if relpath == PROJECTS_ROOT_TOKEN:
        return source_path
    if "/" in source_path:
        return source_path.split("/", 1)[1]
    return source_path


def _first_git_date(root: Path, pathspec: str, needle: str) -> str | None:
    """First (oldest) commit's author date where *needle* was pickaxed into
    *pathspec* under *root* -- or ``None`` if the repo/path/match doesn't
    exist. Never raises: an unresolvable git query is a normal "no evidence"
    outcome here, not a tool error.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "--reverse", "--format=%aI", "-S", needle, "--", pathspec],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            return line.split("T", 1)[0]
    return None


def _anchor_date(root: Path, path_within_root: str, anchor: str) -> str | None:
    if not anchor or not path_within_root:
        return None
    return _first_git_date(root, path_within_root, anchor)


def _fallback_date(hindsight_repo: Path, source: str, row_id: str | None) -> str | None:
    if not row_id or not hindsight_repo.is_dir():
        return None
    rel = f"pipeline/L1/{source}.jsonl"
    return _first_git_date(hindsight_repo, rel, f'"{row_id}"')


def repair_file(
    path: Path,
    *,
    roots: dict[str, str],
    projects_dir: Path,
    self_dir: Path,
    hindsight_repo: Path,
) -> RepairStats:
    """Date every undated row in *path* in place. Fails loud (R4) on an
    absent or empty input -- a zero count must never look like "not measured".
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"L1 input not found: {path}")

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    non_empty = [(i, ln) for i, ln in enumerate(raw_lines) if ln.strip()]
    if not non_empty:
        raise ValueError(f"L1 input is empty: {path}")

    source = path.stem
    root = _resolve_root(source, roots, projects_dir, self_dir)
    relpath = roots.get(source)

    stats = RepairStats()
    out_lines = list(raw_lines)

    for i, raw in non_empty:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}:{i + 1}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"L1 record is not an object in {path}:{i + 1}")

        if row.get("first_seen") is not None:
            continue  # already dated -- left completely alone, not counted

        date = None
        source_path = row.get("source_path")
        anchor = row.get("source_anchor")
        if root is not None and isinstance(source_path, str) and source_path and isinstance(anchor, str):
            within = _path_within_root(source_path, relpath)
            date = _anchor_date(root, within, anchor)

        if date:
            row["first_seen"] = date
            row["first_seen_provenance"] = "git-anchor"
            stats.dated_by_anchor += 1
            out_lines[i] = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            continue

        fb = _fallback_date(hindsight_repo, source, row.get("id"))
        if fb:
            row["first_seen"] = fb
            row["first_seen_provenance"] = "l1-ingest-fallback"
            stats.dated_by_fallback += 1
            out_lines[i] = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            continue

        stats.still_undated += 1
        # left alone -- no first_seen, no provenance key, raw line unchanged

    path.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    return stats


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _print_differential(clusters_path: Path, l1_dir: Path) -> None:
    """Report the DATED% split between the Arm B intervention families and
    the comparator pool. Reporting only -- this packet does not fix the gap,
    it makes it visible so downstream normalisation can account for it.
    """
    try:
        clusters_text = clusters_path.read_text(encoding="utf-8")
    except OSError:
        print(
            f"date-repair: DIFFERENTIAL: unavailable (no clusters file at {clusters_path})",
            file=sys.stderr,
        )
        return

    arm_b_ids: set[str] = set()
    comparator_ids: set[str] = set()
    for line in clusters_text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        cid = rec.get("cluster_id")
        if cid is None:
            continue  # the _meta header row
        members = rec.get("members", [])
        if cid in ARM_B_CLUSTERS:
            arm_b_ids.update(members)
        if cid in COMPARATOR_CLUSTERS:
            comparator_ids.update(members)

    id_dated: dict[str, bool] = {}
    if l1_dir.is_dir():
        for jf in sorted(l1_dir.glob("*.jsonl")):
            for line in jf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rid = rec.get("id")
                if rid is None:
                    continue
                id_dated[rid] = rec.get("first_seen") is not None

    def pct(ids: set[str]) -> float | None:
        known = [id_dated[i] for i in ids if i in id_dated]
        if not known:
            return None
        return sum(known) / len(known) * 100

    p, q = pct(arm_b_ids), pct(comparator_ids)
    p_s = f"{p:.1f}%" if p is not None else "n/a"
    q_s = f"{q:.1f}%" if q is not None else "n/a"
    print(
        f"date-repair: DIFFERENTIAL: intervention-family dated {p_s}, comparator-pool dated {q_s}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--l1", type=Path, default=None,
                     help="L1 jsonl file, or a directory of them (default: pipeline/L1 under --self-dir)")
    ap.add_argument("--source-roots", type=Path, default=None)
    ap.add_argument("--projects-dir", type=Path, default=None)
    ap.add_argument("--self-dir", type=Path, default=None)
    ap.add_argument("--hindsight-repo", type=Path, default=None)
    ap.add_argument("--clusters", type=Path, default=None,
                     help="pipeline/L2/clusters.jsonl, for the DIFFERENTIAL report")
    args = ap.parse_args(argv)

    repo_root = _repo_root()
    self_dir = args.self_dir if args.self_dir is not None else repo_root
    hindsight_repo = args.hindsight_repo if args.hindsight_repo is not None else repo_root
    projects_dir = args.projects_dir if args.projects_dir is not None else (Path.home() / "projects")
    source_roots_path = args.source_roots if args.source_roots is not None else (repo_root / "conf" / "source-roots.conf")
    l1_target = args.l1 if args.l1 is not None else (self_dir / "pipeline" / "L1")
    clusters_path = args.clusters if args.clusters is not None else (hindsight_repo / "pipeline" / "L2" / "clusters.jsonl")

    try:
        roots_text = source_roots_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"date-repair: ERROR: cannot read source-roots map {source_roots_path}: {exc}", file=sys.stderr)
        return 1
    try:
        roots = parse_source_roots(roots_text)
    except ValueError as exc:
        print(f"date-repair: ERROR: {source_roots_path}: {exc}", file=sys.stderr)
        return 1

    if l1_target.is_dir():
        files = sorted(l1_target.glob("*.jsonl"))
        if not files:
            print(f"date-repair: ERROR: no .jsonl files found in {l1_target}", file=sys.stderr)
            return 1
        l1_dir_for_differential = l1_target
    else:
        files = [l1_target]
        l1_dir_for_differential = l1_target.parent

    total = RepairStats()
    had_error = False
    for f in files:
        try:
            stats = repair_file(f, roots=roots, projects_dir=projects_dir, self_dir=self_dir, hindsight_repo=hindsight_repo)
        except ValueError as exc:
            print(f"date-repair: ERROR: {exc}", file=sys.stderr)
            had_error = True
            continue
        total.dated_by_anchor += stats.dated_by_anchor
        total.dated_by_fallback += stats.dated_by_fallback
        total.still_undated += stats.still_undated

    print(f"date-repair: DATED-BY-ANCHOR: {total.dated_by_anchor}", file=sys.stderr)
    print(f"date-repair: DATED-BY-FALLBACK: {total.dated_by_fallback}", file=sys.stderr)
    print(f"date-repair: STILL-UNDATED: {total.still_undated}", file=sys.stderr)
    _print_differential(clusters_path, l1_dir_for_differential)

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
