"""Pre-flight safety checks (FR-6.x).

Three layers, in order:

  1. schema_check  — frame-type policy + lowering well-formedness
  2. frame_check   — every referenced (asset_id, frame_name) exists
  3. state_check   — gripper state machine doesn't double-open / double-close

Each layer returns a `CheckResult`. `preflight()` runs all three and
returns the first failure. The sim dry-run (PhysicalInfeasibility) is
not included here — it lives in `twin_sim.dry_run` because it requires a
backend and is heavier than these in-memory checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from twin_core.errors import (
    FrameNotFound,
    SchemaError,
    StateMachineViolation,
    ValidationError,
)
from twin_core.lowering import lower_workflow
from twin_core.operations import WorkflowDict
from twin_core.protocols import FrameService

# Frame-type policy: which frame names a primitive is allowed to target.
# Tightening or relaxing happens here, not at every call site.
PICK_OBJECT_ALLOWED_FRAMES: frozenset[str] = frozenset({"grasp"})
# place_at: the canonical Matterix convention is "place" (PlaceObjectCfg
# always targets pre_place + place on the asset). The "dropoff_" prefix
# is also accepted to support fake-sim demos with multi-slot tables.
PLACE_AT_ALLOWED_FRAMES: frozenset[str] = frozenset({"place"})
PLACE_AT_ALLOWED_PREFIX: str = "dropoff_"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single safety check."""

    ok: bool
    error_class: str | None = None
    reason: str | None = None
    step_index: int | None = None
    plan_segment: dict[str, Any] | None = None

    @classmethod
    def passing(cls) -> "CheckResult":
        return cls(ok=True)

    @classmethod
    def failing(
        cls,
        error: ValidationError,
        step_index: int | None = None,
        plan_segment: dict[str, Any] | None = None,
    ) -> "CheckResult":
        return cls(
            ok=False,
            error_class=type(error).__name__,
            reason=str(error),
            step_index=step_index,
            plan_segment=plan_segment,
        )


def _segment(step: object) -> dict[str, Any]:
    # WorkflowStep is a Pydantic model — model_dump exists; fall back for
    # anything else (model_construct can produce odd shapes).
    if hasattr(step, "model_dump"):
        return step.model_dump()  # type: ignore[no-any-return]
    return {"repr": repr(step)}


def schema_check(workflow: WorkflowDict) -> CheckResult:
    """Frame-type policy + lowering well-formedness.

    Catches:
      * pick_object with a target_frame not in PICK_OBJECT_ALLOWED_FRAMES
      * place_at with a target_frame not prefixed with 'dropoff_'
      * primitive that lowering doesn't know how to handle
      * required fields missing for a primitive
    """
    for index, step in enumerate(workflow):
        if step.primitive == "pick_object":
            if step.target_frame not in PICK_OBJECT_ALLOWED_FRAMES:
                err = SchemaError(
                    f"pick_object target_frame must be one of "
                    f"{sorted(PICK_OBJECT_ALLOWED_FRAMES)}, got "
                    f"{step.target_frame!r}"
                )
                return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))
        elif step.primitive == "place_at":
            tf = step.target_frame
            ok = tf is not None and (
                tf in PLACE_AT_ALLOWED_FRAMES or tf.startswith(PLACE_AT_ALLOWED_PREFIX)
            )
            if not ok:
                err = SchemaError(
                    f"place_at target_frame must be in "
                    f"{sorted(PLACE_AT_ALLOWED_FRAMES)} or start with "
                    f"{PLACE_AT_ALLOWED_PREFIX!r}, got {tf!r}"
                )
                return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))
        elif step.primitive == "move":
            if step.target_pose is None:
                err = SchemaError("move requires target_pose")
                return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))
        elif step.primitive == "heat":
            if not step.target_object:
                err = SchemaError("heat requires target_object (heater asset)")
                return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))
            tt = step.extras.get("target_temperature_k")
            ds = step.extras.get("duration_s")
            if not isinstance(tt, (int, float)) or not isinstance(ds, (int, float)):
                err = SchemaError(
                    "heat extras must include target_temperature_k (K) and duration_s"
                )
                return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))
        else:
            err = SchemaError(f"unknown primitive: {step.primitive!r}")
            return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))

    return CheckResult.passing()


def frame_check(workflow: WorkflowDict, frames: FrameService) -> CheckResult:
    """Every (asset_id, frame_name) referenced by lowering must exist.

    We invoke the real lowering rather than re-implementing the rules,
    so the check stays consistent with what the backend will actually do.
    """
    try:
        lower_workflow(workflow, frames)
    except FrameNotFound as exc:
        return CheckResult.failing(exc)
    except ValidationError as exc:
        # SchemaError leaked from lowering — surface it but as the
        # appropriate error class. (schema_check should have caught
        # this already; we keep it here for defence in depth.)
        return CheckResult.failing(exc)
    return CheckResult.passing()


def state_check(
    workflow: WorkflowDict, *, initial_gripper_closed: bool = False
) -> CheckResult:
    """Replay the workflow against an abstract gripper state machine.

    pick_object closes; place_at opens. Detects:
      * pick_object when gripper already closed (already holding something)
      * place_at when gripper is open (nothing to place)
    """
    closed = initial_gripper_closed
    for index, step in enumerate(workflow):
        if step.primitive == "pick_object":
            if closed:
                err = StateMachineViolation(
                    current_state="gripper_closed",
                    attempted_action="pick_object (gripper already holding)",
                )
                return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))
            closed = True
        elif step.primitive == "place_at":
            if not closed:
                err = StateMachineViolation(
                    current_state="gripper_open",
                    attempted_action="place_at (nothing to place)",
                )
                return CheckResult.failing(err, step_index=index, plan_segment=_segment(step))
            closed = False
        # 'move' and 'heat' have no gripper effect
    return CheckResult.passing()


def preflight(
    workflow: WorkflowDict,
    frames: FrameService,
    *,
    initial_gripper_closed: bool = False,
) -> CheckResult:
    """Run schema → frame → state checks, returning the first failure."""
    for check in (
        lambda: schema_check(workflow),
        lambda: frame_check(workflow, frames),
        lambda: state_check(workflow, initial_gripper_closed=initial_gripper_closed),
    ):
        result = check()
        if not result.ok:
            return result
    return CheckResult.passing()
