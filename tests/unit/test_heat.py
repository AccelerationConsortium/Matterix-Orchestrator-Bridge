"""Unit tests for the Heat UnitOperation + 'heat' primitive."""

from __future__ import annotations

import pytest

from twin_core import (
    Heat,
    MiniOrchestrator,
    PickAndPlace,
    SchemaError,
    WorkflowStep,
    lower_workflow,
    operation_to_workflow,
    preflight,
)
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService


def _frames() -> StaticFrameService:
    return StaticFrameService.default_for_demo()


def test_heat_to_workflow_yields_one_step() -> None:
    op = Heat(asset_name="hotplate", target_temperature_k=373.15, duration_s=10.0)
    wf = operation_to_workflow(op)
    assert len(wf) == 1
    assert wf[0].primitive == "heat"
    assert wf[0].target_object == "hotplate"
    assert wf[0].extras["target_temperature_k"] == 373.15
    assert wf[0].extras["duration_s"] == 10.0


def test_heat_lowering_is_single_no_op_action_with_extras() -> None:
    wf = operation_to_workflow(
        Heat(asset_name="hotplate", target_temperature_k=300.0, duration_s=2.0)
    )
    actions = lower_workflow(wf, _frames())
    assert len(actions) == 1
    a = actions[0]
    assert a.target_pose is None
    assert a.gripper_command is None
    assert a.extras["phase"] == "heat"
    assert a.extras["asset_name"] == "hotplate"
    assert a.extras["target_temperature_k"] == 300.0
    assert a.extras["duration_s"] == 2.0


def test_heat_missing_extras_raises_schema() -> None:
    bad = WorkflowStep(primitive="heat", target_object="hotplate")
    with pytest.raises(SchemaError):
        lower_workflow([bad], _frames())


def test_heat_missing_asset_raises_schema_via_preflight() -> None:
    bad = WorkflowStep(
        primitive="heat",
        extras={"target_temperature_k": 300.0, "duration_s": 1.0},
    )
    result = preflight([bad], _frames())
    assert not result.ok
    assert result.error_class == "SchemaError"


def test_combined_pickandplace_then_heat_runs_through_orchestrator() -> None:
    orch = MiniOrchestrator(
        backend=SimBackend(FakeMatterixEnv()),
        frames=_frames(),
    )
    plan = [
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="hotplate",
            target_frame="place",
        ),
        Heat(asset_name="hotplate", target_temperature_k=353.15, duration_s=3.0),
    ]
    record = orch.run(plan)
    assert record.completed
    # PickAndPlace = 8 actions, Heat = 1 no-op action.
    assert len(record.steps) == 9
    # Last step must be the heat no-op.
    last = record.steps[-1]
    assert last.action.extras["phase"] == "heat"
    assert last.operation_index == 1


def test_preflight_passes_combined_plan() -> None:
    plan_workflow = []
    for op in [
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="hotplate",
            target_frame="place",
        ),
        Heat(asset_name="hotplate", target_temperature_k=353.15, duration_s=3.0),
    ]:
        plan_workflow.extend(operation_to_workflow(op))
    assert preflight(plan_workflow, _frames()).ok


def test_place_at_accepts_place_frame_per_matterix_convention() -> None:
    """Schema policy: place_at must allow Matterix's canonical 'place'
    frame (PlaceObjectCfg uses pre_place + place internally)."""
    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="hotplate",
            target_frame="place",
        )
    )
    assert preflight(workflow, _frames()).ok
