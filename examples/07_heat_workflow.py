"""Composite workflow: Pick beaker → Place on hotplate → Heat to 80°C.

Run:
    uv run python examples/07_heat_workflow.py

Demonstrates:
  * The bridge handles >1 UnitOperation in a single plan (extensibility).
  * The bridge handles a non-motion UO (Heat — semantic action) alongside
    a motion UO (PickAndPlace).
  * Asset names match real Matterix scene names (`beaker`, `hotplate`)
    so the same plan would run on a real Matterix task that registers
    both assets (stock `Matterix-Test-Beaker-Lift-Franka-v1` does NOT
    yet — see docs/findings.md "Things that remain unknown").

This runs against FakeMatterixEnv. Heat lowering is a no-op in fake-sim
(records the semantic action but no temperature dynamics). On real
Matterix, MatterixWorkflowRunner translates the same plan into:
  PickObjectCfg → PlaceObjectCfg → TurnOnHeaterCfg(on) → WaitCfg → TurnOnHeaterCfg(off)
"""

from __future__ import annotations

from twin_core import Heat, MiniOrchestrator, PickAndPlace
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
            target_object="hotplate",
            target_frame="place",        # matches Matterix PlaceObjectCfg convention
        ),
        Heat(
            asset_name="hotplate",
            target_temperature_k=353.15,  # 80°C
            duration_s=5.0,
        ),
    ]

    record = orchestrator.run(plan)
    print(f"completed={record.completed} steps={len(record.steps)}")

    for step in record.steps:
        phase = step.action.extras.get("phase", "?")
        ee = tuple(round(c, 3) for c in step.observation.ee_pose.position)
        if phase == "heat":
            heater = step.action.extras.get("asset_name")
            t_k = step.action.extras.get("target_temperature_k")
            dur = step.action.extras.get("duration_s")
            print(
                f"  op={step.operation_index} act={step.action_index} "
                f"phase={phase!s:<14} heater={heater} "
                f"target={t_k}K duration={dur}s"
            )
        else:
            print(
                f"  op={step.operation_index} act={step.action_index} "
                f"phase={phase!s:<14} ee={ee} "
                f"gripper_closed={step.observation.gripper_closed}"
            )

    print(f"\nbridge translated {len(plan)} UnitOperation(s) into "
          f"{len(record.steps)} backend action(s).")


if __name__ == "__main__":
    main()
