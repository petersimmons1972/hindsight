"""What CI actually runs, and whether the repo's own comments say so truthfully.

Two separate jobs live here.

1. The workflow pin. `.github/workflows/guard.yml` is pinned by full-file digest
   so no workflow edit can land without a human updating this test.

2. The claim audit. Three call sites reconcile L1 with `--source` scoping, and
   each carries a comment explaining what is still covered elsewhere. A comment
   that certifies a check nobody runs is this registry's own headline failure
   mode -- a proxy trusted in place of the thing -- so the comments are checked
   against what `guard.yml` demonstrably executes, not against a fixed string.
   Every rule below is DERIVED: the scoped sources come from parsing the
   workflow, the full source list comes from `reconcile_l1.ENUMERABLE`. If CI
   later starts running an unscoped reconcile, these tests relax on their own.
"""
import hashlib
import importlib.util
import re
from pathlib import Path


REPO = Path(__file__).parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "guard.yml"
RECONCILE = REPO / "pipeline" / "reconcile_l1.py"
PRE_COMMIT = REPO / ".githooks" / "pre-commit"
ADD_TOOL = REPO / "bin" / "add-failure-mode.sh"
REQUIRE_REAL_CI = REPO / "bin" / "require-real-ci.sh"
BATS_WORKFLOW_CONTRACT = REPO / "guard" / "tests" / "test_ci_workflow_contract.bats"

# sha256 of .github/workflows/guard.yml, measured with
#   python3 -c "import hashlib,pathlib;print(hashlib.sha256(
#       pathlib.Path('.github/workflows/guard.yml').read_bytes()).hexdigest())"
# ANY edit to that workflow changes this value and MUST update it here in the
# same change -- that is the whole point of the pin. Never copy a digest out of
# a review comment or a PR body; recompute it against the file on disk.
INTENDED_WORKFLOW_SHA256 = "7c0a8984f7d02e3358b0b8443e0fbaa58e96bfbdb4b6b1dda87cbb11a05ba89c"

# A comment sentence may name a broader-than-CI check only while denying it.
# "CI never runs the unscoped gate" is true; "the unscoped run CI uses" is not.
_OVERCLAIM_TOKENS = ("unscoped", "all five", "every source", "full corpus",
                     "corpus-wide", "corpus wide")
_NEGATION = re.compile(
    r"\b(not|never|no|none|cannot|can't|isn't|aren't|without|nothing|neither)\b",
    re.IGNORECASE,
)
_CI = re.compile(r"\bCI\b")
_SOURCE_ARG = re.compile(r"--source[=\s]+(?:'([^']*)'|\"([^\"]*)\"|([^\s\\]+))")
_GATE_ARG = re.compile(r"--gate[=\s]+(?:'([^']*)'|\"([^\"]*)\"|([^\s\\]+))")
_MATRIX_SHARD_LIST = re.compile(r"(?m)^        shard: \[([^\]\n]+)\]$")
_STEP_SHARD_IF = re.compile(
    r"^        if: matrix\.shard\s*(==|!=)\s*'([^']+)'$"
)


# ── evidence loaders: an unreadable evidence source must FAIL, never skip ─────

def _read(path: Path) -> str:
    assert path.is_file(), (
        f"evidence source missing: {path}. This check cannot pass without it; "
        "an absent input is not a clean result."
    )
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"evidence source is empty: {path}"
    return text


