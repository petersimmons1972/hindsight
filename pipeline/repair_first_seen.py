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

The corpus statistics (DIFFERENTIAL / WARNING) are UNPOINTABLE: they read
exactly two module constants derived from this file's own location --
``CORPUS_L1`` and ``CORPUS_CLUSTERS`` -- and nothing else. No CLI flag or
function argument can make them read any other directory or file. ``--l1``
may retarget the REPAIR (dating rows in some other file, e.g. for a test
fixture); it has no influence whatsoever on the statistics. If the repair
target isn't ``CORPUS_L1``, both statistic lines print NOT MEASURED naming
that as the reason.

Usage:  python3 repair_first_seen.py [--l1 PATH] [--source-roots PATH]
                                      [--projects-dir PATH] [--self-dir PATH]
                                      [--hindsight-repo PATH]
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

# This file's own directory -- the ONE anchor the statistics are allowed to
# read from. Derived from __file__, never from an argument: there is no CLI
# flag, no function parameter, no environment variable that can move it.
_PIPELINE_DIR = Path(__file__).resolve().parent

# The real corpus location and the real cluster-membership file. Every
# statistic (DIFFERENTIAL, WARNING) reads these two constants and nothing
# else. ``--l1`` can still retarget the REPAIR -- that's what makes repair
# testable against a scratch fixture -- but it can never make a statistic
# read anywhere but here (see _measure_corpus).
CORPUS_L1 = _PIPELINE_DIR / "L1"
CORPUS_CLUSTERS = _PIPELINE_DIR / "L2" / "clusters.jsonl"


def _repo_root() -> Path:
    return _PIPELINE_DIR.parent


# The two family sets this packet reports a fairness differential across.
# Fixed here as MODULE CONSTANTS, never read from an argument or inferred
# from whatever a clusters file happens to contain -- an argument-supplied
# or partial family list is exactly how a scratch/stripped clusters file
# used to get treated as authoritative (instances #1 and #6 of the
# fabricated-statistic defect; see _resolve_measurement).
ARM_B_FAMILIES = {"c-043", "c-045", "c-063", "c-082", "c-104", "c-191"}
COMPARATOR_FAMILIES = {
    "c-003", "c-004", "c-007", "c-008", "c-038", "c-044", "c-049", "c-051",
    "c-055", "c-058", "c-070", "c-085", "c-101", "c-117", "c-178",
}
EXPECTED_FAMILIES = ARM_B_FAMILIES | COMPARATOR_FAMILIES  # 21 families total

# The real corpus's ground-truth member counts. ENFORCED (instance #8: a
# clusters.jsonl silently stripped of 2 of c-104's members shrank the
# denominator from 32 to 30 and printed a fabricated 53.3% -- nothing checked
# that the resolved membership actually matched the known-good count). Any
# other resolved count on either arm is a hard NOT MEASURED naming the actual
# counts, never a silent recompute of the percentage over whatever survived.
EXPECTED_ARM_B_MEMBERS = 32
EXPECTED_COMPARATOR_MEMBERS = 102
EXPECTED_MEMBERS = EXPECTED_ARM_B_MEMBERS + EXPECTED_COMPARATOR_MEMBERS  # 134


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


@dataclass
class CorpusMeasurement:
    """The ONE trust gate. Every statistic print path -- the differential,
    the fallback WARNING -- consults this and only this. ``measured`` is
    True only when the corpus's IDENTITY has been established: this run's
    target really is CORPUS_L1, every expected family is present in
    CORPUS_CLUSTERS, each arm's resolved membership matches the known-good
    count, and every declared member was actually loaded. When any of that
    fails, ``reason`` names the shortfall and every statistic path prints
    NOT MEASURED with it -- never a number, never a silent skip.

    ``id_provenance`` covers EVERY row loaded from the corpus (not just
    cluster members), so it backs both the per-family differential and the
    corpus-wide fallback-share warning from a single read of disk.
    """

    measured: bool
    reason: str | None = None
    id_provenance: dict[str, str] | None = None
    arm_b_ids: frozenset[str] | None = None
    comparator_ids: frozenset[str] | None = None


