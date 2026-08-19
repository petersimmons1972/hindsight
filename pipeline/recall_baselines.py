#!/usr/bin/env python3
"""Per-(family, backend) recall baselines — a ratchet, not an absolute floor.

Founder ruling 2026-08-19 (hindsight#121). The ground-truth fixture asserted an
absolute recall floor of 0.75 for every family on every backend. That floor is a
*target*, and the corpus outgrew it: `shared-mutable-checkout` fell below 0.75
on both backends purely through corpus growth (673 -> 678 entries), with no code
change involved. An absolute floor in that situation offers two bad options —
weaken the number by hand every time it goes red, or hold the whole release
hostage to a research problem.

The ruling replaces it with a recorded-baseline ratchet:

  * the sanctioned release path records the CURRENT per-(family, backend) recall
    into `pipeline/L2/recall-baselines.json`, a committed, reviewable artifact;
  * a release that would drop ANY family below its recorded baseline FAILS
    LOUDLY and writes nothing;
  * accepting a lower baseline is possible, but only through an explicit
    `--allow-drop --reason "..."` override whose reason string is recorded in
    the artifact's `overrides` log, so every regression that was accepted is
    visible in the file and in `git log` forever.

So the number can still move down — but never silently, and never without a
named human reason attached to it. 0.75 remains the aspirational target
(`target_fraction` below, and the fixture's `min_fraction_together`); it is no
longer the gate.

hindsight#121 stays OPEN tracking the underlying degradation. This module makes
the degradation visible and non-worsening; it does not fix it.

Modes:
  (default)              verify the committed artifact against measured recall
  --update               re-measure and rewrite the artifact (release path)
  --allow-drop --reason  permit a measured drop below a recorded baseline
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = REPO / "pipeline" / "L2" / "recall-baselines.json"
DEFAULT_FIXTURE = REPO / "pipeline" / "tests" / "fixtures" / "recurrence_ground_truth.json"
DEFAULT_CLUSTERS = REPO / "pipeline" / "L2" / "clusters.jsonl"
DEFAULT_L1 = REPO / "pipeline" / "L1"
CLUSTER_CODE = REPO / "pipeline" / "cluster.py"

SCHEMA = "hindsight.recall-baselines/v1"
# Aspirational only. Referenced in messages so a reader of a failure knows how
# far the ratchet currently sits from where it is supposed to end up.
TARGET_FRACTION = 0.75

# "released" is the committed pipeline/L2/clusters.jsonl partition -- what
# downstream consumers (pipeline/recurrence_report.py) actually read. "tfidf"
# and "http" are live re-clusterings, measured only when asked for.
RELEASED = "released"


def _load_cluster_module():
    spec = importlib.util.spec_from_file_location("hindsight_recall_cluster", CLUSTER_CODE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_families(fixture: Path = DEFAULT_FIXTURE) -> dict[str, list[str]]:
    data = json.loads(fixture.read_text(encoding="utf-8"))
    return {family["key"]: list(family["members"]) for family in data["families"]}


def recall_from_assignments(
    assignments: dict[str, str], families: dict[str, list[str]]
) -> dict[str, dict[str, object]]:
    """Largest single cluster holding members of each family, as a fraction.

    A member absent from the partition entirely counts against the family: it is
    assigned a unique sentinel so it can never coincide with another member.
    """
    measured: dict[str, dict[str, object]] = {}
    for family, members in families.items():
        assigned = [assignments.get(member, f"__missing__{member}") for member in members]
        largest = max(assigned.count(cluster_id) for cluster_id in set(assigned))
        measured[family] = {
            "together": largest,
            "members": len(members),
            "fraction": round(largest / len(members), 6),
        }
    return measured


def released_assignments(clusters_path: Path = DEFAULT_CLUSTERS) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line in clusters_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if "_meta" in record:
            continue
        for member in record["members"]:
            assignments[member] = record["cluster_id"]
    return assignments


def _live_assignments(backend_name: str) -> dict[str, str] | None:
    cl = _load_cluster_module()
    entries = cl.load_entries(DEFAULT_L1)
    if backend_name == "tfidf":
        backend = cl.TfidfEmbeddingBackend()
    elif backend_name == "http":
        backend = cl.HttpEmbeddingBackend()
        if not backend.available:
            return None
    else:  # pragma: no cover - guarded by argparse choices
        raise ValueError(f"unknown backend: {backend_name}")
    clusters = cl.cluster_entries_from_backend(entries, backend)
    return {member: cluster.cluster_id for cluster in clusters for member in cluster.members}


def measure(backends: list[str], fixture: Path = DEFAULT_FIXTURE,
            clusters_path: Path = DEFAULT_CLUSTERS) -> dict[str, dict[str, dict[str, object]]]:
    families = load_families(fixture)
    measured: dict[str, dict[str, dict[str, object]]] = {}
    for backend_name in backends:
        if backend_name == RELEASED:
            assignments = released_assignments(clusters_path)
        else:
            assignments = _live_assignments(backend_name)
            if assignments is None:
                continue
        measured[backend_name] = recall_from_assignments(assignments, families)
    return measured


def load_artifact(path: Path = DEFAULT_ARTIFACT) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_drops(
    recorded: dict[str, object], measured: dict[str, dict[str, dict[str, object]]]
) -> list[tuple[str, str, float, float]]:
    """(backend, family, recorded_fraction, measured_fraction) for every drop.

    A backend or family that is measured but has no recorded baseline is NOT a
    drop -- it is a new row, recorded on the next `--update`. A recorded row
    that was not measured this run is not a drop either (it was not observed);
    it is left untouched rather than silently reset, so an unreachable HTTP
    backend can never launder a regression by simply not being measured.
    """
    drops: list[tuple[str, str, float, float]] = []
    baselines = recorded.get("baselines", {})
    for backend_name, families in measured.items():
        recorded_backend = baselines.get(backend_name)
        if not recorded_backend:
            continue
        for family, stats in families.items():
            recorded_family = recorded_backend.get(family)
            if recorded_family is None:
                continue
            was = float(recorded_family["fraction"])
            now = float(stats["fraction"])
            if now < was:
                drops.append((backend_name, family, was, now))
    return sorted(drops)


def _merge_baselines(
    recorded: dict[str, object], measured: dict[str, dict[str, dict[str, object]]]
) -> dict[str, dict[str, dict[str, object]]]:
    merged = {
        backend: dict(families)
        for backend, families in dict(recorded.get("baselines", {})).items()
    }
    for backend_name, families in measured.items():
        merged.setdefault(backend_name, {})
        merged[backend_name].update(families)
    return merged


def _render_drops(drops: list[tuple[str, str, float, float]]) -> str:
    lines = [
        "recall-baselines: REFUSED: measured recall dropped below a recorded baseline.",
        "",
    ]
    for backend_name, family, was, now in drops:
        lines.append(
            f"  {backend_name}/{family}: {was:.4f} -> {now:.4f}"
            f"  (target {TARGET_FRACTION:.2f})"
        )
    lines += [
        "",
        "Nothing was written. A drop is a real capability regression until proven",
        "otherwise -- investigate first (hindsight#121 tracks the known one).",
        "To accept it deliberately, re-run with:",
        "  --update --allow-drop --reason \"why this drop is acceptable\"",
        "The reason is recorded in the artifact's overrides log and in git history.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record and enforce per-(family, backend) recall baselines."
    )
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--clusters", type=Path, default=DEFAULT_CLUSTERS)
    parser.add_argument(
        "--backend", action="append", dest="backends",
        choices=[RELEASED, "tfidf", "http"],
        help="repeatable; defaults to released+tfidf+http",
    )
    parser.add_argument("--update", action="store_true",
                        help="re-measure and rewrite the artifact (release path)")
    parser.add_argument("--allow-drop", action="store_true",
                        help="permit a measured drop below a recorded baseline")
    parser.add_argument("--reason", default=None,
                        help="required with --allow-drop; recorded in the artifact")
    args = parser.parse_args(argv)

    if args.allow_drop and not (args.reason or "").strip():
        print("recall-baselines: error: --allow-drop requires a non-empty --reason",
              file=sys.stderr)
        return 2
    if args.allow_drop and not args.update:
        print("recall-baselines: error: --allow-drop is only meaningful with --update",
              file=sys.stderr)
        return 2

    backends = args.backends or [RELEASED, "tfidf", "http"]
    measured = measure(backends, fixture=args.fixture, clusters_path=args.clusters)

    if args.artifact.exists():
        recorded = load_artifact(args.artifact)
    elif args.update:
        recorded = {"baselines": {}, "overrides": []}
    else:
        print(f"recall-baselines: error: no baseline artifact at {args.artifact}; "
              f"run with --update to record the initial baselines", file=sys.stderr)
        return 1

    drops = find_drops(recorded, measured)
    if drops and not args.allow_drop:
        print(_render_drops(drops), file=sys.stderr)
        return 1

    if not args.update:
        rows = sum(len(families) for families in measured.values())
        print(f"recall-baselines: PASS: {rows} (family,backend) rows at or above baseline "
              f"across {sorted(measured)}")
        return 0

    overrides = list(recorded.get("overrides", []))
    if drops:
        overrides.append({
            "date": datetime.date.today().isoformat(),
            "reason": args.reason.strip(),
            "accepted": [
                {"backend": backend, "family": family, "from": was, "to": now}
                for backend, family, was, now in drops
            ],
        })

    cl = _load_cluster_module()
    payload = {
        "schema": SCHEMA,
        "target_fraction": TARGET_FRACTION,
        "target_note": (
            "0.75 is the aspirational recall target from "
            "pipeline/tests/fixtures/recurrence_ground_truth.json. The GATE is the "
            "recorded baseline below; see hindsight#121."
        ),
        "provenance": {
            "l1_sha256": cl.l1_corpus_digest(DEFAULT_L1),
            "cluster_sha256": cl.cluster_code_config_digest(CLUSTER_CODE),
            "corpus_size": len(cl.load_entries(DEFAULT_L1)),
        },
        "baselines": _merge_baselines(recorded, measured),
        "overrides": overrides,
    }
    tmp = args.artifact.with_suffix(args.artifact.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(args.artifact)
    rows = sum(len(families) for families in payload["baselines"].values())
    verb = "RECORDED (override)" if drops else "RECORDED"
    print(f"recall-baselines: {verb}: {rows} (family,backend) rows -> {args.artifact.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
