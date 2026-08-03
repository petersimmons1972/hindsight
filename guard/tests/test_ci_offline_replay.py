from pathlib import Path


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "guard.yml"


def _step_blocks(workflow: str) -> list[tuple[str, ...]]:
    """Extract job step blocks at the workflow's six-space list indentation."""
    blocks: list[list[str]] = []
    for line in workflow.splitlines():
        if line.startswith("      - "):
            blocks.append([line])
        elif blocks and (line.startswith("        ") or not line.strip()):
            blocks[-1].append(line)
    return [tuple(block) for block in blocks]


def test_catalog_guard_runs_only_the_committed_offline_l2_replay() -> None:
    workflow = WORKFLOW.read_text()

    replay_steps = [
        block for block in _step_blocks(workflow)
        if block[0] == "      - name: Replay committed L2 offline"
    ]
    assert replay_steps == [(
        "      - name: Replay committed L2 offline",
        "        run: python3 pipeline/replay_l2.py",
    )]

    python_tests = workflow.index("      - name: Run Python tests\n")
    replay = workflow.index("      - name: Replay committed L2 offline\n")
    bats = workflow.index("      - name: Run bats tests\n")
    validation = workflow.index("      - name: Reconcile L1 corpus")
    assert python_tests < replay < bats < validation

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
