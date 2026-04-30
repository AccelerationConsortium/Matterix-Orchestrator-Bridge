"""Protocols defining the contract every backend must satisfy.

ExecutorBackend is the central abstraction. Sim backend, real-stub
backend, and (future) real hardware backend all implement this.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from twin_core.schemas import Action, Observation, Pose


@runtime_checkable
class ExecutorBackend(Protocol):
    """A backend that can reset and step through a workflow."""

    def reset(self) -> Observation: ...

    def step(self, action: Action) -> Observation: ...

    def close(self) -> None: ...


@runtime_checkable
class FrameService(Protocol):
    """Looks up named frames on assets.

    Sim backend: reads from USD asset config.
    Real backend: reads from calibration database / hand-eye result.
    """

    def lookup(self, asset_id: str, frame_name: str) -> Pose: ...

    def has_frame(self, asset_id: str, frame_name: str) -> bool: ...