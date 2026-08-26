#!/usr/bin/env python3
"""validate_l3.py -- gate for pipeline/L3/invariants.jsonl (plan-06, hindsight#21).

Every row in the L3 ledger must resolve to exactly one of two states,
`machine` or `judgment`. "Documented" is not a third state. Row schema and
validation rules are pinned by the founder-authorized ground truth fixture at
pipeline/tests/fixtures/l3_ground_truth.jsonl (PR #63, co-authored by the
founder) -- this validator conforms to that fixture, not the other way
around. See plans/06-l3-invariant-ledger.md D1-D6 for the full contract:

  D1  kind is exactly "machine" or "judgment" -- nothing else.
  D2  --assert-paths-exist: a machine row's enforcement.path must exist
      under --repo-root, when enforcement.repo names the locally-checked-out
      repo (LOCAL_REPO_NAME below). A machine row naming a different repo's
      path is unverifiable from here and is treated as a failure under
      --assert-paths-exist, same reasoning as a missing path: an unverifiable
      "machine" claim reads as covered without being checked.
  D3  a row's source_repos, deduplicated (blank-stripped), must have >=2
      distinct non-blank entries. Duplicate-only repos ("repo-a","repo-a")
      do not clear the bar. source_repos must structurally be a JSON array
      of strings -- a bare string (iterates char-by-char), a dict (iterates
      its keys), or a list with a non-string member is rejected outright
      with a named D3 error, not silently accepted as "iterable with >=2
      distinct members" and not left to crash as an uncaught TypeError.
  D4  a judgment row must carry a non-empty (non-whitespace) procedural
      substitute.
  --  every row's `invariant` field (docs/L3.md schema) must be a non-empty,
      non-whitespace string. An "invariant ledger" that never inspects
      `invariant` grades hollow rows green; this is schema enforcement, not
      a new D-numbered gate in plan-06.
  D5  a missing, empty, or unparseable --clusters file is fail-loud: exit 1
      unconditionally, even against an empty ledger. `--clusters /dev/null`
      exits 1. (This is a corpus-integrity precondition, independent of any
      single row's own embedded provenance -- see docs/L3.md.)
  D6  this script never writes anything; it only reads and reports.

Exit 0 only when every ledger row clears D1-D4 and the invariant-field
schema check above. Exit 1 on any violation, or
on a missing/empty/unparseable --clusters file.
"""
import argparse
import json
import os
import sys

# The only repo this checkout can verify a "machine" enforcement path against.
LOCAL_REPO_NAME = "hindsight"


