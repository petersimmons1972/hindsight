#!/usr/bin/env python3
"""Repair missing ``first_seen`` dates on L1 corpus rows (Issue #32).

Rows are dated by the first source-repository commit containing their anchor
when that evidence is available. Otherwise, the tool falls back to the commit
that first ingested the row into Hindsight, preserving that distinction in
``first_seen_provenance``. Rows without either evidence path remain undated.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SELF_ROOT_TOKEN = "SELF"
PROJECTS_ROOT_TOKEN = "."

_PIPELINE_DIR = Path(__file__).resolve().parent
CORPUS_L1 = _PIPELINE_DIR / "L1"


def _repo_root() -> Path:
    return _PIPELINE_DIR.parent


@dataclass
class RepairStats:
    dated_by_anchor: int = 0
    dated_by_fallback: int = 0
    still_undated: int = 0


def parse_source_roots(text: str) -> dict[str, str]:
    """Parse a non-empty ``source:relative-root`` mapping."""
    mapping: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"malformed source-roots line {line_number}: {raw_line!r}")
        source, _, relpath = line.partition(":")
        source, relpath = source.strip(), relpath.strip()
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
    return candidate if candidate.is_dir() else None


def _path_within_root(source_path: str, relpath: str | None) -> str:
    """Convert a projects-root-relative source path to its repository path."""
    if relpath == PROJECTS_ROOT_TOKEN:
        return source_path
    return source_path.split("/", 1)[1] if "/" in source_path else source_path


def _first_git_date(root: Path, pathspec: str, needle: str) -> str | None:
    """Return the oldest pickaxe match date, or ``None`` when unavailable."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "--reverse", "--format=%aI", "-S", needle, "--", pathspec],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.strip():
            return line.strip().split("T", 1)[0]
    return None


def _anchor_date(root: Path, path_within_root: str, anchor: str) -> str | None:
    return _first_git_date(root, path_within_root, anchor) if anchor and path_within_root else None


def _fallback_date(hindsight_repo: Path, source: str, row_id: str | None) -> str | None:
    if not row_id or not hindsight_repo.is_dir():
        return None
    return _first_git_date(hindsight_repo, f"pipeline/L1/{source}.jsonl", f'"{row_id}"')


def repair_file(
    path: Path,
    *,
    roots: dict[str, str],
    projects_dir: Path,
    self_dir: Path,
    hindsight_repo: Path,
) -> RepairStats:
    """Date undated rows in ``path`` and fail loudly for invalid input."""
    stats, output = _compute_repair(
        path,
        roots=roots,
        projects_dir=projects_dir,
        self_dir=self_dir,
        hindsight_repo=hindsight_repo,
    )
    Path(path).write_text(output, encoding="utf-8")
    return stats