def _enumerable_slugs() -> set[str]:
    """The full source list, read from the reconciler itself -- never hardcoded."""
    assert RECONCILE.is_file(), f"evidence source missing: {RECONCILE}"
    spec = importlib.util.spec_from_file_location("_reconcile_l1_probe", RECONCILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    slugs = set(getattr(module, "ENUMERABLE", {}))
    assert slugs, "reconcile_l1.ENUMERABLE is empty -- nothing could be scoped"
    return slugs


def _step_blocks(workflow: str) -> list[tuple[str, ...]]:
    """Extract job step blocks at the workflow's six-space list indentation."""
    blocks: list[list[str]] = []
    for line in workflow.splitlines():
        if line.startswith("      - "):
            blocks.append([line])
        elif blocks and (line.startswith("        ") or not line.strip()):
            blocks[-1].append(line)
    return [tuple(block) for block in blocks]


def _declared_matrix_shards(workflow: str) -> tuple[str, ...]:
    """Return the one declared matrix.shard list, failing on ambiguity."""
    declarations = _MATRIX_SHARD_LIST.findall(workflow)
    assert len(declarations) == 1, (
        "guard.yml must declare exactly one inline matrix.shard list; found "
        f"{len(declarations)}"
    )
    shards = tuple(item.strip() for item in declarations[0].split(","))
    assert shards and all(shards), (
        "matrix.shard must declare at least one non-empty value"
    )
    assert len(shards) == len(set(shards)), (
        f"matrix.shard contains duplicate values: {shards}"
    )
    return shards


def _step_label(block: tuple[str, ...]) -> str:
    return block[0].removeprefix("      - ")


def _validated_step_shard_conditions(
    workflow: str,
) -> tuple[tuple[str, ...], list[tuple[tuple[str, ...], str, str]]]:
    """Return declared shards and validated step-level shard conditions."""
    declared = _declared_matrix_shards(workflow)
    guarded_steps: list[tuple[tuple[str, ...], str, str]] = []

    for block in _step_blocks(workflow):
        shard_lines = [line for line in block if "matrix.shard" in line]
        if not shard_lines:
            continue
        assert len(shard_lines) == 1, (
            f"{_step_label(block)} must have exactly one matrix.shard condition; "
            f"found {shard_lines}"
        )
        comparison = _STEP_SHARD_IF.fullmatch(shard_lines[0])
        assert comparison is not None, (
            f"{_step_label(block)} has an unsupported matrix.shard condition: "
            f"{shard_lines[0].strip()!r}"
        )
        operation, literal = comparison.groups()
        assert literal in declared, (
            f"{_step_label(block)} uses unknown matrix.shard literal {literal!r}; "
            f"declared shards are {declared}"
        )
        guarded_steps.append((block, operation, literal))

    assert guarded_steps, "guard.yml has no step-level matrix.shard conditions"
    return declared, guarded_steps


def _reconcile_commands(workflow: str) -> list[str]:
    """Every executable (non-comment) reconcile invocation in the workflow."""
    return [
        line.strip() for line in workflow.splitlines()
        if "reconcile_l1.py" in line and not line.strip().startswith("#")
    ]


def _scoped_sources(command: str) -> list[str]:
    return ["".join(match) for match in _SOURCE_ARG.findall(command)]


def _gated_sources(command: str) -> list[str]:
    return [slug for match in _GATE_ARG.findall(command) for slug in "".join(match).split(",")]


def _preceding_comment_block(path: Path, needle: str) -> str:
    """The contiguous comment block immediately above the first real use of `needle`."""
    lines = _read(path).splitlines()
    idx = next(
        (i for i, line in enumerate(lines)
         if needle in line and not line.strip().startswith("#")),
        None,
    )
    assert idx is not None, f"{path} has no executable line containing {needle!r}"
    block: list[str] = []
    j = idx - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        block.append(lines[j].strip().lstrip("#").strip())
        j -= 1
    text = "\n".join(reversed(block))
    assert text.strip(), (
        f"{path}: the {needle!r} invocation carries no explanatory comment, so "
        "there is nothing to audit and nothing telling the next reader what CI "
        "does and does not cover."
    )
    return text


def _sentences(block: str) -> list[str]:
    flat = " ".join(block.split())
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if s.strip()]


def _top_level_block(workflow: str, key: str) -> str:
    """Return the YAML block for a top-level mapping key, including its header.

    Stops at the next non-comment top-level key. An absent key fails loudly
    rather than returning empty — an empty block would make 'push is scoped'
    vacuously true.
    """
    lines = workflow.splitlines()
    start = next(
        (
            i for i, line in enumerate(lines)
            if not line.startswith((" ", "\t")) and (line == f"{key}:" or line.startswith(f"{key}:"))
        ),
        None,
    )
    assert start is not None, f"guard.yml has no top-level {key!r} key"
    collected = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("#") or line.startswith((" ", "\t")) or not line.strip():
            collected.append(line)
            continue
        break
    return "\n".join(collected)


