from pathlib import Path
import re


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "guard.yml"


def test_catalog_guard_runs_only_the_committed_offline_l2_replay() -> None:
    workflow = WORKFLOW.read_text()

    replay_steps = re.findall(
        r"^      - name: Replay committed L2 offline\n"
        r"^        run: ([^\n]+)$",
        workflow,
        re.MULTILINE,
    )
    assert replay_steps == ["python3 pipeline/replay_l2.py"]

    python_tests = workflow.index("      - name: Run Python tests\n")
    replay = workflow.index("      - name: Replay committed L2 offline\n")
    bats = workflow.index("      - name: Run bats tests\n")
    validation = workflow.index("      - name: Reconcile L1 corpus")
    assert python_tests < replay < bats < validation

    forbidden = (
        "pipeline/capture_embedding_snapshot.py",
        "pipeline/cluster.py",
        "curl",
        "wget",
        "embedding HTTP",
    )
    assert not [token for token in forbidden if token in workflow]