def _parse_cluster_families(clusters_text: str) -> dict[str, set[str]]:
    """PURE: parse clusters.jsonl TEXT into cluster_id -> members, restricted
    to this module's known family ids. No IO, no path argument."""
    found: dict[str, set[str]] = {}
    for line in clusters_text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        cid = rec.get("cluster_id")
        if cid is None:
            continue  # the _meta header row
        if cid in EXPECTED_FAMILIES:
            found[cid] = set(rec.get("members", []))
    return found


def _parse_id_provenance(records: list[dict]) -> dict[str, str]:
    """PURE: turn already-parsed L1 row dicts into id -> provenance. No IO,
    no path argument."""
    id_provenance: dict[str, str] = {}
    for rec in records:
        rid = rec.get("id")
        if rid is None:
            continue
        prov = rec.get("first_seen_provenance")
        if prov == "git-anchor":
            id_provenance[rid] = "git-anchor"
        elif prov == "l1-ingest-fallback":
            id_provenance[rid] = "l1-ingest-fallback"
        elif rec.get("first_seen") is not None:
            id_provenance[rid] = "pre-existing"
        else:
            id_provenance[rid] = "undated"
    return id_provenance


def _resolve_measurement(found_families: dict[str, set[str]], id_provenance: dict[str, str]) -> CorpusMeasurement:
    """PURE: every check after "the clusters text is parsed and the corpus
    rows are loaded" -- family presence, the EXPECTED_ARM_B_MEMBERS /
    EXPECTED_COMPARATOR_MEMBERS equality, and unresolved-member detection.
    Takes only already-loaded data (dicts), does no IO, and accepts no path.

    Checked in order, first failure wins:
      1. the clusters data declares every module-constant family -- a file
         stripped of a family must not resolve vacuously over the rest;
      2. each arm's resolved membership count matches the known-good total
         -- a family quietly stripped of members (not the whole family, just
         some of its members) must not silently shrink the denominator;
      3. every member of every declared family was actually loaded from a
         corpus row -- an id absent from every row never resolved.
    """
    missing_families = EXPECTED_FAMILIES - found_families.keys()
    if missing_families:
        return CorpusMeasurement(
            False,
            f"clusters file missing {len(missing_families)} of {len(EXPECTED_FAMILIES)} "
            f"expected families: {', '.join(sorted(missing_families))}",
        )

    arm_b_ids: set[str] = set().union(*(found_families[c] for c in ARM_B_FAMILIES))
    comparator_ids: set[str] = set().union(*(found_families[c] for c in COMPARATOR_FAMILIES))

    if len(arm_b_ids) != EXPECTED_ARM_B_MEMBERS or len(comparator_ids) != EXPECTED_COMPARATOR_MEMBERS:
        return CorpusMeasurement(
            False,
            f"cluster membership resolved to {len(arm_b_ids)} arm-b members "
            f"(expected {EXPECTED_ARM_B_MEMBERS}) and {len(comparator_ids)} comparator members "
            f"(expected {EXPECTED_COMPARATOR_MEMBERS})",
        )

    expected_ids = arm_b_ids | comparator_ids
    unresolved_ids = expected_ids - id_provenance.keys()
    if unresolved_ids:
        return CorpusMeasurement(
            False,
            f"{len(unresolved_ids)} of {len(expected_ids)} cluster members did not resolve",
        )

    return CorpusMeasurement(
        True,
        id_provenance=id_provenance,
        arm_b_ids=frozenset(arm_b_ids),
        comparator_ids=frozenset(comparator_ids),
    )


