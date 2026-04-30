"""Unit tests for v1 schemas — validates calibration decisions D-001..D-004."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from twin_core import (
    Action,
    Observation,
    PickAndPlace,
    Pose,
    WorkflowStep,
    operation_to_workflow,
)


def test_pose_defaults_to_identity_quaternion() -> None:
    p = Pose(position=(0.0, 0.0, 0.0))
    assert p.orientation == (0.0, 0.0, 0.0, 1.0)
    assert p.frame_id is None


def test_observation_optional_fields_default_none() -> None:
    obs = Observation(ee_pose=Pose(position=(0.0, 0.0, 0.5)), gripper_closed=False)
    assert obs.gripper_width is None
    assert obs.joint_positions is None
    assert obs.asset_frames == {}


def test_observation_accepts_full_v1_payload() -> None:
    obs = Observation(
        ee_pose=Pose(position=(0.0, 0.0, 0.5)),
        gripper_closed=False,
        gripper_width=0.085,
        joint_positions=(0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785),
        asset_frames={"beaker": {"grasp": Pose(position=(0.4, 0.0, 0.1))}},
    )
    assert obs.gripper_width == 0.085
    assert len(obs.joint_positions or ()) == 7
    assert "beaker" in obs.asset_frames


def test_action_gripper_command_is_constrained() -> None:
    Action(gripper_command="open")
    Action(gripper_command="close")
    with pytest.raises(PydanticValidationError):
        Action(gripper_command="grip")  # type: ignore[arg-type]


def test_workflow_step_primitive_is_constrained() -> None:
    WorkflowStep(primitive="pick_object", target_object="beaker", target_frame="grasp")
    with pytest.raises(PydanticValidationError):
        WorkflowStep(primitive="teleport", target_object="beaker")  # type: ignore[arg-type]


def test_pickandplace_to_workflow_yields_two_steps() -> None:
    op = PickAndPlace(
        source_object="beaker",
        source_frame="grasp",
        target_object="table",
        target_frame="dropoff_a1",
    )
    workflow = operation_to_workflow(op)
    assert len(workflow) == 2
    assert workflow[0].primitive == "pick_object"
    assert workflow[0].target_object == "beaker"
    assert workflow[0].target_frame == "grasp"
    assert workflow[1].primitive == "place_at"
    assert workflow[1].target_object == "table"
    assert workflow[1].target_frame == "dropoff_a1"