def clusters_file_is_usable(path):
    """D5: --clusters must exist and contain at least one parseable, non-meta row."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if i == 0 and isinstance(row, dict) and "_meta" in row:
                    continue
                return True  # found at least one real row
    except (OSError, json.JSONDecodeError):
        return False
    return False


def load_ledger(path):
    """Return a list of (line_no, row_dict_or_None, raw_line), or None if the file is absent."""
    if not path or not os.path.isfile(path):
        return None
    rows = []
    with open(path) as f:
        for i, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                rows.append((i, json.loads(raw), raw))
            except json.JSONDecodeError:
                rows.append((i, None, raw))
    return rows


def check_row(row, assert_paths_exist, repo_root):
    """Return a list of violation strings for one ledger row (empty list == valid)."""
    errors = []
    kind = row.get("kind")

    # D1 -- exactly machine or judgment, nothing else.
    if kind not in ("machine", "judgment"):
        errors.append(f"kind={kind!r} is neither 'machine' nor 'judgment' (D1)")
        return errors  # nothing else about this row can be graded meaningfully

    # invariant -- every row (docs/L3.md schema) must state a non-empty
    # generalized claim. Checked before D3 so a row missing both fields
    # reports both violations rather than short-circuiting.
    invariant = row.get("invariant")
    if not isinstance(invariant, str) or not invariant.strip():
        errors.append(
            f"invariant={invariant!r} is empty/blank -- a ledger row must "
            "state its generalized claim in the 'invariant' field; an "
            "unenforceable finding with no invariant text is not a ledger "
            "row (schema, docs/L3.md)"
        )

    # D3 -- >=2 distinct source repos, deduplicated. source_repos must be a
    # JSON array of strings; anything else fails structurally rather than
    # degrading into a truthy/iterable check (a string iterates character by
    # character; a dict iterates its keys) or an uncaught TypeError.
    source_repos = row.get("source_repos")
    if source_repos is None:
        source_repos = []
    if not isinstance(source_repos, list) or not all(isinstance(r, str) for r in source_repos):
        errors.append(
            f"source_repos={source_repos!r} must be a JSON array of repo-name "
            "strings, not a bare string/dict/other type or a list containing "
            "a non-string member (D3)"
        )
    else:
        distinct = {r.strip() for r in source_repos if r.strip()}
        if len(distinct) < 2:
            errors.append(
                f"source_repos={source_repos!r} has only {len(distinct)} distinct "
                "non-blank repo(s) -- single-repo provenance does not clear the L3 bar (D3)"
            )

    if kind == "machine":
        enforcement = row.get("enforcement")
        candidate = enforcement.get("path") if isinstance(enforcement, dict) else None
        if (
            not isinstance(enforcement, dict)
            or not isinstance(candidate, str)
            or not candidate.strip()
        ):
            errors.append(
                "kind=machine but enforcement is not a {repo, path} object with "
                "a non-blank string path (D2)"
            )
        elif assert_paths_exist:
            repo = enforcement.get("repo")
            if repo != LOCAL_REPO_NAME:
                errors.append(
                    f"enforcement.path {candidate!r} is claimed against repo "
                    f"{repo!r}, which this checkout cannot verify (only "
                    f"{LOCAL_REPO_NAME!r} is locally checked out) -- an "
                    "unverifiable machine claim reads as covered without "
                    "being checked (D2)"
                )
            else:
                full_path = candidate if os.path.isabs(candidate) else os.path.join(repo_root, candidate)
                if not os.path.exists(full_path):
                    errors.append(
                        f"enforcement.path {candidate!r} does not exist under "
                        f"repo root {repo_root!r} (D2 -- a fabricated mechanism "
                        "is worse than an honest gap)"
                    )
    else:  # judgment
        substitute = row.get("procedural_substitute")
        if not isinstance(substitute, str) or not substitute.strip():
            errors.append(
                "kind=judgment but procedural_substitute is empty (D4 -- "
                "unenforceable and offering nothing in its place is not a "
                "finding, it is a shrug)"
            )

    return errors


def validate(ledger_path, clusters_path, assert_paths_exist, repo_root):
    if not clusters_file_is_usable(clusters_path):
        print(
            f"FAIL: --clusters '{clusters_path}' is missing, empty, or unparseable. "
            "D5: this is a fail-loud condition, never a vacuous pass.",
            file=sys.stderr,
        )
        return 1

    ledger = load_ledger(ledger_path)
    if ledger is None:
        print(f"FAIL: --ledger '{ledger_path}' does not exist.", file=sys.stderr)
        return 1

    all_errors = []
    machine_count = 0
    judgment_count = 0

    for line_no, row, raw in ledger:
        if row is None:
            all_errors.append(f"line {line_no}: not valid JSON: {raw!r}")
            continue
        if not isinstance(row, dict):
            # A line can parse as valid JSON without being a JSON object --
            # a bare list, string, or number. Reject it structurally here,
            # before any .get() call, rather than let it reach check_row and
            # crash with an uncaught AttributeError.
            all_errors.append(f"line {line_no}: row is not a JSON object: {raw!r}")
            continue
        row_id = row.get("id") or row.get("case") or f"<line {line_no}>"
        row_errors = check_row(row, assert_paths_exist, repo_root)
        if row_errors:
            for e in row_errors:
                all_errors.append(f"{row_id}: {e}")
            continue
        if row.get("kind") == "machine":
            machine_count += 1
        else:
            judgment_count += 1

    if all_errors:
        print(f"FAIL: {len(all_errors)} violation(s) in '{ledger_path}':", file=sys.stderr)
        for e in all_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(
        f"OK: {len(ledger)} row(s) validated ({machine_count} machine, "
        f"{judgment_count} judgment); --clusters '{clusters_path}' present."
    )
    return 0


def main():
    default_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", default=os.path.join(default_repo_root, "pipeline", "L3", "invariants.jsonl"))
    parser.add_argument("--clusters", default=os.path.join(default_repo_root, "pipeline", "L2", "clusters.jsonl"))
    parser.add_argument("--assert-paths-exist", action="store_true")
    parser.add_argument("--repo-root", default=default_repo_root)
    args = parser.parse_args()
    return validate(args.ledger, args.clusters, args.assert_paths_exist, args.repo_root)


if __name__ == "__main__":
    sys.exit(main())