def _read_corpus_records() -> list[dict]:
    """The ONE disk read of the real corpus: every row from every
    CORPUS_L1/*.jsonl file. Reads the module constant only -- takes no
    argument, so there is nothing to point elsewhere."""
    records: list[dict] = []
    for jf in sorted(CORPUS_L1.glob("*.jsonl")):
        for line in jf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict):
                records.append(rec)
    return records


def _measure_corpus(l1_target: Path) -> CorpusMeasurement:
    """Establish corpus identity ONCE, before any statistic is computed.
    IO orchestration only -- both reads are of the module constants
    (CORPUS_L1, CORPUS_CLUSTERS), never of an argument; all computation is
    delegated to the pure _resolve_measurement.

    ``l1_target`` is used for exactly one comparison: is this run's actual
    repair target CORPUS_L1 itself? Nothing derived from ``l1_target`` is
    ever used as a read location -- there is structurally no way for a
    ``--l1`` override to redirect what gets measured, only whether it
    matches (in which case it's measured) or doesn't (NOT MEASURED).
    """
    if not CORPUS_L1.is_dir():
        return CorpusMeasurement(False, f"no corpus directory at {CORPUS_L1}")

    if l1_target.resolve() != CORPUS_L1.resolve():
        return CorpusMeasurement(False, "target is not the corpus")

    try:
        clusters_text = CORPUS_CLUSTERS.read_text(encoding="utf-8")
    except OSError:
        return CorpusMeasurement(False, f"no clusters file at {CORPUS_CLUSTERS}")

    found_families = _parse_cluster_families(clusters_text)
    id_provenance = _parse_id_provenance(_read_corpus_records())
    return _resolve_measurement(found_families, id_provenance)


def _summarize_family(ids: frozenset[str], id_provenance: dict[str, str]) -> tuple[int, int, int, int]:
    """PURE: (pre-existing, git-anchor, l1-ingest-fallback, undated) counts
    for *ids* against an already-loaded provenance map."""
    pre = anchor = fallback = undated = 0
    for i in ids:
        p = id_provenance.get(i)
        if p == "pre-existing":
            pre += 1
        elif p == "git-anchor":
            anchor += 1
        elif p == "l1-ingest-fallback":
            fallback += 1
        elif p == "undated":
            undated += 1
    return pre, anchor, fallback, undated


def _pct_pre_dated(pre: int, anchor: int, fallback: int) -> str:
    """PURE."""
    total = pre + anchor + fallback
    if total == 0:
        return "n/a"
    return f"{pre / total * 100:.1f}%"


def _fallback_share(id_provenance: dict[str, str]) -> tuple[int, int]:
    """PURE: (fallback count, dated count) across every row in an
    already-loaded provenance map."""
    anchor = sum(1 for p in id_provenance.values() if p == "git-anchor")
    fallback = sum(1 for p in id_provenance.values() if p == "l1-ingest-fallback")
    return fallback, anchor + fallback


def _print_differential(measurement: CorpusMeasurement) -> None:
    """Report the PROVENANCE-QUALITY split between the Arm B intervention
    families and the comparator pool. Reporting only -- this packet does not
    fix the gap, it makes it visible so downstream normalisation can account
    for it.

    Measures pre-existing / git-anchor / l1-ingest-fallback shares, not mere
    "first_seen is not None": that flag goes to 100% once repair finishes
    and can never again surface the bias it exists to surface.
    """
    if not measurement.measured:
        print(f"date-repair: DIFFERENTIAL: NOT MEASURED ({measurement.reason})", file=sys.stderr)
        return

    for label, ids in (
        ("intervention-family", measurement.arm_b_ids),
        ("comparator-pool", measurement.comparator_ids),
    ):
        pre, anchor, fallback, undated = _summarize_family(ids, measurement.id_provenance)
        print(
            f"date-repair: DIFFERENTIAL: {label} (n={len(ids)}) "
            f"pre-existing={pre} git-anchor={anchor} l1-ingest-fallback={fallback} "
            f"undated={undated} -> {_pct_pre_dated(pre, anchor, fallback)} pre-dated",
            file=sys.stderr,
        )


