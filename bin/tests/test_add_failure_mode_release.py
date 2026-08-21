#!/usr/bin/env python3
"""A canonical catalog add must land the L2 embedding-snapshot release with it.

hindsight#108: ``bin/add-failure-mode.sh``'s ``RUN_FULL_LOOP`` grows
``pipeline/L1/homelab-canon.jsonl`` but never performs the controlled release
step that re-derives ``pipeline/L2/embedding-snapshot.json`` (and the committed
``pipeline/L2/clusters.jsonl`` partition replayed from it). The add reports
success, and ``catalog-guard`` CI is the first thing that notices -- after the
commit has already landed.

These tests are behavioural, not textual. Nothing here greps the shell script
for a command name and calls that proof: the contract asserted is the one CI
actually enforces -- ``python3 pipeline/replay_l2.py`` exits 0 -- evaluated on a
throwaway copy of this repository before and after a real invocation of
``bin/add-failure-mode.sh``. A future rewrite that reaches consistency some
other way keeps passing; a rewrite that only *mentions* the release command
does not.

Hermeticity. The real release command
(``pipeline/capture_embedding_snapshot.py``) is documented as a controlled
release action against a live embedding backend, and CI must never invoke it.
So each sandbox installs a stand-in at that exact path whose behaviour the test
chooses: an honest offline release, a release that silently does nothing, one
that fails, one that destroys the evidence the checker reads, and no release
command at all. The stand-in records every invocation. That makes the whole
suite offline and deterministic while still exercising the real script, the
real guard, the real clustering core and the real replay checker.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADD_TOOL = REPO_ROOT / "bin" / "add-failure-mode.sh"
CAPTURE_REL = Path("pipeline") / "capture_embedding_snapshot.py"
SNAPSHOT_REL = Path("pipeline") / "L2" / "embedding-snapshot.json"
CLUSTERS_REL = Path("pipeline") / "L2" / "clusters.jsonl"
CATALOG_REL = Path("catalog") / "failure-modes.md"
LEDGER_REL = Path("catalog") / "id-ledger.txt"
PIN_RELATIVES = (
    Path("pipeline") / "tests" / "test_replay_l2.py",
    Path("pipeline") / "tests" / "test_replay_l2_mutations.py",
)
MARKER_NAME = ".release-invocations"

COPY_IGNORE = shutil.ignore_patterns(".git", ".workflow-lanes", "__pycache__", "*.pyc", ".venv")

# Sibling repositories the canonical (full-loop) branch refuses to run without.
SIBLING_FILES = (
    Path("fleet") / "FAILURE-MODES.md",
    Path("fleet") / "orchestration" / "FAILURE-MODES.md",
    Path("fleet") / "CODING-INVARIANTS.md",
    Path("fleet") / "CODING-FAILURE-MODES.md",
    Path("claude-codex") / "docs" / "integration-failure-modes.md",
    Path("fleet-dispatch") / "migrations" / "0017_failure_class.sql",
)

ADD_TIMEOUT = 1800
CHECK_TIMEOUT = 900


# ── the stand-in release command ──────────────────────────────────────────────
#
# MODE is substituted per sandbox. Every mode records its invocation first, so
# "was the release step reached at all?" is answerable independently of whether
# the release succeeded.

_RELEASE_STUB = '''#!/usr/bin/env python3
"""Test stand-in for the controlled embedding-snapshot release command."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

MODE = {mode!r}

REPO = Path(__file__).resolve().parents[1]
MARKER = REPO / {marker!r}
with MARKER.open("a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")

SNAPSHOT = REPO / "pipeline" / "L2" / "embedding-snapshot.json"
CLUSTERS = REPO / "pipeline" / "L2" / "clusters.jsonl"
L1 = REPO / "pipeline" / "L1"
CODE = REPO / "pipeline" / "cluster.py"

if MODE == "noop":
    print("release stand-in: did nothing at all")
    raise SystemExit(0)

if MODE == "fail":
    print("release stand-in: embedding backend unavailable", file=sys.stderr)
    raise SystemExit(1)

if MODE == "evidence_gone":
    SNAPSHOT.unlink(missing_ok=True)
    print("release stand-in: removed the snapshot and claimed success")
    raise SystemExit(0)

