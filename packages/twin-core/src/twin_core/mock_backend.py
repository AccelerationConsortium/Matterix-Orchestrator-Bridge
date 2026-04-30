"""MockBackend — minimal ExecutorBackend implementation for Day 0.

Used to validate the protocol contract without any sim or hardware.
Once sim backend exists (Day 2), this remains useful for unit tests.
"""

from __future__ import annotations

from twin_core.schemas import Action, Observation, Pose


class MockBackend:
    """In-memory backend that records actions and returns deterministic obs."""

    def __init__(self) -> None:
        self.actions: list[Action] = []
        self._gripper_closed = False
        self._ee_pose = Pose(position=(0.0, 0.0, 0.5))

    def reset(self) -> Observation:
        self.actions.clear()
        self._gripper_closed = False
        self._ee_pose = Pose(position=(0.0, 0.0, 0.5))
        return self._observation()

    def step(self, action: Action) -> Observation:
        self.actions.append(action)
        if action.target_pose is not None:
            self._ee_pose = action.target_pose
        if action.gripper_command == "close":
            self._gripper_closed = True
        elif action.gripper_command == "open":
            self._gripper_closed = False
        return self._observation()

    def close(self) -> None:
        return None

    def _observation(self) -> Observation:
        return Observation(
            ee_pose=self._ee_pose,
            gripper_closed=self._gripper_closed,
        )