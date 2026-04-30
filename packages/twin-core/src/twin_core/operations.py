"""Unit operations and translation to backend-executable workflow.

PickAndPlace is the only operation in PoC scope. The translator
operation_to_workflow() now emits typed WorkflowStep instances per the
v1 schema (calibrated Day 1, validated against real Matterix later).
"""

from __future__ import annotations

from dataclasses import dataclass

from twin_core.schemas import WorkflowStep


@dataclass(frozen=True)
class UnitOperation:
    """Marker base class for unit operations."""


@dataclass(frozen=True)
class PickAndPlace(UnitOperation):
    """Pick an object from one frame, place it at another.

    Both source and target are (asset_id, frame_name) pairs — the
    same abstraction sim and real both understand.
    """

    source_object: str
    source_frame: str
    target_object: str
    target_frame: str


WorkflowDict = list[WorkflowStep]


def operation_to_workflow(op: UnitOperation) -> WorkflowDict:
    """Translate a UnitOperation into a backend-executable workflow.

    Emits WorkflowStep primitives. Each backend (sim, real-stub) is
    responsible for translating these into low-level Action sequences.
    """
    if isinstance(op, PickAndPlace):
        return [
            WorkflowStep(
                primitive="pick_object",
                target_object=op.source_object,
                target_frame=op.source_frame,
            ),
            WorkflowStep(
                primitive="place_at",
                target_object=op.target_object,
                target_frame=op.target_frame,
            ),
        ]
    raise NotImplementedError(f"No translator for {type(op).__name__}")
