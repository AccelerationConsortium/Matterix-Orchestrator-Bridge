"""Day 3 demo: MiniOrchestrator drives SimBackend end-to-end.

Run:
    uv run python examples/02_orchestrator_to_sim.py

Expected: orchestrator translates a list of UnitOperations into the same
action stream as 01_run_sim.py, but via the protocol-level interface.
Prints a compact run log showing operation index, action index, phase,
and the resulting ee pose / gripper state.
"""

from __future__ import annotations

from twin_core import MiniOrchestrator, PickAndPlace
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService


def main() -> None:
    orchestrator = MiniOrchestrator(
        backend=SimBackend(FakeMatterixEnv()),
        frames=StaticFrameService.default_for_demo(),
    )

    plan = [
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="table",
            target_frame="dropoff_a1",
        ),
    ]

    record = orchestrator.run(plan)
    print(f"completed={record.completed} steps={len(record.steps)}")
    print(f"initial ee={record.initial_observation.ee_pose.position}")

    for step in record.steps:
        phase = step.action.extras.get("phase", "?")
        ee = tuple(round(c, 3) for c in step.observation.ee_pose.position)
        print(
            f"  op={step.operation_index} act={step.action_index} "
            f"phase={phase!s:<14} ee={ee} "
            f"gripper_closed={step.observation.gripper_closed}"
        )


if __name__ == "__main__":
    main()
