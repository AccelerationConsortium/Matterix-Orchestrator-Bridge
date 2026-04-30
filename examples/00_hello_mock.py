"""Day 0 hello-world: drive MockBackend through a PickAndPlace.

Run:
    uv run python examples/00_hello_mock.py

Expected: prints the WorkflowStep sequence and the resulting action stream.
"""

from __future__ import annotations

from twin_core import (
    Action,
    PickAndPlace,
    Pose,
    WorkflowStep,
    operation_to_workflow,
)
from twin_core.mock_backend import MockBackend


def lower_step_to_action(step: WorkflowStep) -> Action:
    """Naive lowering for the mock — sim/real backends do this for real."""
    if step.primitive == "pick_object":
        return Action(
            target_pose=Pose(position=(0.4, 0.0, 0.3)),
            gripper_command="close",
            extras={"primitive": step.primitive},
        )
    if step.primitive == "place_at":
        return Action(
            target_pose=Pose(position=(0.6, 0.2, 0.3)),
            gripper_command="open",
            extras={"primitive": step.primitive},
        )
    return Action(extras={"primitive": step.primitive})


def main() -> None:
    backend = MockBackend()
    obs = backend.reset()
    print(f"reset → ee={obs.ee_pose.position} gripper_closed={obs.gripper_closed}")

    op = PickAndPlace(
        source_object="beaker_500ml",
        source_frame="grasp",
        target_object="optical_table",
        target_frame="dropoff_a1",
    )
    workflow = operation_to_workflow(op)
    for step in workflow:
        print(
            f"workflow step: {step.primitive} "
            f"object={step.target_object} frame={step.target_frame}"
        )

    for step in workflow:
        action = lower_step_to_action(step)
        obs = backend.step(action)
        print(
            f"step {step.primitive} → ee={obs.ee_pose.position} "
            f"gripper_closed={obs.gripper_closed}"
        )

    backend.close()
    print(f"recorded {len(backend.actions)} actions")


if __name__ == "__main__":
    main()
