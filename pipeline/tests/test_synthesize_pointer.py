"""Regression coverage for tiered pointer synthesis."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "synthesize-pointer.py"
SPEC = importlib.util.spec_from_file_location("hindsight_synthesize_pointer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_high_tier_member_absorbed_into_capped_cluster_remains_visible(tmp_path: Path, monkeypatch) -> None:
    """FM-305 must remain a HIGH.md row even when its cluster selects FM-363."""
    catalog = tmp_path / "failure-modes.md"
    catalog.write_text(
        "\n".join(
            [
                "| FM-305 | absorbed HIGH singleton | check FM-305 | Judgment |",
                "| FM-363 | selected cluster representative | check FM-363 | Judgment |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    criticality = tmp_path / "criticality.jsonl"
    criticality.write_text(
        "\n".join(
            [
                json.dumps({"fm_id": "FM-305", "tier": "HIGH", "generality": "LOCAL"}),
                json.dumps({"fm_id": "FM-363", "tier": "HIGH", "generality": "BROAD"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    clusters = tmp_path / "clusters.jsonl"
    clusters.write_text(
        json.dumps(
            {
                "cluster_id": "c-capped",
                "members": ["hc-FM-305", "hc-FM-363"],
                "representative": "hc-FM-363",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    pointer = tmp_path / "POINTER.md"
    high = tmp_path / "HIGH.md"
    monkeypatch.setattr(MODULE, "CATALOG", catalog)
    monkeypatch.setattr(MODULE, "CRITICALITY", criticality)
    if hasattr(MODULE, "CLUSTERS"):
        monkeypatch.setattr(MODULE, "CLUSTERS", clusters)
    monkeypatch.setattr(MODULE, "POINTER_OUT", pointer)
    monkeypatch.setattr(MODULE, "HIGH_OUT", high)

    assert MODULE.main() == 0
    assert "- **FM-305** [LOCAL] check FM-305" in high.read_text(encoding="utf-8")
