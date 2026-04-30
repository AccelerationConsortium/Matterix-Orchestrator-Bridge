"""Unit tests for lower_workflow."""

from __future__ import annotations

import pytest

from twin_core import (
    PickAndPlace,
    SchemaError,
    WorkflowStep,
    lower_workflow,
    operation_to_workflow,
)
from twin_core.errors import FrameNotFound
from twin_sim import StaticFrameService


def _frames() -> StaticFrameService:
    return StaticFrameService.default_for_demo()


def test_lower_pickandplace_emits_eight_actions() -> None:
    op = PickAndPlace(
        source_object="beaker",
        source_frame="grasp",
        target_object="table",
        target_frame="dropoff_a1",
    )
    actions = lower_workflow(operation_to_workflow(op), _frames())
    # 4 actions per primitive (pre, target, gripper, retract) * 2 primitives
    assert len(actions) == 8
    phases = [a.extras["phase"] for a in actions]
    assert phases == [
        "pre_grasp",
        "grasp",
        "close_gripper",
        "post_grasp",
        "pre_dropoff",
        "dropoff",
        "open_gripper",
        "retract",
    ]


def test_lower_unknown_primitive_raises_schema_error() -> None:
    bad = WorkflowStep.model_construct(primitive="teleport")  # bypass validation
    with pytest.raises(SchemaError):
        lower_workflow([bad], _frames())


def test_lower_pick_with_missing_frame_raises_frame_not_found() -> None:
    workflow = [
        WorkflowStep(
            primitive="pick_object",
            target_object="beaker",
            target_frame="non_existent_frame",
        )
    ]
    with pytest.raises(FrameNotFound) as excinfo:
        lower_workflow(workflow, _frames())
    assert excinfo.value.frame_name == "non_existent_frame"


def test_lower_move_requires_target_pose() -> None:
    workflow = [WorkflowStep(primitive="move")]
    with pytest.raises(SchemaError):
        lower_workflow(workflow, _frames())