def _render_matrix_timeout(expression: str, shard: str) -> int:
    """Evaluate the narrow conditional form used by guard.timeout-minutes."""
    wrapped = re.fullmatch(r"\$\{\{\s*(.*?)\s*}}", expression)
    assert wrapped is not None, f"unsupported timeout expression: {expression!r}"
    branches = [branch.strip() for branch in wrapped.group(1).split("||")]
    assert len(branches) >= 2, "timeout expression has no conditional branches"

    for branch in branches[:-1]:
        conditional = re.fullmatch(
            r"matrix\.shard == '([^']+)'\s*&&\s*([1-9][0-9]*)",
            branch,
        )
        assert conditional is not None, f"unsupported timeout branch: {branch!r}"
        if shard == conditional.group(1):
            return int(conditional.group(2))

    assert re.fullmatch(r"[1-9][0-9]*", branches[-1]), (
        f"unsupported timeout default: {branches[-1]!r}"
    )
    return int(branches[-1])


# ── the workflow pin ─────────────────────────────────────────────────────────

def test_pinned_workflow_evidence_source_must_be_present() -> None:
    # A pin whose subject is gone must fail loudly rather than vacuously pass.
    assert WORKFLOW.is_file(), f"pinned workflow missing: {WORKFLOW}"
    assert WORKFLOW.read_bytes().strip(), "pinned workflow is empty"
    assert re.fullmatch(r"[0-9a-f]{64}", INTENDED_WORKFLOW_SHA256), (
        "INTENDED_WORKFLOW_SHA256 is not a well-formed sha256 digest -- an "
        "abbreviated or mistyped value cannot pin anything."
    )


def test_every_step_shard_literal_is_declared() -> None:
    _validated_step_shard_conditions(_read(WORKFLOW))


def test_workflow_contract_runs_unconditionally_in_every_shard() -> None:
    contract_steps = [
        block for block in _step_blocks(_read(WORKFLOW))
        if block[0] == "      - name: Validate workflow shard contract"
    ]
    assert contract_steps == [(
        "      - name: Validate workflow shard contract",
        (
            "        run: bash guard/tests/ci_workflow_contract.bash "
            ".github/workflows/guard.yml"
        ),
    )], (
        "the workflow contract must be an unconditional matrix pre-step; "
        "a shard-specific test step cannot be its only execution anchor"
    )


def test_workflow_integrity_detectors_are_reachable_from_distinct_shards() -> None:
    workflow = _read(WORKFLOW)
    assert BATS_WORKFLOW_CONTRACT.is_file(), (
        f"tools-shard workflow detector missing: {BATS_WORKFLOW_CONTRACT}"
    )
    assert BATS_WORKFLOW_CONTRACT.read_bytes().strip(), (
        "tools-shard workflow detector is empty"
    )
    bats_steps = [
        block for block in _step_blocks(workflow)
        if block[0] == "      - name: Run bats tests"
    ]
    assert bats_steps == [(
        "      - name: Run bats tests",
        "        if: matrix.shard == 'tools'",
        "        run: bats guard/tests/*.bats",
    )], (
        "the independent Bats workflow detector must remain reachable from tools"
    )


def test_pytest_steps_are_gated_to_their_own_shards() -> None:
    workflow = _read(WORKFLOW)
    release_steps = [
        block for block in _step_blocks(workflow)
        if block[0] == "      - name: Run Python tests (release shard)"
    ]
    assert release_steps == [(
        "      - name: Run Python tests (release shard)",
        "        if: matrix.shard == 'pytest-release'",
        (
            "        run: python3 -m pytest "
            "bin/tests/test_add_failure_mode_release.py -n 3 --dist=load "
            "--max-worker-restart=0 -vv --durations=25"
        ),
    )]

    rest_steps = [
        block for block in _step_blocks(workflow)
        if block[0] == "      - name: Run Python tests (remaining shard)"
    ]
    assert rest_steps == [(
        "      - name: Run Python tests (remaining shard)",
        "        if: matrix.shard == 'pytest-rest'",
        (
            "        run: python3 -m pytest guard/tests/ pipeline/tests/ "
            "bin/tests/ --ignore=bin/tests/test_add_failure_mode_release.py "
            "-q --durations=25"
        ),
    )]


