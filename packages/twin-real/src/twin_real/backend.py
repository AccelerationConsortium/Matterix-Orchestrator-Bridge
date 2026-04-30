"""RealStubBackend — mimics real-hardware behavior in pure Python.

Per FR-3.x: same ExecutorBackend interface as sim; internal state
machine (gripper, ee_pose); simulated latency 0.5–2s per action;
TWIN_REAL_INJECT_FAILURE env var for failure injection; raises
StateMachineViolation on inconsistent gripper commands. Passes the same
contract tests as MockBackend and SimBackend.

Latency is parameterised so contract tests can pass `latency_seconds=(0.0,
0.0)`. The default reflects FR-3.3 for demos.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field

from twin_core.errors import StateMachineViolation, ValidationError
from twin_core.schemas import Action, Observation, Pose


class CommunicationError(ValidationError):
    """Failure-injected communication error (FR-3.4)."""


@dataclass
class RealStubBackend:
    """Stateful stub of a real Franka + Robotiq85 controller."""

    initial_ee_pose: Pose = field(
        default_factory=lambda: Pose(position=(0.0, 0.0, 0.5))
    )
    latency_seconds: tuple[float, float] = (0.5, 2.0)
    rng: random.Random = field(default_factory=random.Random)
    failure_spec_env_var: str = "TWIN_REAL_INJECT_FAILURE"

    _ee_pose: Pose = field(init=False)
    _gripper_closed: bool = field(init=False, default=False)
    _step_count: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self._ee_pose = self.initial_ee_pose

    # -- ExecutorBackend ----------------------------------------------

    def reset(self) -> Observation:
        self._sleep()
        self._ee_pose = self.initial_ee_pose
        self._gripper_closed = False
        self._step_count = 0
        return self._observation()

    def step(self, action: Action) -> Observation:
        self._step_count += 1
        self._sleep()
        self._maybe_inject_failure(action)

        if action.gripper_command is not None:
            self._apply_gripper(action.gripper_command)

        if action.target_pose is not None:
            self._ee_pose = action.target_pose

        return self._observation()

    def close(self) -> None:
        return None

    # -- internals ----------------------------------------------------

    def _apply_gripper(self, command: str) -> None:
        if command == "close":
            if self._gripper_closed:
                raise StateMachineViolation(
                    current_state="gripper_closed",
                    attempted_action="close (already closed)",
                )
            self._gripper_closed = True
        elif command == "open":
            if not self._gripper_closed:
                raise StateMachineViolation(
                    current_state="gripper_open",
                    attempted_action="open (already open)",
                )
            self._gripper_closed = False
        else:
            # GripperCommand literal already constrains this at the schema
            # level, but be defensive in case extras-bypass is ever added.
            raise StateMachineViolation(
                current_state="any",
                attempted_action=f"unknown gripper command {command!r}",
            )

    def _sleep(self) -> None:
        lo, hi = self.latency_seconds
        if hi <= 0.0:
            return
        time.sleep(self.rng.uniform(lo, hi))

    def _maybe_inject_failure(self, action: Action) -> None:
        spec = os.environ.get(self.failure_spec_env_var)
        if not spec:
            return

        # Supported specs:
        #   "always"             → every step fails
        #   "step:N"             → fail when self._step_count == N
        #   "gripper_close"      → fail when action.gripper_command == "close"
        #   "gripper_open"       → fail when action.gripper_command == "open"
        if spec == "always":
            raise CommunicationError("injected: always")
        if spec.startswith("step:"):
            try:
                target = int(spec.removeprefix("step:"))
            except ValueError as exc:
                raise CommunicationError(f"bad failure spec {spec!r}") from exc
            if self._step_count == target:
                raise CommunicationError(f"injected: step {target}")
        if spec == "gripper_close" and action.gripper_command == "close":
            raise CommunicationError("injected: gripper_close")
        if spec == "gripper_open" and action.gripper_command == "open":
            raise CommunicationError("injected: gripper_open")

    def _observation(self) -> Observation:
        return Observation(
            ee_pose=self._ee_pose,
            gripper_closed=self._gripper_closed,
            gripper_width=0.0 if self._gripper_closed else 0.085,
        )
