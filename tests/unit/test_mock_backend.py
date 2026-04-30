"""Unit tests for MockBackend - protocol compliance + state transitions."""

from __future__ import annotations

from twin_core import Action, Pose
from twin_core.mock_backend import MockBackend


def test_reset_clears_recorded_actions() -> None:
    backend = MockBackend()
    backend.step(Action(gripper_command="close"))
    assert len(backend.actions) == 1
    backend.reset()
    assert backend.actions == []


def test_gripper_open_close_toggle() -> None:
    backend = MockBackend()
    backend.reset()
    obs = backend.step(Action(gripper_command="close"))
    assert obs.gripper_closed is True
    obs = backend.step(Action(gripper_command="open"))
    assert obs.gripper_closed is False


def test_target_pose_updates_ee_pose() -> None:
    backend = MockBackend()
    backend.reset()
    target = Pose(position=(0.5, 0.1, 0.3))
    obs = backend.step(Action(target_pose=target))
    assert obs.ee_pose == target


def test_no_op_action_preserves_state() -> None:
    backend = MockBackend()
    obs_before = backend.reset()
    obs_after = backend.step(Action())
    assert obs_after.ee_pose == obs_before.ee_pose
    assert obs_after.gripper_closed == obs_before.gripper_closed


def test_observations_are_frozen() -> None:
    backend = MockBackend()
    obs = backend.reset()
    # Pydantic frozen=True → assignment raises ValidationError
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        obs.ee_pose = Pose(position=(0.0, 0.0, 0.0))  # type: ignore[misc]