def test_matrix_timeouts_render_to_safety_bounds() -> None:
    workflow = _read(WORKFLOW)
    timeout_lines = [
        line for line in workflow.splitlines()
        if line.strip().startswith("timeout-minutes:")
    ]
    assert len(timeout_lines) == 1, "guard.yml must define exactly one job timeout"
    expression = timeout_lines[0].split(":", 1)[1].strip()
    assert {
        shard: _render_matrix_timeout(expression, shard)
        for shard in ("tools", "pytest-release", "pytest-rest")
    } == {"tools": 15, "pytest-release": 60, "pytest-rest": 30}


def test_catalog_guard_runs_only_the_committed_offline_l2_replay() -> None:
    workflow_bytes = WORKFLOW.read_bytes()
    # Deliberately pin the full manifest: any future workflow edit must receive
    # review and update this test, even if an evasion preserves surface tokens.
    assert hashlib.sha256(workflow_bytes).hexdigest() == INTENDED_WORKFLOW_SHA256
    workflow = workflow_bytes.decode()

    assert re.search(r"(?m)^  guard:\n    name: guard$", workflow)
    shards = ["pytest-release", "pytest-rest", "tools"]
    assert f"        shard: [{', '.join(shards)}]" in workflow
    required_checks = ",".join(f"guard ({shard})" for shard in shards)
    assert f'REQUIRED_CSV="{required_checks}"' in _read(REQUIRE_REAL_CI), (
        "require-real-ci.sh must consume GitHub's exact matrix check names; "
        "the unsuffixed job name is not a reported check"
    )
    timeout = (
        "    timeout-minutes: ${{ matrix.shard == 'tools' && 15 || "
        "matrix.shard == 'pytest-release' && 60 || 30 }}"
    )
    assert workflow.count(timeout) == 1, (
        "tools, pytest-release, and pytest-rest must time out at 15, 60, and "
        "30 minutes respectively"
    )

    parser_steps = [
        block for block in _step_blocks(workflow)
        if block[0] == "      - name: Set up parser runtime"
    ]
    assert parser_steps == [(
        "      - name: Set up parser runtime",
        "        if: matrix.shard != 'pytest-release'",
        "        uses: actions/setup-node@v4",
        "        with:",
        "          node-version: 24.11.0",
    )], (
        "pytest-rest runs JavaScript parser tests against Node's internal "
        "Acorn and must receive the same pinned parser runtime as tools"
    )

    dependency_steps = [
        block for block in _step_blocks(workflow)
        if block[0] == "      - name: Install Python dependencies"
    ]
    assert dependency_steps == [(
        "      - name: Install Python dependencies",
        "        run: python3 -m pip install numpy pytest pytest-xdist==3.8.0",
    )]

    release = (
        "python3 -m pytest bin/tests/test_add_failure_mode_release.py "
        "-n 3 --dist=load --max-worker-restart=0 -vv --durations=25"
    )
    remainder = (
        "python3 -m pytest guard/tests/ pipeline/tests/ bin/tests/ "
        "--ignore=bin/tests/test_add_failure_mode_release.py -q --durations=25"
    )
    assert workflow.count(release) == 1
    assert workflow.count(remainder) == 1
    assert workflow.count("pytest-xdist==3.8.0") == 1
    assert workflow.count(" -n 3 ") == 1

    headers = [block[0] for block in _step_blocks(workflow)]
    assert headers == [
        "      - uses: actions/checkout@v4",
        "      - name: Validate workflow shard contract",
        "      - name: Set up parser runtime",
        "      - name: Set up Bats parser runtime",
        "      - name: Set up virtualenv",
        "      - name: Install Python dependencies",
        "      - name: Report parser dependencies",
        "      - name: Validate canonical catalog",
        "      - name: Run Python tests (release shard)",
        "      - name: Run Python tests (remaining shard)",
        "      - name: Replay committed L2 offline",
        "      - name: Verify recall baselines against the committed partition",
        "      - name: Run bats tests",
        "      - name: Run bin/ tool bats tests (require-real-ci, land)",
        "      - name: Reconcile L1 corpus (declared reduced check)",
        "      - name: Validate L1 schema",
        "      - name: Verify enforcement",
    ]

    replay_steps = [
        block for block in _step_blocks(workflow)
        if block[0] == "      - name: Replay committed L2 offline"
    ]
    assert replay_steps == [(
        "      - name: Replay committed L2 offline",
        "        if: matrix.shard == 'tools'",
        "        run: python3 pipeline/replay_l2.py",
    )]

    python_release = workflow.index("      - name: Run Python tests (release shard)\n")
    python_rest = workflow.index("      - name: Run Python tests (remaining shard)\n")
    replay = workflow.index("      - name: Replay committed L2 offline\n")
    bats = workflow.index("      - name: Run bats tests\n")
    validation = workflow.index("      - name: Reconcile L1 corpus")
    assert python_release < python_rest < replay < bats < validation

    forbidden = {
        "pipeline/cluster.py",
        "pipeline.cluster",
        "pipeline/capture_embedding_snapshot.py",
        "capture_embedding_snapshot.py",
        "pipeline.capture_embedding_snapshot",
        "capture_embedding_snapshot",
        "curl",
        "wget",
        "/v1/embeddings",
        "/api/embeddings",
        "embedding HTTP",
    }
    lowered_workflow = workflow.lower()
    assert not [token for token in sorted(forbidden) if token.lower() in lowered_workflow]