def _print_fallback_warning(measurement: CorpusMeasurement) -> None:
    """~90% of the real corpus's dated rows fell back to when the row
    entered HINDSIGHT rather than a recovered logging date -- that is an
    honest outcome of ruling R-c, not a defect, but it must be stated loudly
    wherever these dates get consumed.

    Measured from CORPUS PROVENANCE -- every first_seen_provenance tag
    already sitting on disk, off the SAME id_provenance the differential
    used -- never from this run's own deltas: repair is idempotent, so a
    deltas-gated warning fires on the one run that does the dating and then
    goes permanently silent for every steady-state run after, even though
    the corpus stays just as fallback-heavy.

    Consults the SAME gate as the differential. Silence is legitimate only
    when the corpus was actually measured and genuinely has nothing to warn
    about (no dated rows, or a healthy anchor share) -- never as a stand-in
    for "the corpus's identity was never established."
    """
    if not measurement.measured:
        print(f"date-repair: WARNING: NOT MEASURED ({measurement.reason})", file=sys.stderr)
        return

    fallback, dated = _fallback_share(measurement.id_provenance)
    if dated == 0:
        return
    fallback_share = fallback / dated
    if fallback_share > 0.5:
        print(
            f"date-repair: WARNING: {fallback_share * 100:.1f}% of the corpus's dated rows "
            "used l1-ingest-fallback (entered HINDSIGHT, not the true logging date)",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--l1", type=Path, default=None,
                     help="L1 jsonl file, or a directory of them, to REPAIR (default: CORPUS_L1, "
                          "this repo's own pipeline/L1). Retargeting this only changes what gets "
                          "dated -- the DIFFERENTIAL/WARNING statistics always read CORPUS_L1 and "
                          "CORPUS_CLUSTERS regardless, and print NOT MEASURED whenever this doesn't "
                          "resolve to CORPUS_L1 itself.")
    ap.add_argument("--source-roots", type=Path, default=None)
    ap.add_argument("--projects-dir", type=Path, default=None)
    ap.add_argument("--self-dir", type=Path, default=None,
                     help="Root used to resolve the SELF-mapped source-roots token during REPAIR "
                          "only; has no effect on the statistics.")
    ap.add_argument("--hindsight-repo", type=Path, default=None)
    args = ap.parse_args(argv)

    repo_root = _repo_root()
    self_dir = args.self_dir if args.self_dir is not None else repo_root
    hindsight_repo = args.hindsight_repo if args.hindsight_repo is not None else repo_root
    projects_dir = args.projects_dir if args.projects_dir is not None else (Path.home() / "projects")
    source_roots_path = args.source_roots if args.source_roots is not None else (repo_root / "conf" / "source-roots.conf")
    l1_target = args.l1 if args.l1 is not None else CORPUS_L1

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
    else:
        files = [l1_target]

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

    if had_error:
        # D-2 / R4: a fail-loud path must never print counts, not even
        # zeros -- a zero is indistinguishable from a genuine all-zero run.
        print("date-repair: NOT MEASURED", file=sys.stderr)
    else:
        print(f"date-repair: DATED-BY-ANCHOR: {total.dated_by_anchor}", file=sys.stderr)
        print(f"date-repair: DATED-BY-FALLBACK: {total.dated_by_fallback}", file=sys.stderr)
        print(f"date-repair: STILL-UNDATED: {total.still_undated}", file=sys.stderr)

    # ONE gate, established once, consulted by every statistic path below --
    # reached on EVERY exit, error or success alike, so the DIFFERENTIAL and
    # WARNING lines are never silently skipped (instance #5: a fail-loud
    # return used to happen before either line printed at all).
    measurement = _measure_corpus(l1_target)
    _print_differential(measurement)
    _print_fallback_warning(measurement)

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