if MODE != "honest":
    raise SystemExit(f"release stand-in: unknown mode {{MODE!r}}")

import numpy as np

spec = importlib.util.spec_from_file_location("hindsight_release_cluster", CODE)
cl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cl
spec.loader.exec_module(cl)

entries = cl.load_entries(L1)
dimensions = int(cl.HTTP_BACKEND_IDENTITY["dimensions"])

previous = {{}}
if SNAPSHOT.exists():
    try:
        previous = json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("embeddings") or {{}}
    except (json.JSONDecodeError, OSError, AttributeError):
        previous = {{}}


def deterministic_vector(entry_id):
    seed = int.from_bytes(hashlib.sha256(entry_id.encode("utf-8")).digest()[:8], "big")
    vector = np.random.default_rng(seed).normal(size=dimensions)
    vector /= np.linalg.norm(vector)
    return [round(float(value), 6) for value in vector]


embeddings = {{}}
for entry in entries:
    kept = previous.get(entry.id)
    if isinstance(kept, list) and len(kept) == dimensions:
        embeddings[entry.id] = kept
    else:
        embeddings[entry.id] = deterministic_vector(entry.id)

l1_digest = cl.l1_corpus_digest(L1)
cluster_digest = cl.cluster_code_config_digest(CODE)
SNAPSHOT.write_text(json.dumps({{
    "schema": cl.SNAPSHOT_SCHEMA,
    "provenance": {{"l1_sha256": l1_digest, "cluster_sha256": cluster_digest}},
    "backend": dict(cl.HTTP_BACKEND_IDENTITY),
    "embeddings": embeddings,
}}) + "\\n", encoding="utf-8")

matrix = cl.load_embedding_snapshot(
    SNAPSHOT, entries, cl.HTTP_BACKEND_IDENTITY,
    expected_l1_digest=l1_digest, expected_cluster_digest=cluster_digest,
)
threshold = cl.default_threshold("http")
ordered = sorted(entries, key=lambda entry: entry.id)
clusters = cl.cluster_entries(ordered, matrix, backend_name="http", threshold=threshold)


class _Identity:
    name = "http"

    def embed(self, texts):  # pragma: no cover - the release never embeds here
        raise AssertionError("the offline release stand-in must not embed")


