"""Schemas for observation, action, and workflow primitives.

v1 — calibrated against the Matterix shape documented in plan §6.1
without direct introspection (deferred per docs/findings.md A1/A2).
Fields beyond v0 are all Optional so downstream code can ignore them
until the runtime inspection produces real values.

Shape:
  - low-level Action (target_pose + gripper_command) — what a backend
    consumes per `step()`
  - WorkflowStep (named primitive: pick_object / move / place) — what a
    PickAndPlace `operation_to_workflow()` emits, closer to Matterix
    WorkflowDict
  - Observation — pose + gripper boolean is mandatory; gripper_width,
    joint_positions, and per-asset frames are Optional escape hatches
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GripperCommand = Literal["open", "close"]
PrimitiveName = Literal["pick_object", "move", "place_at"]


class Pose(BaseModel):
    """6-DOF pose. Position in meters, orientation as quaternion (xyzw)."""

    model_config = ConfigDict(frozen=True)

    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    frame_id: str | None = None  # None means world frame


class Observation(BaseModel):
    """Backend observation after a step.

    Mandatory: ee_pose, gripper_closed.
    Optional: gripper_width (Robotiq85 ~ 0..0.085 m), joint_positions
    (Franka 7-DOF), per-asset named frames (e.g. {"beaker_500ml":
    {"grasp": Pose(...)}}). All Optional — calibration may add more.
    """

    model_config = ConfigDict(frozen=True)

    ee_pose: Pose
    gripper_closed: bool
    gripper_width: float | None = None
    joint_positions: tuple[float, ...] | None = None
    asset_frames: dict[str, dict[str, Pose]] = Field(default_factory=dict)
    extras: dict[str, object] = Field(default_factory=dict)


class Action(BaseModel):
    """Low-level backend action (one step).

    A WorkflowStep is decomposed into one or more Action instances by
    the backend; the backend is what knows how to translate a primitive
    like "pick_object" into ee-pose + gripper sequence.
    """

    model_config = ConfigDict(frozen=True)

    target_pose: Pose | None = None
    gripper_command: GripperCommand | None = None
    extras: dict[str, object] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    """A named primitive — the unit Matterix's WorkflowDict speaks in.

    Fields are intentionally a superset; not every primitive uses every
    field. `pick_object` uses `target_object` + `target_frame`; `move`
    uses `target_pose`; `place_at` uses both.
    """

    model_config = ConfigDict(frozen=True)

    primitive: PrimitiveName
    target_object: str | None = None
    target_frame: str | None = None
    target_pose: Pose | None = None
    extras: dict[str, object] = Field(default_factory=dict)