def test_catalog_guard_push_is_scoped_to_main_only() -> None:
    """Unfiltered `on.push` duplicates every PR run (hindsight#123).

    Merge gating reads the PR's statusCheckRollup, so pull_request runs are
    what actually gate a merge. Scoping push to main loses no gating coverage.
    The push trigger itself must remain — main still needs post-merge coverage.
    """
    on_block = _top_level_block(_read(WORKFLOW), "on")
    assert re.search(r"(?m)^  push:\n    branches:\s*\[main\]\s*$", on_block), (
        "guard.yml on.push must be scoped to main; an unfiltered push "
        "duplicates every pull_request run on the same commit"
    )
    assert re.search(r"(?m)^  pull_request:\s*$", on_block), (
        "guard.yml must keep on.pull_request — that is the merge gate"
    )
    assert re.search(r"(?m)^  push:\n  [A-Za-z]", on_block) is None, (
        "guard.yml still has an unfiltered on.push (no branches child)"
    )


def test_catalog_guard_cancels_superseded_runs() -> None:
    """Without concurrency, a superseded push occupies the runner (hindsight#123).

    Cancellation is correct on PR branches. It is not correct on main: a
    rapid sequence of merges would cancel the guard run for an already-merged
    commit, leaving that SHA with no completed result and nothing that will
    ever produce one. Pin the exact expression so a bare `true` cannot pass.
    """
    block = _top_level_block(_read(WORKFLOW), "concurrency")
    assert "${{ github.workflow }}-${{ github.ref }}" in block, (
        "concurrency.group must be keyed on the workflow and the ref"
    )
    # Discriminate: a bare `true` cancels main and must not satisfy this pin.
    assert re.search(r"(?m)^  cancel-in-progress:\s*true\s*$", block) is None, (
        "concurrency.cancel-in-progress must exempt main; a bare true cancels "
        "the guard run for an already-merged commit"
    )
    assert re.search(
        r"(?m)^  cancel-in-progress:\s*"
        r"\$\{\{ github\.ref != 'refs/heads/main' \}\}\s*$",
        block,
    ), (
        "concurrency.cancel-in-progress must be "
        "${{ github.ref != 'refs/heads/main' }} so superseded PR runs die "
        "and main runs are the record for a landed commit"
    )


# ── what CI's reconcile step actually covers ─────────────────────────────────

def test_ci_reconciles_a_named_proper_subset_of_the_corpus() -> None:
    workflow = _read(WORKFLOW)
    slugs = _enumerable_slugs()
    commands = _reconcile_commands(workflow)
    assert commands, "guard.yml no longer reconciles L1 at all"

    scoped: set[str] = set()
    unscoped: list[str] = []
    for command in commands:
        found = _scoped_sources(command)
        if found:
            scoped.update(found)
        else:
            unscoped.append(command)

    unknown = sorted(scoped - slugs)
    assert not unknown, (
        f"guard.yml scopes reconcile to unknown source(s) {unknown}; the "
        "reconciler exits 2 on those, so CI would fail for the wrong reason."
    )
    # Today CI is deliberately reduced. If that ever changes, this assertion is
    # what tells the author that the comment audit below has loosened too.
    assert not unscoped, (
        "guard.yml now runs an unscoped reconcile; re-read the comment audit "
        "tests below, which relax on their own when this is true."
    )
    assert scoped, "guard.yml reconciles nothing"
    assert scoped < slugs, (
        "CI now covers every source; the 'not checked in CI' comments this "
        "suite requires are no longer true and must be rewritten."
    )


