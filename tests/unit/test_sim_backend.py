"""Unit tests for FakeMatterixEnv + SimBackend wiring."""

from __future__ import annotations

import pytest

from twin_core import Action, PhysicalInfeasibility, Pose
from twin_sim import FakeMatterixEnv, SimBackend


def test_sim_backend_translates_observation() -> None:
    backend = SimBackend(FakeMatterixEnv())
    obs = backend.reset()
    assert obs.gripper_closed is False
    # FakeMatterixEnv reports gripper_width 0.085 when open.
    assert obs.gripper_width == 0.085
    assert "beaker" in obs.asset_frames


def test_sim_backend_moves_ee_via_action() -> None:
    backend = SimBackend(FakeMatterixEnv())
    backend.reset()
    target = Pose(position=(0.4, 0.0, 0.10))
    obs = backend.step(Action(target_pose=target))
    assert obs.ee_pose.position == (0.4, 0.0, 0.10)


def test_fake_env_grasps_beaker_when_close_and_gripper_closes() -> None:
    backend = SimBackend(FakeMatterixEnv())
    backend.reset()
    # Move ee to grasp pose (where the beaker lives), then close gripper.
    backend.step(Action(target_pose=Pose(position=(0.60, 0.05, 0.10))))
    obs = backend.step(Action(gripper_command="close"))
    assert obs.gripper_closed is True

    # Now move ee — beaker should follow.
    obs = backend.step(Action(target_pose=Pose(position=(0.5, 0.0, 0.30))))
    beaker_world = obs.asset_frames["beaker"]["world"]
    assert beaker_world.position == (0.5, 0.0, 0.30)


def test_fake_env_raises_physical_infeasibility_inside_nogo_aabb() -> None:
    env = FakeMatterixEnv(
        nogo_aabb=((0.50, -0.10, 0.00), (0.70, 0.10, 0.20)),
    )
    backend = SimBackend(env)
    backend.reset()
    with pytest.raises(PhysicalInfeasibility):
        backend.step(Action(target_pose=Pose(position=(0.6, 0.0, 0.10))))


def test_dry_run_returns_ok_for_clean_workflow() -> None:
    from twin_core import PickAndPlace, operation_to_workflow
    from twin_sim import StaticFrameService, dry_run

    backend = SimBackend(FakeMatterixEnv())
    frames = StaticFrameService.default_for_demo()
    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="table",
            target_frame="dropoff_a1",
        )
    )
    result = dry_run(workflow, backend, frames)
    assert result.ok is True
    assert result.reason is None


def test_dry_run_catches_physical_infeasibility() -> None:
    from twin_core import PickAndPlace, operation_to_workflow
    from twin_sim import StaticFrameService, dry_run

    # No-go region covers the dropoff target → place_at hits infeasibility.
    env = FakeMatterixEnv(
        nogo_aabb=((0.55, 0.15, 0.05), (0.65, 0.25, 0.40)),
    )
    backend = SimBackend(env)
    frames = StaticFrameService.default_for_demo()
    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="table",
            target_frame="dropoff_a1",
        )
    )
    result = dry_run(workflow, backend, frames)
    assert result.ok is False
    assert result.error_class == "PhysicalInfeasibility"
    assert result.failed_step_index is not None
