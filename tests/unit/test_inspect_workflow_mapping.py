"""Tests for the dry workflow mapping inspector."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples" / "inspect_workflow_mapping.py"
WORKFLOW_JSON = ROOT / "examples" / "workflows" / "matterix_heat_workflow.json"


def test_inspect_workflow_mapping_prints_expected_chain() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(WORKFLOW_JSON)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "workflow JSON -> UnitOperation -> WorkflowStep -> matterix_sm Cfg" in result.stdout
    assert "pick_and_place -> PickAndPlace" in result.stdout
    assert "heat -> Heat" in result.stdout
    assert "WorkflowStep(pick_object, target=beaker) -> PickObjectCfg" in result.stdout
    assert "WorkflowStep(place_at, target=ika_plate) -> PlaceObjectCfg" in result.stdout
    assert "WorkflowStep(heat, target=ika_plate)" in result.stdout
    assert "Total Matterix cfgs: 5" in result.stdout