cl.write_clusters(CLUSTERS, clusters, _Identity(), threshold, len(entries))
print(f"release stand-in: {{len(entries)}} entries, {{len(clusters)}} clusters")
'''


def _install_release(repo: Path, mode: str) -> None:
    """Put a stand-in release command at the path the real one occupies."""
    target = repo / CAPTURE_REL
    if mode == "absent":
        target.unlink(missing_ok=True)
        return
    target.write_text(_RELEASE_STUB.format(mode=mode, marker=MARKER_NAME), encoding="utf-8")
    target.chmod(0o755)


def _run(argv: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("CATALOG", None)
    env.pop("CORPUS", None)
    return subprocess.run(
        argv, cwd=str(cwd), env=env, text=True, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


def _replay(repo: Path) -> subprocess.CompletedProcess[str]:
    """The exact consistency check catalog-guard runs, on this repo copy."""
    return _run([sys.executable, "pipeline/replay_l2.py"], repo, CHECK_TIMEOUT)


def _add(repo: Path, description: str, *, catalog: Path | None = None) -> subprocess.CompletedProcess[str]:
    argv = ["bash", str(repo / "bin" / "add-failure-mode.sh"),
            "-c", "A", "-t", "LOW", "--recurrence-of", "none", description]
    env = dict(os.environ)
    env.pop("CORPUS", None)
    if catalog is None:
        env.pop("CATALOG", None)
    else:
        env["CATALOG"] = str(catalog)
    return subprocess.run(
        argv, cwd=str(repo), env=env, text=True, timeout=ADD_TIMEOUT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "<absent>"


def _report(label: str, *results: subprocess.CompletedProcess[str]) -> str:
    blocks = [f"--- {' '.join(map(str, result.args))} -> {result.returncode}\n{result.stdout}"
              for result in results]
    return label + "\n" + "\n".join(blocks)


def _release_invocations(repo: Path) -> list[str]:
    marker = repo / MARKER_NAME
    if not marker.exists():
        return []
    return [line for line in marker.read_text(encoding="utf-8").splitlines()]


def _reported_counts(output: str) -> tuple[int, int]:
    matches = re.findall(r"replay-l2: PASS: (\d+) entries, (\d+) clusters", output)
    assert len(matches) == 1, output
    return tuple(map(int, matches[0]))


def _pinned_counts(repo: Path) -> tuple[tuple[int, int], tuple[int, int], int]:
    replay_source = (repo / PIN_RELATIVES[0]).read_text(encoding="utf-8")
    mutations_source = (repo / PIN_RELATIVES[1]).read_text(encoding="utf-8")
    replay_matches = re.findall(
        r'assert REPLAY\.main\(\[\]\) == 0 and "PASS: (\d+) entries, (\d+) clusters"',
        replay_source,
    )
    exact_matches = re.findall(
        r'replay-l2: PASS: (\d+) entries, (\d+) clusters\\n', mutations_source
    )
    embedding_matches = re.findall(r'len\(payload\["embeddings"\]\) == (\d+)', mutations_source)
    assert len(replay_matches) == len(exact_matches) == len(embedding_matches) == 1
    return (*map(lambda pair: tuple(map(int, pair)), (replay_matches[0], exact_matches[0])), int(embedding_matches[0]))


def _undo_dir(output: str) -> Path:
    match = re.search(r"^UNDO: .* --undo (.+)$", output, flags=re.MULTILINE)
    assert match, output
    return Path(match.group(1))


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def green_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of this repository whose committed L2 replay is known-green.

    The checked-in tree may itself be mid-drift (that is the bug), so the
    baseline is established here rather than assumed: run the honest release
    once and require the replay checker to pass. If it cannot be made green
    the suite FAILS -- it never skips, because a skipped baseline would let
    every downstream assertion pass by never running.
    """
    workspace = tmp_path_factory.mktemp("release-template")
    repo = workspace / "hindsight"
    shutil.copytree(REPO_ROOT, repo, symlinks=True, ignore=COPY_IGNORE)
    for relative in SIBLING_FILES:
        sibling = workspace / relative
        sibling.parent.mkdir(parents=True, exist_ok=True)
        sibling.touch()

    _install_release(repo, "honest")
    release = _run([sys.executable, str(repo / CAPTURE_REL)], repo, CHECK_TIMEOUT)
    assert release.returncode == 0, _report("baseline release failed", release)

    replay = _replay(repo)
    assert replay.returncode == 0, _report(
        "the test baseline could not be made consistent, so no add can be judged against it",
        release, replay,
    )
    (repo / MARKER_NAME).unlink(missing_ok=True)
    return repo


@pytest.fixture
def sandbox(green_template: Path, tmp_path: Path):
    """Fresh, independently mutable copy of the green baseline per test."""
    def build(mode: str) -> Path:
        workspace = tmp_path / mode
        repo = workspace / "hindsight"
        shutil.copytree(green_template.parent, workspace, symlinks=True, ignore=COPY_IGNORE)
        _install_release(repo, mode)
        (repo / MARKER_NAME).unlink(missing_ok=True)
        assert _replay(repo).returncode == 0, "sandbox did not start consistent"
        return repo

    return build


# ── the contract: a successful add lands consistent ───────────────────────────


def test_successful_canonical_add_leaves_the_committed_l2_replay_green(sandbox) -> None:
    repo = sandbox("honest")
    before = _replay(repo)
    assert before.returncode == 0

    added = _add(repo, "an add left the committed L2 snapshot behind its own L1 corpus")
    assert added.returncode == 0, _report("the canonical add itself failed", added)

    after = _replay(repo)
    assert after.returncode == 0, _report(
        "add-failure-mode.sh reported success but left catalog-guard's replay red",
        added, after,
    )


def test_successful_canonical_add_grows_the_catalog_it_just_released(sandbox) -> None:
    """Guards the vacuous fix: staying green by never writing anything."""
    repo = sandbox("honest")
    catalog = repo / CATALOG_REL
    ledger = repo / LEDGER_REL
    rows_before = catalog.read_text(encoding="utf-8").count("\n| FM-")
    ledger_before = len(ledger.read_text(encoding="utf-8").splitlines())

    added = _add(repo, "a release step that skips the write would also stay green")
    assert added.returncode == 0, _report("the canonical add itself failed", added)

    assert catalog.read_text(encoding="utf-8").count("\n| FM-") == rows_before + 1
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == ledger_before + 1
    assert _replay(repo).returncode == 0


def test_successful_canonical_add_invokes_the_controlled_release_command(sandbox) -> None:
    repo = sandbox("honest")
    added = _add(repo, "the release command must be reached by the write path itself")
    assert added.returncode == 0, _report("the canonical add itself failed", added)
    assert _release_invocations(repo), _report(
        f"the add never invoked {CAPTURE_REL}; consistency must come from the "
        "sanctioned release command inside the write path, not from a manual "
        "second step a human is trusted to remember",
        added,
    )


def test_successful_canonical_add_derives_all_replay_pins_and_undo_restores_them(sandbox) -> None:
    repo = sandbox("honest")
    pin_paths = [repo / relative for relative in PIN_RELATIVES]
    pins_before = {path: _digest(path) for path in pin_paths}

    added = _add(repo, "the filing transaction must derive every replay pin")
    assert added.returncode == 0, _report("the canonical add itself failed", added)
    entries, clusters = _reported_counts(added.stdout)
    replay_pin, exact_pin, embedding_pin = _pinned_counts(repo)
    assert replay_pin == (entries, clusters)
    assert exact_pin == (entries, clusters)
    assert embedding_pin == entries

    undo = _run(
        ["bash", str(repo / "bin" / "add-failure-mode.sh"), "--undo", str(_undo_dir(added.stdout))],
        repo,
        CHECK_TIMEOUT,
    )
    assert undo.returncode == 0, _report("undo did not restore the filing transaction", undo)
    assert {path: _digest(path) for path in pin_paths} == pins_before


def test_unlocatable_replay_pin_fails_loudly_without_partial_write(sandbox) -> None:
    repo = sandbox("honest")
    broken_pin = repo / PIN_RELATIVES[0]
    broken_pin.write_text("pin intentionally unavailable\n", encoding="utf-8")
    protected = [
        repo / CATALOG_REL,
        repo / LEDGER_REL,
        repo / "pipeline" / "L1" / "homelab-canon.jsonl",
        repo / SNAPSHOT_REL,
        repo / CLUSTERS_REL,
        *(repo / relative for relative in PIN_RELATIVES),
    ]
    before = {path: _digest(path) for path in protected}

    added = _add(repo, "a missing replay pin must abort the whole filing transaction")
    assert added.returncode != 0, _report("the add accepted an unlocatable replay pin", added)
    assert "replay pin" in added.stdout.lower()
    assert {path: _digest(path) for path in protected} == before


def test_external_corpus_drift_still_fails_the_literal_replay_pins(sandbox) -> None:
    repo = sandbox("honest")
    added = _add(repo, "the pins must remain independent replay oracles")
    assert added.returncode == 0, _report("the canonical add itself failed", added)

    corpus = repo / "pipeline" / "L1" / "homelab-canon.jsonl"
    corpus.write_text(corpus.read_text(encoding="utf-8").replace('"instance"', '"instance_x"', 1), encoding="utf-8")
    replay_tests = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "pipeline/tests/test_replay_l2.py::test_committed_snapshot_replays_through_real_default_loader",
            "pipeline/tests/test_replay_l2_mutations.py::test_default_committed_replay_succeeds_with_network_poisoned",
        ],
        repo,
        CHECK_TIMEOUT,
    )
    assert replay_tests.returncode != 0, _report(
        "corpus drift made the replay pins tautological instead of failing", replay_tests
    )
    assert "2 failed" in replay_tests.stdout, _report(
        "both literal replay-pin tests must reject corpus drift", replay_tests
    )


# ── the negatives: an add without a real release must be caught ───────────────


def test_release_that_silently_does_nothing_fails_the_add(sandbox) -> None:
    """Invoking the release is not the contract; leaving the repo consistent is.

    The stand-in here exits 0 and changes nothing -- exactly the shape of the
    bug, where the snapshot is left behind the grown corpus. The add must fail
    loudly before commit rather than inherit the release command's exit code.
    """
    repo = sandbox("noop")
    catalog_before = _digest(repo / CATALOG_REL)
    ledger_before = _digest(repo / LEDGER_REL)

    added = _add(repo, "a release that returns success without releasing anything")
    assert added.returncode != 0, _report(
        "the add reported success while the committed snapshot was left stale", added, _replay(repo),
    )
    assert _digest(repo / CATALOG_REL) == catalog_before
    assert _digest(repo / LEDGER_REL) == ledger_before


def test_failing_release_fails_the_add_and_restores_the_tree(sandbox) -> None:
    repo = sandbox("fail")
    catalog_before = _digest(repo / CATALOG_REL)
    ledger_before = _digest(repo / LEDGER_REL)

    added = _add(repo, "the embedding backend was down when the release was attempted")
    assert added.returncode != 0, _report("a failed release did not fail the add", added)
    assert _digest(repo / CATALOG_REL) == catalog_before
    assert _digest(repo / LEDGER_REL) == ledger_before
    assert _replay(repo).returncode == 0, _report(
        "a failed add left the repository inconsistent instead of as it found it", added,
    )


def test_add_fails_when_the_release_destroys_the_evidence_and_claims_success(sandbox) -> None:
    """The checker's own evidence source is gone -- that must FAIL, not pass.

    A verification that reads the snapshot must treat "there is no snapshot" as
    a failure. Skipping the check when its input is missing is the exact shape
    that turns a gate into decoration.
    """
    repo = sandbox("evidence_gone")
    added = _add(repo, "the release removed the snapshot and exited zero")
    assert added.returncode != 0, _report(
        "the add passed with no embedding snapshot on disk at all", added,
    )


def test_destroyed_snapshot_is_restored_when_the_add_rolls_back(sandbox) -> None:
    repo = sandbox("evidence_gone")
    snapshot_before = _digest(repo / SNAPSHOT_REL)
    clusters_before = _digest(repo / CLUSTERS_REL)
    assert snapshot_before != "<absent>"

    added = _add(repo, "a rolled-back add must restore the release artefacts too")
    assert added.returncode != 0
    assert _digest(repo / SNAPSHOT_REL) == snapshot_before, _report(
        "the undo journal does not cover the release artefacts it now writes", added,
    )
    assert _digest(repo / CLUSTERS_REL) == clusters_before
    assert _replay(repo).returncode == 0


def test_absent_release_command_fails_the_add(sandbox) -> None:
    """No stand-in at all: an unavailable release must be loud, never skipped."""
    repo = sandbox("absent")
    catalog_before = _digest(repo / CATALOG_REL)
    ledger_before = _digest(repo / LEDGER_REL)

    added = _add(repo, "the release command was missing from the tree entirely")
    assert added.returncode != 0, _report(
        "the add succeeded with no release command present", added,
    )
    assert _digest(repo / CATALOG_REL) == catalog_before
    assert _digest(repo / LEDGER_REL) == ledger_before


# ── the boundary: the light path is not a release ─────────────────────────────


def test_non_canonical_add_does_not_trigger_a_release(sandbox, tmp_path: Path) -> None:
    """Only a canonical write grows L1, so only a canonical write may release.

    Firing a live-backend release for every scratch-catalog add would be a
    different defect: it makes the cheap path depend on a service it does not
    need. This is the over-implementation boundary.
    """
    repo = sandbox("honest")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    catalog = scratch / "failure-modes.md"
    shutil.copy2(repo / CATALOG_REL, catalog)
    shutil.copy2(repo / LEDGER_REL, scratch / "id-ledger.txt")
    snapshot_before = _digest(repo / SNAPSHOT_REL)

    added = _add(repo, "a scratch-catalog add needs no embedding release", catalog=catalog)
    assert added.returncode == 0, _report("the light-path add failed", added)
    assert not _release_invocations(repo), _report(
        "a non-canonical add invoked the controlled release command", added,
    )
    assert _digest(repo / SNAPSHOT_REL) == snapshot_before
