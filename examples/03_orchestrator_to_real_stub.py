"""Day 4-5 demo: MiniOrchestrator drives RealStubBackend end-to-end.

Run:
    uv run python examples/03_orchestrator_to_real_stub.py

Expected: same plan as 02_orchestrator_to_sim.py, same lowered actions,
same observed state transitions — but dispatched through the real-stub
instead of sim. Demo 1 ("same plan, two backends") is satisfied.

Tip: try running with `TWIN_REAL_INJECT_FAILURE=step:5` set to see the
stub raise CommunicationError mid-run, then with
`TWIN_REAL_INJECT_FAILURE=gripper_close` to inject a targeted failure.
"""

from __future__ import annotations

from twin_core import MiniOrchestrator, PickAndPlace
from twin_real import RealStubBackend
from twin_sim import StaticFrameService


def main() -> None:
    orchestrator = MiniOrchestrator(
        # Demo latency is non-zero per FR-3.3 — keep small so the demo
        # finishes in a few seconds instead of ~16s with default 0.5–2s.
        backend=RealStubBackend(latency_seconds=(0.05, 0.15)),
        frames=StaticFrameService.default_for_demo(),
    )

    plan = [
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="grasp",
            target_object="optical_table",
            target_frame="dropoff_a1",
        ),
    ]

    record = orchestrator.run(plan)
    print(f"completed={record.completed} steps={len(record.steps)}")
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
