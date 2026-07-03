"""Tests for adapting fixed SDL1Chem/Uoroboros workflow JSON."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from twin_core import (
    Sdl1ChemAdapterError,
    load_sdl1chem_workflow_json,
)


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "workflows" / "sdl1chem_robot_loop_excerpt.json"
SCRIPT = ROOT / "examples" / "inspect_sdl1chem_adapter.py"


def test_sdl1chem_adapter_maps_supported_uo_paths() -> None:
    mapping = load_sdl1chem_workflow_json(EXAMPLE)

    assert mapping.name == "sdl1chem-robot-loop-excerpt"
    assert [block.uo_path for block in mapping.mapped_blocks] == [
        "echem-uos:flush_tool_transfer",
        "echem-uos:insert_electrode",
        "echem-uos:remove_electrode",
    ]
    assert [op.operation_type for op in mapping.loaded_workflow.operations] == [
        "pick_and_place",
        "pick_and_place",
        "pick_and_place",
    ]
    assert [step.primitive for step in mapping.to_workflow_steps()] == [
        "pick_object",
        "place_at",
        "pick_object",
        "place_at",
        "pick_object",
        "place_at",
    ]
    assert [block.uo_path for block in mapping.unsupported_blocks] == [
        "echem-uos:setup_experiment",
        "echem-uos:write_loop_results",
    ]


def test_sdl1chem_adapter_allows_external_mapping_rules() -> None:
    workflow = {
        "name": "custom",
        "blocks": [
            {
                "id": "b_heat",
                "uo_path": "echem-uos:heat_plate",
            }
        ],
    }

    mapping = load_sdl1chem_workflow_json(
        workflow,
        mapping_rules={
            "echem-uos:heat_plate": {
                "operation": "heat",
                "params": {
                    "asset_name": "ika_plate",
                    "target_temperature_k": 373.15,
                    "duration_s": 5,
                },
            }
        },
    )

    assert mapping.unsupported_blocks == []
    assert [step.primitive for step in mapping.to_workflow_steps()] == ["heat"]
    assert mapping.to_workflow_steps()[0].extras["target_temperature_k"] == 373.15


def test_sdl1chem_adapter_strict_mode_reports_unsupported_blocks() -> None:
    with pytest.raises(Sdl1ChemAdapterError, match="setup_experiment"):
        load_sdl1chem_workflow_json(EXAMPLE, fail_on_unsupported=True)


def test_sdl1chem_adapter_requires_blocks() -> None:
    with pytest.raises(Sdl1ChemAdapterError, match="blocks"):
        load_sdl1chem_workflow_json({"name": "empty", "blocks": []})


def test_sdl1chem_adapter_accepts_path(tmp_path) -> None:
    path = tmp_path / "workflow.json"
    path.write_text(EXAMPLE.read_text())

    mapping = load_sdl1chem_workflow_json(path)
    assert len(mapping.mapped_blocks) == 3


def test_inspect_sdl1chem_adapter_script() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(EXAMPLE)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "SDL1Chem block -> UnitOperation -> WorkflowStep" in result.stdout
    assert "echem-uos:insert_electrode -> PickAndPlace" in result.stdout
    assert "Unsupported UO blocks: 2" in result.stdout


def test_sdl1chem_adapter_rejects_invalid_json(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(["not", "object"]))

    with pytest.raises(Sdl1ChemAdapterError, match="root"):
        load_sdl1chem_workflow_json(path)
