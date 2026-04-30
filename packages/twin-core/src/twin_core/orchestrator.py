"""MiniOrchestrator — accepts list[UnitOperation], dispatches via backend.

Per FR-4.1/4.2: single-step interruptible / inspectable. Each step is
visible (the lowered Action and the resulting Observation are recorded
on the run record) so a caller can stop and inspect after any step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from twin_core.lowering import lower_workflow
from twin_core.operations import UnitOperation, operation_to_workflow
from twin_core.protocols import ExecutorBackend, FrameService
from twin_core.schemas import Action, Observation


@dataclass
class StepRecord:
    """One executed Action + its resulting Observation, plus provenance."""

    operation_index: int
    action_index: int
    action: Action
    observation: Observation


@dataclass
class RunRecord:
    """Result of running a list of UnitOperations end-to-end."""

    initial_observation: Observation
    steps: list[StepRecord] = field(default_factory=list)
    completed: bool = False


class MiniOrchestrator:
    """Translate UnitOperations into Actions, dispatch via a backend."""

    def __init__(self, backend: ExecutorBackend, frames: FrameService) -> None:
        self._backend = backend
        self._frames = frames

    def run(self, operations: Iterable[UnitOperation]) -> RunRecord:
        ops = list(operations)
        initial_obs = self._backend.reset()
        record = RunRecord(initial_observation=initial_obs)

        for op_index, op in enumerate(ops):
            workflow = operation_to_workflow(op)
            actions = lower_workflow(workflow, self._frames)
            for act_index, action in enumerate(actions):
                obs = self._backend.step(action)
                record.steps.append(
                    StepRecord(
                        operation_index=op_index,
                        action_index=act_index,
                        action=action,
                        observation=obs,
                    )
                )
        record.completed = True
        return record
