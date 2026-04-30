"""Error taxonomy for the safety layer.

Demo target: at least 3 of these classes are caught and shown in
examples/04_safety_demo.py.
"""

from __future__ import annotations


class ValidationError(Exception):
    """Base class for all pre-flight and runtime validation failures."""


class SchemaError(ValidationError):
    """Plan failed schema validation (wrong types, missing fields, etc.)."""


class FrameNotFound(ValidationError):
    """Plan referenced a frame that the asset does not declare."""

    def __init__(self, asset_id: str, frame_name: str) -> None:
        self.asset_id = asset_id
        self.frame_name = frame_name
        super().__init__(f"Frame '{frame_name}' not found on asset '{asset_id}'")


class PhysicalInfeasibility(ValidationError):
    """Sim dry-run determined the plan cannot be executed physically."""

    def __init__(self, reason: str, step_index: int | None = None) -> None:
        self.reason = reason
        self.step_index = step_index
        super().__init__(f"Physical infeasibility at step {step_index}: {reason}")


class StateMachineViolation(ValidationError):
    """Plan violates a state machine constraint (e.g., close gripper twice)."""

    def __init__(self, current_state: str, attempted_action: str) -> None:
        self.current_state = current_state
        self.attempted_action = attempted_action
        super().__init__(
            f"Cannot {attempted_action} in state {current_state}"
        )