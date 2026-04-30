"""Day 2 demo: drive SimBackend (FakeMatterixEnv) through a PickAndPlace.

Run:
    uv run python examples/01_run_sim.py

Expected: prints lowered actions and observations as the fake env moves
the ee through pre_grasp → grasp → close → post_grasp → pre_dropoff →
dropoff → open → retract. Also prints the beaker's world pose at the
end to confirm it followed the gripper.
"""

from __future__ import annotations

from twin_core import (
    PickAndPlace,
    lower_workflow,
    operation_to_workflow,
)
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService


def main() -> None:
    backend = SimBackend(FakeMatterixEnv())
    frames = StaticFrameService.default_for_demo()

    obs = backend.reset()
    print(f"reset → ee={obs.ee_pose.position}")

    op = PickAndPlace(
        source_object="beaker",
        source_frame="grasp",
        target_object="table",
        target_frame="dropoff_a1",
    )
    workflow = operation_to_workflow(op)
    actions = lower_workflow(workflow, frames)
    print(f"lowered {len(actions)} actions")

    for i, action in enumerate(actions):
        obs = backend.step(action)
        phase = action.extras.get("phase", "?")
        print(
            f"  [{i}] phase={phase!s:<14} "
            f"ee={tuple(round(c, 3) for c in obs.ee_pose.position)} "
            f"gripper_closed={obs.gripper_closed}"
        )

    beaker = obs.asset_frames.get("beaker", {}).get("world")
    if beaker:
        print(f"final beaker world pose: {tuple(round(c, 3) for c in beaker.position)}")
    backend.close()


if __name__ == "__main__":
    main()
