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
  (default)                          verify the committed artifact against measured recall
  --update                          re-measure and rewrite the artifact (release path)
  --allow-drop --reason             permit a measured drop below a recorded RAW baseline
  --allow-drop --reason --reconcile BACKEND/FAMILY
                                     also re-pin a *reconciled_floors* entry (hindsight#178):
                                     --allow-drop alone never touches reconciled_floors, so a
                                     drop against a reviewed exception stays refused until the
                                     exact backend/family is named here explicitly.
"""

from __future__ import annotations

import argparse
import copy
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
            # Deliberately NOT rounded. round(6/7, 6) == 0.857143 is *greater*
            # than 6/7, so a rounded baseline compares as a drop against the
            # very measurement that produced it -- the ratchet would fire on
            # nothing but float noise on its own recorded value.
            "fraction": largest / len(members),
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
    """(backend, family, effective_floor_fraction, measured_fraction) for every drop.

    A recorded reconciliation floor replaces the raw baseline for its matching
    backend/family; otherwise the raw baseline remains the comparison floor.

    A backend or family that is measured but has no recorded baseline is NOT a
    drop -- it is a new row, recorded on the next `--update`. A recorded row
    that was not measured this run is not a drop either (it was not observed);
    it is left untouched rather than silently reset, so an unreachable HTTP
    backend can never launder a regression by simply not being measured.
    """
    drops: list[tuple[str, str, float, float]] = []
    baselines = recorded.get("baselines", {})
    reconciled_floors = recorded.get("reconciled_floors", {})
    for backend_name, families in measured.items():
        recorded_backend = baselines.get(backend_name)
        if not recorded_backend:
            continue
        reconciled_backend = reconciled_floors.get(backend_name, {})
        for family, stats in families.items():
            recorded_family = recorded_backend.get(family)
            if recorded_family is None:
                continue
            reconciled_family = reconciled_backend.get(family)
            effective_floor = (
                reconciled_family if reconciled_family is not None else recorded_family
            )
            was = float(effective_floor["fraction"])
            now = float(stats["fraction"])
            # Tolerance, not equality: these are ratios of small integers that
            # round-trip through JSON. A ratchet that fires on the last bit of a
            # float is a ratchet that gets disabled by whoever it wakes up.
            if now < was - 1e-9:
                drops.append((backend_name, family, was, now))
    return sorted(drops)


def find_reconciled_drops(
    recorded: dict[str, object], measured: dict[str, dict[str, dict[str, object]]]
) -> list[tuple[str, str, float, float]]:
    """The subset of `find_drops` whose effective floor came from `reconciled_floors`.

    These are the drops `--allow-drop` alone must NOT silently accept: each one
    represents a previously reviewed, reconciled exception. Eroding it requires
    the operator to name it explicitly via `--reconcile backend/family` (see
    `main`) so the re-pin is a deliberate, auditable act rather than a side
    effect of an unrelated `--allow-drop --reason` for some other family.
    """
    reconciled_floors = recorded.get("reconciled_floors", {})
    out = []
    for backend_name, family, was, now in find_drops(recorded, measured):
        reconciled_backend = reconciled_floors.get(backend_name, {})
        if family in reconciled_backend:
            out.append((backend_name, family, was, now))
    return out


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


def _render_unreconciled(drops: list[tuple[str, str, float, float]]) -> str:
    lines = [
        "recall-baselines: REFUSED: --allow-drop cannot silently erode a reviewed",
        "reconciled_floors entry (hindsight#178). Each drop below names a",
        "backend/family whose effective floor came from `reconciled_floors`, not the",
        "raw `baselines` row -- --allow-drop --reason updates baselines/overrides",
        "only, and never touches a reconciled exception on its own.",
        "",
    ]
    for backend_name, family, was, now in drops:
        lines.append(f"  {backend_name}/{family}: {was:.4f} -> {now:.4f}")
    lines += [
        "",
        "Nothing was written. If this drop is a genuine re-measurement of an",
        "already-reviewed exception (corpus growth re-clustering the same fixture",
        "family, not a new quality regression), re-pin it explicitly by name:",
        "  --update --allow-drop --reason \"why\" "
        + " ".join(f"--reconcile {b}/{f}" for b, f, _, _ in drops),
        "This is deliberately a second, explicit flag beyond --allow-drop: naming",
        "the exact backend/family is what keeps this auditable rather than a side",
        "effect of an unrelated --allow-drop for some other family.",
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
    parser.add_argument(
        "--reconcile", action="append", dest="reconcile", default=[],
        metavar="BACKEND/FAMILY",
        help=(
            "repeatable; with --update --allow-drop --reason, explicitly re-pin "
            "reconciled_floors[BACKEND][FAMILY] to the newly measured value. "
            "--allow-drop alone never touches a reconciled_floors entry -- a "
            "drop against one is refused unless named here by exact backend/"
            "family, so re-pinning a reviewed exception stays a deliberate, "
            "auditable act rather than a side effect of an unrelated override. "
            "The named BACKEND/FAMILY must also have been measured by this run "
            "-- naming a target outside the --backend selection (or on an "
            "unavailable backend) is refused, never silently ignored."
        ),
    )
    args = parser.parse_args(argv)

    if args.allow_drop and not (args.reason or "").strip():
        print("recall-baselines: error: --allow-drop requires a non-empty --reason",
              file=sys.stderr)
        return 2
    if args.allow_drop and not args.update:
        print("recall-baselines: error: --allow-drop is only meaningful with --update",
              file=sys.stderr)
        return 2
    if args.reconcile and not args.allow_drop:
        print("recall-baselines: error: --reconcile is only meaningful with --allow-drop",
              file=sys.stderr)
        return 2

    reconcile_targets: set[tuple[str, str]] = set()
    for raw in args.reconcile:
        if "/" not in raw:
            print(f"recall-baselines: error: --reconcile expects BACKEND/FAMILY, got {raw!r}",
                  file=sys.stderr)
            return 2
        backend_name, family_name = raw.split("/", 1)
        reconcile_targets.add((backend_name, family_name))

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

    for backend_name, family_name in reconcile_targets:
        if family_name not in recorded.get("reconciled_floors", {}).get(backend_name, {}):
            print(
                "recall-baselines: error: --reconcile "
                f"{backend_name}/{family_name} names no existing "
                "reconciled_floors entry -- there is nothing reviewed to re-pin",
                file=sys.stderr,
            )
            return 2

    # Existing in the artifact is not enough: the target must also have been
    # MEASURED by this invocation. A target whose backend was never selected
    # (or was selected but unavailable, like an unreachable `http`) has no new
    # measurement to re-pin to, so it would fall out of `find_reconciled_drops`
    # and be silently skipped while the command printed RECORDED and exited 0 --
    # a cosmetic success that is exactly the class `--reconcile` exists to
    # close. An explicit operator instruction that cannot be carried out must
    # fail loudly and write nothing, naming both the target and what was in
    # fact measured.
    unmeasured = sorted(
        (backend_name, family_name)
        for backend_name, family_name in reconcile_targets
        if family_name not in measured.get(backend_name, {})
    )
    if unmeasured:
        measured_rows = sorted(
            f"{backend_name}/{family}"
            for backend_name, families in measured.items()
            for family in families
        )
        for backend_name, family_name in unmeasured:
            print(
                "recall-baselines: error: --reconcile "
                f"{backend_name}/{family_name} was never measured by this run, so "
                "there is no measured recall to re-pin it to -- refusing rather "
                "than reporting success without touching it",
                file=sys.stderr,
            )
        print(
            "recall-baselines: measured this run: "
            + (", ".join(measured_rows) if measured_rows else "(nothing)"),
            file=sys.stderr,
        )
        print(
            "recall-baselines: re-run with a --backend selection that measures "
            + ", ".join(sorted({backend for backend, _ in unmeasured}))
            + " (and confirm that backend is available).",
            file=sys.stderr,
        )
        return 2

    drops = find_drops(recorded, measured)
    if drops and not args.allow_drop:
        print(_render_drops(drops), file=sys.stderr)
        return 1

    reconciled_drops = find_reconciled_drops(recorded, measured)
    unreconciled = [
        drop for drop in reconciled_drops if (drop[0], drop[1]) not in reconcile_targets
    ]
    if unreconciled and args.allow_drop:
        print(_render_unreconciled(unreconciled), file=sys.stderr)
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
    # Reconciliation records explain reviewed exceptions to the raw measured
    # baseline. They are durable artifact evidence, not a newly measured row,
    # so a routine release rewrite must retain them exactly -- EXCEPT for an
    # entry the operator named explicitly via --reconcile, which is a
    # deliberate, reasoned re-pin (hindsight#178), not silent erosion.
    if "reconciled_floors" in recorded:
        payload["reconciled_floors"] = copy.deepcopy(recorded["reconciled_floors"])
        for backend_name, family, was, _now in reconciled_drops:
            if (backend_name, family) not in reconcile_targets:
                continue
            entry = payload["reconciled_floors"][backend_name][family]
            new_stats = measured[backend_name][family]
            date = datetime.date.today().isoformat()
            entry["cause"] = (
                entry.get("cause", "").rstrip()
                + f" UPDATE {date} (--reconcile {backend_name}/{family}): re-pinned "
                f"from {was:.4f} to {float(new_stats['fraction']):.4f} via "
                f"--allow-drop --reason: {args.reason.strip()}"
            )
            entry["together"] = new_stats["together"]
            entry["members"] = new_stats["members"]
            entry["fraction"] = new_stats["fraction"]
    tmp = args.artifact.with_suffix(args.artifact.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(args.artifact)
    rows = sum(len(families) for families in payload["baselines"].values())
    verb = "RECORDED (override)" if drops else "RECORDED"
    print(f"recall-baselines: {verb}: {rows} (family,backend) rows -> {args.artifact.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
