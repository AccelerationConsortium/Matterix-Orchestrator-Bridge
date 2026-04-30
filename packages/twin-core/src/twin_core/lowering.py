"""Lower a WorkflowDict (named primitives) into a list of low-level Actions.

Lives in twin-core because both sim and real-stub use the same lowering —
"same plan, two backends" requires it. Each backend may further refine
how an Action becomes its own native action_dict, but the cross-backend
interchange happens at the Action level.

Lowering uses FrameService.lookup() to resolve (asset_id, frame_name)
into world-frame poses. FrameNotFound bubbles up as a ValidationError.
"""

from __future__ import annotations

from twin_core.errors import SchemaError
from twin_core.operations import WorkflowDict
from twin_core.protocols import FrameService
from twin_core.schemas import Action, WorkflowStep


def lower_workflow(workflow: WorkflowDict, frames: FrameService) -> list[Action]:
    """Convert a WorkflowDict into a flat list of Actions, resolving frames."""
    actions: list[Action] = []
    for step in workflow:
        actions.extend(_lower_step(step, frames))
    return actions


def _lower_step(step: WorkflowStep, frames: FrameService) -> list[Action]:
    if step.primitive == "pick_object":
        return _lower_pick(step, frames)
    if step.primitive == "place_at":
        return _lower_place(step, frames)
    if step.primitive == "move":
        return _lower_move(step)
    if step.primitive == "heat":
        return _lower_heat(step)
    raise SchemaError(f"Unknown primitive: {step.primitive!r}")


def _require(value: str | None, what: str, primitive: str) -> str:
    if value is None:
        raise SchemaError(f"primitive {primitive!r} requires {what}")
    return value


def _lower_pick(step: WorkflowStep, frames: FrameService) -> list[Action]:
    asset = _require(step.target_object, "target_object", step.primitive)
    frame = _require(step.target_frame, "target_frame", step.primitive)
    grasp = frames.lookup(asset, frame)
    pre = frames.lookup(asset, "pre_grasp")
    post = frames.lookup(asset, "post_grasp")
    return [
        Action(target_pose=pre, extras={"phase": "pre_grasp"}),
        Action(target_pose=grasp, extras={"phase": "grasp"}),
        Action(gripper_command="close", extras={"phase": "close_gripper"}),
        Action(target_pose=post, extras={"phase": "post_grasp"}),
    ]


def _lower_place(step: WorkflowStep, frames: FrameService) -> list[Action]:
    asset = _require(step.target_object, "target_object", step.primitive)
    frame = _require(step.target_frame, "target_frame", step.primitive)
    drop = frames.lookup(asset, frame)
    pre_drop = frames.lookup(asset, f"pre_{frame}")
    return [
        Action(target_pose=pre_drop, extras={"phase": "pre_dropoff"}),
        Action(target_pose=drop, extras={"phase": "dropoff"}),
        Action(gripper_command="open", extras={"phase": "open_gripper"}),
        Action(target_pose=pre_drop, extras={"phase": "retract"}),
    ]


def _lower_move(step: WorkflowStep) -> list[Action]:
    if step.target_pose is None:
        raise SchemaError("primitive 'move' requires target_pose")
    return [Action(target_pose=step.target_pose, extras={"phase": "move"})]


def _lower_heat(step: WorkflowStep) -> list[Action]:
    """Heat is a semantic action — no robot motion. Emits a single
    no-op Action carrying the heater details in extras so fake-sim
    runs (and tests / audit logs) can see that heat happened.
    """
    if not step.target_object:
        raise SchemaError("primitive 'heat' requires target_object (heater asset)")
    target_temp_k = step.extras.get("target_temperature_k")
    duration_s = step.extras.get("duration_s")
    if not isinstance(target_temp_k, (int, float)) or not isinstance(
        duration_s, (int, float)
    ):
        raise SchemaError(
            "primitive 'heat' requires extras "
            "{'target_temperature_k': float, 'duration_s': float}"
        )
    return [
        Action(
            extras={
                "phase": "heat",
                "asset_name": step.target_object,
                "target_temperature_k": float(target_temp_k),
                "duration_s": float(duration_s),
            }
        )
    ]