def _compute_repair(
    path: Path,
    *,
    roots: dict[str, str],
    projects_dir: Path,
    self_dir: Path,
    hindsight_repo: Path,
) -> tuple[RepairStats, str]:
    """Return a validated repair output without modifying ``path``."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"L1 input not found: {path}")
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    non_empty = [(index, line) for index, line in enumerate(raw_lines) if line.strip()]
    if not non_empty:
        raise ValueError(f"L1 input is empty: {path}")

    source = path.stem
    root = _resolve_root(source, roots, projects_dir, self_dir)
    relpath = roots.get(source)
    stats = RepairStats()
    out_lines = list(raw_lines)
    for index, raw in non_empty:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}:{index + 1}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"L1 record is not an object in {path}:{index + 1}")
        if row.get("first_seen") is not None:
            continue

        source_path, anchor = row.get("source_path"), row.get("source_anchor")
        date = None
        if root is not None and isinstance(source_path, str) and source_path and isinstance(anchor, str):
            date = _anchor_date(root, _path_within_root(source_path, relpath), anchor)
        if date:
            row["first_seen"] = date
            row["first_seen_provenance"] = "git-anchor"
            stats.dated_by_anchor += 1
        else:
            fallback = _fallback_date(hindsight_repo, source, row.get("id"))
            if fallback:
                row["first_seen"] = fallback
                row["first_seen_provenance"] = "l1-ingest-fallback"
                stats.dated_by_fallback += 1
            else:
                stats.still_undated += 1
                continue
        out_lines[index] = json.dumps(row, ensure_ascii=False, separators=(",", ":"))

    return stats, "\n".join(out_lines) + "\n"


def _replace_staged_outputs(outputs: list[tuple[Path, str]]) -> None:
    """Commit outputs with normal-failure compensation, not crash atomicity.

    Every original has a same-directory backup before replacement. Ordinary
    staging and replace errors are compensated, but a process crash between
    replacements cannot make the whole directory atomic.
    """
    staged_paths: list[Path] = []
    backup_paths: dict[Path, Path] = {}
    preserve_for_recovery: set[Path] = set()
    ordered_outputs = sorted(outputs, key=lambda item: str(item[0]))
    try:
        for path, output in ordered_outputs:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as temp:
                temp_path = Path(temp.name)
                # Register immediately: writes and metadata operations can fail.
                staged_paths.append(temp_path)
                temp.write(output)
                temp.flush()
                os.fsync(temp.fileno())
            os.chmod(temp_path, stat.S_IMODE(path.stat().st_mode))

        for path, _output in ordered_outputs:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.backup-",
                delete=False,
            ) as backup:
                backup_path = Path(backup.name)
                # Register immediately so a failed copy or chmod cannot leak it.
                backup_paths[path] = backup_path
                with path.open("rb") as original:
                    while chunk := original.read(1024 * 1024):
                        backup.write(chunk)
                backup.flush()
                os.fsync(backup.fileno())
            os.chmod(backup_path, stat.S_IMODE(path.stat().st_mode))

        replaced_paths: list[Path] = []
        try:
            for (path, _output), temp_path in zip(ordered_outputs, staged_paths):
                os.replace(temp_path, path)
                replaced_paths.append(path)
        except OSError as primary_error:
            rollback_errors: list[tuple[Path, OSError]] = []
            for path in reversed(replaced_paths):
                try:
                    os.replace(backup_paths[path], path)
                except OSError as rollback_error:
                    preserve_for_recovery.add(backup_paths[path])
                    rollback_errors.append((path, rollback_error))
            if rollback_errors:
                rollback_detail = "; ".join(
                    f"{path}: {error}" for path, error in rollback_errors
                )
                raise OSError(
                    f"replacement failed: {primary_error}; rollback failed: {rollback_detail}"
                ) from primary_error
            raise
    finally:
        for temporary_path in staged_paths:
            temporary_path.unlink(missing_ok=True)
        for backup_path in backup_paths.values():
            if backup_path not in preserve_for_recovery:
                backup_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--l1", type=Path, default=None, help="L1 jsonl file or directory to repair.")
    ap.add_argument("--source-roots", type=Path, default=None)
    ap.add_argument("--projects-dir", type=Path, default=None)
    ap.add_argument("--self-dir", type=Path, default=None)
    ap.add_argument("--hindsight-repo", type=Path, default=None)
    args = ap.parse_args(argv)

    repo_root = _repo_root()
    self_dir = args.self_dir or repo_root
    hindsight_repo = args.hindsight_repo or repo_root
    projects_dir = args.projects_dir or (Path.home() / "projects")
    source_roots_path = args.source_roots or (repo_root / "conf" / "source-roots.conf")
    l1_target = args.l1 or CORPUS_L1
    try:
        roots = parse_source_roots(source_roots_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"date-repair: ERROR: cannot read source-roots map {source_roots_path}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"date-repair: ERROR: {source_roots_path}: {exc}", file=sys.stderr)
        return 1

    files = sorted(l1_target.glob("*.jsonl")) if l1_target.is_dir() else [l1_target]
    if l1_target.is_dir() and not files:
        print(f"date-repair: ERROR: no .jsonl files found in {l1_target}", file=sys.stderr)
        return 1
    computations: list[tuple[Path, RepairStats, str]] = []
    for file in files:
        try:
            stats, output = _compute_repair(
                file,
                roots=roots,
                projects_dir=projects_dir,
                self_dir=self_dir,
                hindsight_repo=hindsight_repo,
            )
        except (OSError, ValueError) as exc:
            print(f"date-repair: ERROR: {exc}", file=sys.stderr)
            print("date-repair: NOT MEASURED", file=sys.stderr)
            return 1
        computations.append((file, stats, output))
    if l1_target.is_dir():
        try:
            _replace_staged_outputs([(file, output) for file, _stats, output in computations])
        except OSError as exc:
            print(f"date-repair: ERROR: cannot replace staged output: {exc}", file=sys.stderr)
            print("date-repair: NOT MEASURED", file=sys.stderr)
            return 1
    else:
        file, _stats, output = computations[0]
        try:
            file.write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"date-repair: ERROR: cannot write repaired output: {exc}", file=sys.stderr)
            print("date-repair: NOT MEASURED", file=sys.stderr)
            return 1

    total = RepairStats()
    for _file, stats, _output in computations:
        total.dated_by_anchor += stats.dated_by_anchor
        total.dated_by_fallback += stats.dated_by_fallback
        total.still_undated += stats.still_undated
    print(f"date-repair: DATED-BY-ANCHOR: {total.dated_by_anchor}", file=sys.stderr)
    print(f"date-repair: DATED-BY-FALLBACK: {total.dated_by_fallback}", file=sys.stderr)
    print(f"date-repair: STILL-UNDATED: {total.still_undated}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
