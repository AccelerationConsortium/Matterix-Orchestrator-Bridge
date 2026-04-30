"""SimBackend — wraps a Matterix-like env as ExecutorBackend.

Two env implementations live here:

  * `RealMatterixEnv` — gated `matterix_sm` import. Constructed via
    `make_real_env()`; raises `SimRuntimeUnavailable` if matterix_sm is
    not installed. The actual translation between twin Action and
    Matterix action_dict is centralised in `_action_to_matterix_dict`
    so a single change updates both demos and tests once Matterix obs
    shape is calibrated against the real runtime (see findings.md A2).

  * `FakeMatterixEnv` — deterministic in-process env that satisfies the
    same `MatterixEnvLike` protocol. Used by demos and unit tests since
    Matterix runtime is deferred. Models: ee pose, gripper state, the
    grasped object's relative pose, and a single AABB collision check
    against the optical-table no-go region (used by the Day 6-7 safety
    demo's PhysicalInfeasibility case).

The boundary at `MatterixEnvLike` is what makes the runtime path
swappable later without touching SimBackend or any caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from twin_core.errors import PhysicalInfeasibility
from twin_core.schemas import Action, Observation, Pose


class SimRuntimeUnavailable(RuntimeError):
    """Raised when matterix_sm runtime is requested but not importable."""


class MatterixEnvLike(Protocol):
    """The minimal Matterix-shaped env contract SimBackend depends on."""

    def reset(self) -> dict[str, Any]: ...

    def step(self, action_dict: dict[str, Any]) -> dict[str, Any]: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Fake env — used wherever Matterix runtime is not available
# ---------------------------------------------------------------------------


@dataclass
class _GraspedObject:
    """Tracks an object the gripper is currently holding."""

    asset_id: str
    relative_offset: tuple[float, float, float]


@dataclass
class FakeMatterixEnv:
    """In-process simulator that mimics Matterix's obs/action_dict shape.

    Deterministic, synchronous, dependency-free. Knows enough physics to
    drive the demos: ee follows target_pose; gripper opens/closes; an
    object inside the grasp radius gets attached and follows the ee.
    A configurable AABB no-go region triggers a PhysicalInfeasibility
    exception (used by the Day 6-7 safety demo).
    """

    initial_ee_pose: Pose = field(
        default_factory=lambda: Pose(position=(0.0, 0.0, 0.5))
    )
    object_world_poses: dict[str, Pose] = field(
        default_factory=lambda: {"beaker_500ml": Pose(position=(0.4, 0.0, 0.10))}
    )
    grasp_radius: float = 0.03
    nogo_aabb: tuple[tuple[float, float, float], tuple[float, float, float]] | None = (
        None
    )

    _ee_pose: Pose = field(init=False)
    _gripper_closed: bool = field(init=False, default=False)
    _grasped: _GraspedObject | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._ee_pose = self.initial_ee_pose

    def reset(self) -> dict[str, Any]:
        self._ee_pose = self.initial_ee_pose
        self._gripper_closed = False
        self._grasped = None
        return self._observation_dict()

    def step(self, action_dict: dict[str, Any]) -> dict[str, Any]:
        target = action_dict.get("target_pose")
        if target is not None:
            new_pose = Pose(position=tuple(target["position"]))  # type: ignore[arg-type]
            self._check_collision(new_pose)
            self._ee_pose = new_pose
            if self._grasped is not None:
                # Carried object follows the ee with its capture offset.
                obj = self._grasped
                self.object_world_poses[obj.asset_id] = Pose(
                    position=(
                        new_pose.position[0] + obj.relative_offset[0],
                        new_pose.position[1] + obj.relative_offset[1],
                        new_pose.position[2] + obj.relative_offset[2],
                    )
                )

        gripper = action_dict.get("gripper_command")
        if gripper == "close":
            self._gripper_closed = True
            self._maybe_grasp()
        elif gripper == "open":
            self._gripper_closed = False
            self._grasped = None

        return self._observation_dict()

    def close(self) -> None:
        return None

    # -- internals -----------------------------------------------------

    def _check_collision(self, pose: Pose) -> None:
        if self.nogo_aabb is None:
            return
        (x0, y0, z0), (x1, y1, z1) = self.nogo_aabb
        x, y, z = pose.position
        if x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1:
            raise PhysicalInfeasibility(
                f"ee target {pose.position} inside no-go region "
                f"{self.nogo_aabb}"
            )

    def _maybe_grasp(self) -> None:
        ex, ey, ez = self._ee_pose.position
        for asset_id, pose in self.object_world_poses.items():
            ox, oy, oz = pose.position
            dist = ((ex - ox) ** 2 + (ey - oy) ** 2 + (ez - oz) ** 2) ** 0.5
            if dist <= self.grasp_radius:
                self._grasped = _GraspedObject(
                    asset_id=asset_id,
                    relative_offset=(ox - ex, oy - ey, oz - ez),
                )
                return

    def _observation_dict(self) -> dict[str, Any]:
        return {
            "ee_pose": {
                "position": list(self._ee_pose.position),
                "orientation": list(self._ee_pose.orientation),
            },
            "gripper_closed": self._gripper_closed,
            "gripper_width": 0.0 if self._gripper_closed else 0.085,
            "object_world_poses": {
                asset: {"position": list(p.position)}
                for asset, p in self.object_world_poses.items()
            },
        }


# ---------------------------------------------------------------------------
# Real env — gated import of matterix_sm; documents the wiring
# ---------------------------------------------------------------------------


def make_real_env(
    task: str = "Matterix-Test-Beaker-Lift-Franka-v1",
    *,
    num_envs: int = 1,
    device: str = "cuda",
    use_fabric: bool = True,
    headless: bool = True,
):
    """Construct a real Matterix env via gym.make + Isaac Lab parse_env_cfg.

    Mirrors `Matterix/scripts/run_workflow.py`. Returns the *unwrapped*
    gymnasium env. Caller is responsible for invoking `env.reset()`.

    Note: the returned env does NOT satisfy `MatterixEnvLike` directly —
    real Matterix observations are nested torch-tensor dicts and actions
    are torch tensors produced by `matterix_sm.StateMachine.step(obs)`.
    Use `MatterixWorkflowRunner` (see `twin_sim.real_runner`) to drive
    this env at the workflow level. SimBackend's per-step path is for
    `FakeMatterixEnv` only.
    """
    try:
        import gymnasium as gym  # type: ignore[import-not-found]
        import matterix_tasks  # type: ignore[import-not-found]  # noqa: F401  # registers tasks
        from isaaclab_tasks.utils.parse_cfg import (  # type: ignore[import-not-found]
            parse_env_cfg,
        )
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SimRuntimeUnavailable(
            "Matterix runtime missing — install matterix_tasks + isaaclab + "
            "gymnasium per the Matterix README to enable the real sim path"
        ) from exc

    # Note: AppLauncher / SimulationApp must already be running before
    # gym.make() is called for an Isaac Lab task. This factory does NOT
    # launch Omniverse — the caller is expected to have done so (see
    # examples/06_run_real_matterix.py for the canonical launcher).
    env_cfg = parse_env_cfg(
        task,
        device=device,
        num_envs=num_envs,
        use_fabric=use_fabric,
    )
    env = gym.make(task, cfg=env_cfg).unwrapped
    return env


# ---------------------------------------------------------------------------
# SimBackend — wraps any MatterixEnvLike
# ---------------------------------------------------------------------------


class SimBackend:
    """ExecutorBackend wrapping a Matterix-shaped env."""

    def __init__(self, env: MatterixEnvLike) -> None:
        self._env = env

    def reset(self) -> Observation:
        return _matterix_obs_to_observation(self._env.reset())

    def step(self, action: Action) -> Observation:
        action_dict = _action_to_matterix_dict(action)
        return _matterix_obs_to_observation(self._env.step(action_dict))

    def close(self) -> None:
        self._env.close()


def _action_to_matterix_dict(action: Action) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if action.target_pose is not None:
        out["target_pose"] = {
            "position": list(action.target_pose.position),
            "orientation": list(action.target_pose.orientation),
        }
    if action.gripper_command is not None:
        out["gripper_command"] = action.gripper_command
    if action.extras:
        out["extras"] = action.extras
    return out


def _matterix_obs_to_observation(obs_dict: dict[str, Any]) -> Observation:
    ee_raw = obs_dict["ee_pose"]
    ee_pose = Pose(
        position=tuple(ee_raw["position"]),
        orientation=tuple(ee_raw.get("orientation", (0.0, 0.0, 0.0, 1.0))),
    )
    asset_frames: dict[str, dict[str, Pose]] = {}
    for asset_id, pose_dict in obs_dict.get("object_world_poses", {}).items():
        asset_frames[asset_id] = {
            "world": Pose(position=tuple(pose_dict["position"]))
        }
    return Observation(
        ee_pose=ee_pose,
        gripper_closed=bool(obs_dict["gripper_closed"]),
        gripper_width=obs_dict.get("gripper_width"),
        asset_frames=asset_frames,
        extras={
            k: v
            for k, v in obs_dict.items()
            if k not in {"ee_pose", "gripper_closed", "gripper_width", "object_world_poses"}
        },
    )