def _assert_comment_tells_the_truth_about_ci(
    label: str, block: str, ci_scoped: set[str], slugs: set[str]
) -> None:
    unverified = sorted(slugs - ci_scoped)
    assert unverified, "nothing to audit: CI covers every source"
    sentences = _sentences(block)

    assert _CI.search(block), (
        f"{label}: the comment above the scoped reconcile never mentions CI, so "
        "it cannot tell a reader what the CI path does and does not cover."
    )

    for slug in sorted(ci_scoped):
        assert slug in block, (
            f"{label}: the comment must name the source CI actually reconciles "
            f"({slug}); a reader cannot check a scope that is not written down."
        )

    for slug in unverified:
        carriers = [s for s in sentences if slug in s]
        assert carriers, (
            f"{label}: the comment does not name {slug}, which CI never "
            "verifies. 'four sibling repos' is not a name a reader can act on."
        )
        assert any(_NEGATION.search(s) for s in carriers), (
            f"{label}: every sentence naming {slug} reads as a positive claim. "
            "A source CI does not verify must be stated as NOT verified."
        )

    for sentence in sentences:
        if not _CI.search(sentence):
            continue
        overclaims = [t for t in _OVERCLAIM_TOKENS if t in sentence.lower()]
        if not overclaims:
            continue
        assert _NEGATION.search(sentence), (
            f"{label}: this comment sentence asserts CI performs a "
            f"{overclaims[0]!r} check that guard.yml does not run -- "
            f"{sentence!r}. Documentation may not certify what it never "
            "compared."
        )


def _ci_scoped_sources() -> set[str]:
    return {s for c in _reconcile_commands(_read(WORKFLOW)) for s in _scoped_sources(c)}


def test_ci_reconcile_step_names_the_sources_it_cannot_verify() -> None:
    block = _preceding_comment_block(WORKFLOW, "reconcile_l1.py")
    _assert_comment_tells_the_truth_about_ci(
        "guard.yml", block, _ci_scoped_sources(), _enumerable_slugs()
    )


def test_pre_commit_comment_matches_what_ci_really_checks() -> None:
    block = _preceding_comment_block(PRE_COMMIT, "reconcile_l1.py")
    _assert_comment_tells_the_truth_about_ci(
        ".githooks/pre-commit", block, _ci_scoped_sources(), _enumerable_slugs()
    )


def test_add_failure_mode_comment_matches_what_ci_really_checks() -> None:
    block = _preceding_comment_block(ADD_TOOL, "reconcile_l1.py")
    _assert_comment_tells_the_truth_about_ci(
        "bin/add-failure-mode.sh", block, _ci_scoped_sources(), _enumerable_slugs()
    )


def test_every_call_site_names_only_slugs_the_reconciler_knows() -> None:
    """A typo'd source or gate slug exits 2, breaking its caller loudly."""
    slugs = _enumerable_slugs()
    for path in (WORKFLOW, PRE_COMMIT, ADD_TOOL):
        lines = _read(path).splitlines()
        idx = next(
            i for i, line in enumerate(lines)
            if "reconcile_l1.py" in line and not line.strip().startswith("#")
        )
        # Follow shell line continuations so the scoping flags are not missed.
        command = lines[idx].strip()
        j = idx
        while command.endswith("\\") and j + 1 < len(lines):
            j += 1
            command = command[:-1] + " " + lines[j].strip()
        named = _scoped_sources(command)
        if path == ADD_TOOL:
            assert not named, (
                f"{path}: the per-write path must report every source, not scope it"
            )
            named = _gated_sources(command)
            assert named, f"{path}: reconcile invocation carries no --gate"
        else:
            assert named, f"{path}: reconcile invocation carries no --source scoping"
        unknown = sorted(set(named) - slugs)
        assert not unknown, f"{path}: unknown reconcile slug(s) {unknown}"
