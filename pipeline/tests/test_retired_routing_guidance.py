"""Current catalog guidance must not route work through the retired queue."""

import re
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[2] / "catalog" / "failure-modes.md"
RETIRED_INSTRUCTIONS = re.compile(
    r"fleet-dispatch token-rotation runbook|fleet-enqueue\.sh|fleet-consult\.sh|"
    r"fleet-canary\.sh|goes through fleet-dispatch|only Hermes claims|"
    r"Route plan-feedback through a `comment_only` capability|"
    r"token-impl-grok|restart fleet-dispatch|Prioritize #65 to p1|"
    r"ssh codex/hermes socialization|"
    r"`hermes chat` invocation the poller uses"
)


def test_checks_do_not_recommend_retired_dispatch_paths():
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| FM-"):
            continue
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        assert not RETIRED_INSTRUCTIONS.search(fields[-2]), fields[0]


def test_bullets_do_not_recommend_retired_dispatch_paths():
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("- "):
            assert not RETIRED_INSTRUCTIONS.search(line), line[:100]
