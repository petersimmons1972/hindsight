"""C2 — the recurrence report.

COORDINATOR-AUTHORED GROUND TRUTH (plan rule R3). These assertions were written
before any implementation existed, and they were derived by *measuring the real
481-record corpus*, not by inventing a fixture. Do not weaken a test here to make
an implementation pass; if a row is genuinely unsatisfiable, void it explicitly
in PLAN-TDD.md with the measurement that killed it, the way V7 and the
`fail-silent-gate` family were voided.

The point of this report is the sentence "this has happened before, N times,
across M repos, between date X and date Y". A report that cannot say that is not
a recurrence report no matter how green its suite is.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "pipeline" / "recurrence_report.py"
PINNED_CLUSTERS = REPO / "pipeline" / "L2" / "clusters.jsonl"

# --- ground truth, measured from the pinned artifact on 2026-08-02 -----------
# Members are named individually rather than by count so that a cluster which
# merely happens to be large cannot satisfy a family assertion.
COMPLETION_SIGNAL = [
    "fleet-OPS-11",
    "fleet-OPS-16",
    "fleet-OPS-21",
    "fleet-OPS-23",
    "fleet-OPS-28",
]
SHARED_CHECKOUT = [
    "fleet-OPS-8",
    "fleet-OPS-13",
    "fleet-OPS-36",
    "fleet-OPS-38",
    "fleet-OPS-41",
    "fleet-OPS-45",
]
DEDUP_IDENTITY_KEY = [
    "fleet-orch-ORC-1a",
    "fleet-orch-ORC-1b",
    "fleet-orch-ORC-1c",
]
# The measured ceiling: these four share a *cause shape*, not wording, and the
# lexical/dense engine does not group them. Pinned as an exact count so that a
# future change forces conscious re-measurement instead of silently passing.
FAIL_SILENT_CAUSE_SHAPE = [
    "fleet-CI-1",
    "hc-FM-05",
    "hc-FM-08",
    "fleet-orch-FM-C4",
]


def run_report(*args, clusters=None):
    """Invoke the report as a subprocess; never import-and-call.

    A subprocess is the only form that exercises argument parsing, the default
    clusters path, and the exit code together -- the three things a caller
    actually depends on.
    """
    cmd = [sys.executable, str(REPORT)]
    if clusters is not None:
        cmd += ["--clusters", str(clusters)]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))


def load_clusters(path=PINNED_CLUSTERS):
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return [r for r in rows if "members" in r]


# --------------------------------------------------------------------------
# The artifact this whole tier reads must exist and be the pinned one (FM-169).
# --------------------------------------------------------------------------


def test_pinned_cluster_artifact_is_committed():
    """CI must never re-derive clusters from the live embedding service.

    FM-169: the same code on the same corpus produced 189 clusters on four warm
    runs and 190 on one cold run. Re-deriving here would make this gate both
    flaky and dependent on a service being up.
    """
    assert PINNED_CLUSTERS.exists(), (
        "pipeline/L2/clusters.jsonl is absent. Generate it once with "
        "pipeline/cluster.py and COMMIT it; do not make this test derive it."
    )
    clusters = load_clusters()
    assert len(clusters) > 100, f"expected a real partition, got {len(clusters)} clusters"


def test_report_module_exists():
    assert REPORT.exists(), "pipeline/recurrence_report.py has not been written yet"


# --------------------------------------------------------------------------
# Ground-truth families. Each names its members, so a stub cannot pass by
# emitting the largest cluster and hoping.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family,members,min_size,min_repos",
    [
        ("completion-signal", COMPLETION_SIGNAL, 6, 2),
        ("shared-mutable-checkout", SHARED_CHECKOUT, 7, 1),
        ("dedup-identity-key", DEDUP_IDENTITY_KEY, 3, 1),
    ],
)
def test_ground_truth_family_is_reported_as_one_recurrence(
    family, members, min_size, min_repos
):
    """Every named member must appear in the SAME reported group."""
    res = run_report("--format", "json")
    assert res.returncode == 0, f"report failed: {res.stderr}"
    groups = json.loads(res.stdout)

    holding = [g for g in groups if set(members) <= set(g["members"])]
    assert holding, (
        f"no reported group contains all of {family}: {members}. "
        f"Members were split across groups, so the report would understate "
        f"this recurrence."
    )
    g = holding[0]
    assert g["size"] >= min_size, f"{family}: size {g['size']} < {min_size}"
    assert len(g["source_repos"]) >= min_repos, (
        f"{family}: spans {len(g['source_repos'])} repos, expected >= {min_repos}"
    )


def test_cause_shape_family_does_not_cocluster_PINNED_NEGATIVE():
    """The measured ceiling, pinned exactly (the C1d convention).

    These four records all describe a gate that failed silently, but they share
    no wording. The engine puts them in FOUR DISTINCT groups. If this ever goes
    red, someone must decide whether real capability improved or whether the
    partition collapsed -- do not simply update the number.
    """
    res = run_report("--format", "json")
    assert res.returncode == 0, res.stderr
    groups = json.loads(res.stdout)

    located = {}
    for g in groups:
        for m in FAIL_SILENT_CAUSE_SHAPE:
            if m in g["members"]:
                located[m] = g["cluster_id"]

    assert set(located) == set(FAIL_SILENT_CAUSE_SHAPE), (
        f"expected all four cause-shape records to be reported somewhere; "
        f"missing {set(FAIL_SILENT_CAUSE_SHAPE) - set(located)}"
    )
    assert len(set(located.values())) == 4, (
        f"expected exactly 4 distinct groups (the measured ceiling), got "
        f"{len(set(located.values()))}: {located}. Re-measure before changing this."
    )


# --------------------------------------------------------------------------
# Ranking and row content -- what makes it a *report* rather than a dump.
# --------------------------------------------------------------------------


def test_ranking_is_by_size_then_date_span():
    res = run_report("--format", "json")
    assert res.returncode == 0, res.stderr
    groups = json.loads(res.stdout)
    sizes = [g["size"] for g in groups]
    assert sizes == sorted(sizes, reverse=True), (
        f"groups are not ranked by size: first 10 sizes {sizes[:10]}"
    )

    # within one size band, wider date span ranks first
    for i in range(len(groups) - 1):
        a, b = groups[i], groups[i + 1]
        if a["size"] == b["size"]:
            sa, sb = a.get("span_days"), b.get("span_days")
            if sa is not None and sb is not None:
                assert sa >= sb, (
                    f"equal size {a['size']} but {a['cluster_id']} span {sa} "
                    f"ranked above {b['cluster_id']} span {sb}"
                )


def test_every_row_carries_the_evidence_a_reader_needs():
    """member IDs, source repos, and both dates -- a count alone is not evidence."""
    res = run_report("--format", "json")
    groups = json.loads(res.stdout)
    for g in groups:
        for field in ("cluster_id", "size", "members", "source_repos", "first_seen", "last_seen", "label"):
            assert field in g, f"{g.get('cluster_id')} missing {field}"
        assert len(g["members"]) == g["size"], (
            f"{g['cluster_id']}: size {g['size']} disagrees with "
            f"{len(g['members'])} listed members -- the count must be derived "
            f"from the members, never carried separately"
        )


def test_size_is_derived_from_members_not_read_from_the_file(tmp_path):
    """The assertion above cannot see this on its own.

    In the pinned artifact the serialized `size` already agrees with
    `len(members)`, so an implementation that simply trusts the serialized value
    is behaviourally identical there and survives. Only a partition where the two
    DISAGREE can tell the two implementations apart -- and a count that can drift
    away from the evidence it summarizes is exactly the FM-155 shape: a number
    reported as a measurement that nothing recomputed.
    """
    bad = tmp_path / "lying_size.jsonl"
    bad.write_text(
        json.dumps({"_meta": {"backend": "test", "entry_count": 2}})
        + "\n"
        + json.dumps(
            {
                "cluster_id": "c-999",
                "size": 99,  # a lie; there are two members
                "members": ["x-1", "x-2"],
                "source_repos": ["x"],
                "first_seen": "2026-01-01",
                "last_seen": "2026-01-02",
                "label": "fabricated",
            }
        )
        + "\n"
    )
    res = run_report("--format", "json", clusters=bad)
    if res.returncode != 0:
        # Failing loud on an internally inconsistent record is also correct.
        assert "99" in (res.stderr + res.stdout) or "size" in (res.stderr + res.stdout).lower()
        return
    groups = json.loads(res.stdout)
    assert groups[0]["size"] == 2, (
        f"the report echoed the serialized size {groups[0]['size']} instead of "
        f"deriving 2 from the members it actually has"
    )


def test_null_dates_do_not_crash_ranking():
    """c-043 in the pinned artifact has first_seen/last_seen of null.

    A report that sorts on date span must survive that rather than raising a
    TypeError comparing None.
    """
    clusters = load_clusters()
    assert any(c.get("first_seen") is None for c in clusters), (
        "the pinned artifact no longer contains a null-dated cluster; this test "
        "has lost its subject and must be re-pointed, not deleted"
    )
    res = run_report("--format", "json")
    assert res.returncode == 0, f"null dates crashed the report: {res.stderr}"


def test_text_output_names_members_not_just_counts():
    res = run_report()
    assert res.returncode == 0, res.stderr
    out = res.stdout
    for m in COMPLETION_SIGNAL:
        assert m in out, f"text report never names member {m}"


# --------------------------------------------------------------------------
# Honesty requirements. The report must disclose what it cannot see.
# --------------------------------------------------------------------------


def _header_block(stdout: str) -> str:
    """Everything before the first cluster row.

    Scoping matters: cluster LABELS come from the corpus and happen to contain
    words like `missing_recall`. An unscoped substring search over the whole
    report is therefore satisfiable by corpus data rather than by the report's
    own disclosure -- which is exactly how the first version of the test below
    passed a mutant that had replaced the disclosure with "Report complete."
    """
    lines = []
    for line in stdout.splitlines():
        if re.match(r"^c-\d+:", line.strip()):
            break
        lines.append(line)
    return "\n".join(lines)


def test_report_discloses_its_recall_limitation():
    """It under-reports recurrence. It must say so, on the report itself.

    Silence here is the FM-155/FM-149 family: a partial measurement rendering as
    a complete one.

    MUTATION-PINNED: replacing the disclosure line with any reassuring sentence
    must fail this test. Do not loosen it back to a substring search over the
    whole document.
    """
    res = run_report()
    assert res.returncode == 0, res.stderr
    header = _header_block(res.stdout).lower()

    assert header.strip(), "the report emitted no header block at all"
    assert "limitation" in header, (
        "the report's header states no limitation. It cannot group records that "
        "share a cause shape but no wording (measured: 1/77 blind paraphrase "
        "recall), and a reader who does not know that will read absence as "
        "evidence of no recurrence."
    )
    assert "under-report" in header or "under report" in header, (
        "the header mentions a limitation but never says the report "
        "UNDER-REPORTS. Direction matters: a reader must know the error runs "
        "toward missing recurrences, not inventing them."
    )
    assert "1/77" in header or "1 of 77" in header, (
        "the disclosure cites no measurement. An unquantified caveat is a "
        "disclaimer, not a disclosure."
    )


# --------------------------------------------------------------------------
# Fail-loud contract (R4). Nothing here may fail open.
# --------------------------------------------------------------------------


def test_empty_clusters_file_exits_1_not_an_empty_report(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    res = run_report(clusters=empty)
    assert res.returncode == 1, (
        f"empty clusters must exit 1, got {res.returncode}. An empty report "
        f"reads as 'nothing has ever recurred', which is the exact inversion "
        f"this repository exists to prevent."
    )
    assert res.stdout.strip() == "" or "0 " in res.stdout or res.stderr.strip()


def test_meta_only_file_exits_1():
    """A file with a _meta row but no clusters is still empty."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write(json.dumps({"_meta": {"backend": "http", "entry_count": 0}}) + "\n")
        p = fh.name
    res = run_report(clusters=p)
    assert res.returncode == 1, "a _meta-only file must not read as a valid partition"


