"""Unit tests for bridge workflow JSON loading."""

from __future__ import annotations

import json

import pytest

from twin_core import (
    Heat,
    PickAndPlace,
    WorkflowJsonError,
    load_operations_json,
    load_workflow_steps_json,
)


HEAT_WORKFLOW_JSON = {
    "workflow_name": "matterix-heat-transfer-demo",
    "version": "1.0",
    "operations": [
        {
            "operation_id": "pick_beaker_to_plate",
            "operation": "pick_and_place",
            "params": {
                "source_object": "beaker",
                "source_frame": "grasp",
                "target_object": "ika_plate",
                "target_frame": "place",
            },
        },
        {
            "operation_id": "heat_ika_plate",
            "operation": "heat",
            "params": {
                "asset_name": "ika_plate",
                "target_temperature_k": 373.15,
                "duration_s": 5.0,
            },
        },
    ],
}


def test_load_operations_json_returns_typed_operations() -> None:
    loaded = load_operations_json(HEAT_WORKFLOW_JSON)

    assert loaded.name == "matterix-heat-transfer-demo"
    assert loaded.version == "1.0"
    assert len(loaded.operations) == 2
    assert isinstance(loaded.operations[0].operation, PickAndPlace)
    assert isinstance(loaded.operations[1].operation, Heat)


def test_loaded_workflow_translates_to_workflow_steps() -> None:
    loaded = load_operations_json(HEAT_WORKFLOW_JSON)
    steps = loaded.to_workflow_steps()

    assert [s.primitive for s in steps] == ["pick_object", "place_at", "heat"]
    assert steps[0].target_object == "beaker"
    assert steps[1].target_object == "ika_plate"
    assert steps[2].extras["target_temperature_k"] == 373.15


def test_load_workflow_steps_json_direct_helper() -> None:
    steps = load_workflow_steps_json(HEAT_WORKFLOW_JSON)
    assert len(steps) == 3
    assert steps[-1].primitive == "heat"


def test_load_operations_json_accepts_path(tmp_path) -> None:
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(HEAT_WORKFLOW_JSON))

    loaded = load_operations_json(path)
    assert loaded.operations[0].operation_id == "pick_beaker_to_plate"


def test_unsupported_operation_fails_loudly() -> None:
    bad = {
        "workflow_name": "bad",
        "operations": [{"operation": "centrifuge", "params": {}}],
    }
    with pytest.raises(WorkflowJsonError, match="unsupported operation"):
        load_operations_json(bad)


def test_missing_required_param_reports_operation_index() -> None:
    bad = {
        "workflow_name": "bad",
        "operations": [
            {
                "operation": "heat",
                "params": {"asset_name": "ika_plate", "duration_s": 5.0},
            }
        ],
    }
    with pytest.raises(WorkflowJsonError, match=r"operations\[0\]"):
        load_operations_json(bad)


def test_operations_list_is_required() -> None:
    with pytest.raises(WorkflowJsonError, match="operations"):
        load_operations_json({"workflow_name": "empty"})