def test_missing_clusters_file_exits_nonzero_and_says_so(tmp_path):
    res = run_report(clusters=tmp_path / "does-not-exist.jsonl")
    assert res.returncode != 0, "a missing clusters file must never exit 0"
    assert "does-not-exist" in (res.stderr + res.stdout), (
        "the error must name the path it could not read"
    )


def test_malformed_line_fails_loud_rather_than_being_skipped(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"cluster_id":"c-1","size":2,"members":["a","b"]}\n{not json\n')
    res = run_report(clusters=bad)
    assert res.returncode != 0, (
        "a malformed line was silently skipped. Silently dropping records is "
        "how a partial corpus renders as a complete one."
    )


def test_default_clusters_path_follows_the_module_not_a_hardcoded_home(tmp_path):
    """V12: reconcile_l1.py shipped a hardcoded /home/psimmons path and so
    resolved zero sources on CI while printing COMPLETE. Same trap, same test:
    relocate the module and it must still find its data relative to itself.
    """
    import shutil

    stage = tmp_path / "relocated"
    (stage / "pipeline" / "L2").mkdir(parents=True)
    shutil.copy(REPORT, stage / "pipeline" / "recurrence_report.py")
    shutil.copy(PINNED_CLUSTERS, stage / "pipeline" / "L2" / "clusters.jsonl")

    res = subprocess.run(
        [sys.executable, str(stage / "pipeline" / "recurrence_report.py"), "--format", "json"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert res.returncode == 0, (
        f"relocated module could not find its own data: {res.stderr}. The "
        f"default path must derive from __file__, never from a fixed home dir."
    )
    groups = json.loads(res.stdout)
    assert len(groups) > 100
