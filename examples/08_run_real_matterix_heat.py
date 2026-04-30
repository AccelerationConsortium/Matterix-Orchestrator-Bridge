"""End-to-end: bridge drives the REAL Matterix heat-transfer task.

Run on the lab Linux machine ONLY (Linux + Isaac Lab + matterix_sm +
matterix_tasks installed):

    uv run --no-sync python examples/08_run_real_matterix_heat.py
    # or to see Isaac Sim:
    uv run --no-sync python examples/08_run_real_matterix_heat.py --headless=False

This is the full-loop demo. The plan is the same shape as
`examples/07_heat_workflow.py` (which runs against FakeMatterixEnv),
but here it runs against the stock Matterix task
`Matterix-Test-Semantics-Heat-Transfer-Franka-v1` — which already
includes a Franka, beaker, IKA plate, table, AND a heat-transfer
semantic stack.

What you will see (with --headless removed):
  1. Isaac Sim opens.
  2. Franka picks the beaker.
  3. Franka moves the beaker to the IKA plate, places it.
  4. Heater turns on (target 100°C).
  5. Wait ~5 seconds (heat transfer model warms the beaker).
  6. Heater turns off.
  7. Terminal prints `success=True` + final ee/gripper/heater state.

The bridge plan is two UnitOperations:

    PickAndPlace(beaker → ika_plate@place)
    Heat(ika_plate, target_temperature_k=373.15, duration_s=5.0)

The bridge translates this into FIVE matterix_sm Cfgs:

    PickObjectCfg(object=beaker)
    PlaceObjectCfg(target=ika_plate)
    TurnOnHeaterCfg(asset_name=ika_plate, value=True, target_temperature=373.15)
    WaitCfg(duration=5.0)
    TurnOnHeaterCfg(asset_name=ika_plate, value=False)

…which is structurally identical to the stock task's
`pickup_and_place_beaker` workflow. Running this example proves the
bridge can drive the same Matterix task that a hand-written workflow
can — i.e., the SDL-side abstraction is faithful to the DT side.
"""

from __future__ import annotations

import argparse


def main() -> None:
    from isaaclab.app import AppLauncher  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        default="Matterix-Test-Semantics-Heat-Transfer-Franka-v1",
        help="Matterix task with beaker + ika_plate + Franka.",
    )
    parser.add_argument(
        "--target_temp_k",
        type=float,
        default=373.15,
        help="Heater setpoint in Kelvin (373.15 = 100°C).",
    )
    parser.add_argument(
        "--heat_duration_s",
        type=float,
        default=5.0,
        help="Seconds to hold the heater on.",
    )
    parser.add_argument(
        "--num_envs",
        type=int,
        default=1,
        help="Parallel envs (smoke = 1).",
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()

    app_launcher = AppLauncher(headless=args.headless)
    simulation_app = app_launcher.app

    from twin_core import Heat, PickAndPlace, operation_to_workflow
    from twin_sim import MatterixWorkflowRunner, make_real_env

    print(f"[heat-demo] launching task={args.task!r} num_envs={args.num_envs}")
    env = make_real_env(
        task=args.task,
        num_envs=args.num_envs,
        device=args.device,
        headless=args.headless,
    )
    print(
        f"[heat-demo] env ready: num_envs={env.num_envs} "
        f"step_dt={env.step_dt} device={env.device}"
    )

    plan = [
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="ika_plate",
            target_frame="place",
        ),
        Heat(
            asset_name="ika_plate",
            target_temperature_k=args.target_temp_k,
            duration_s=args.heat_duration_s,
        ),
    ]

    workflow = []
    for op in plan:
        workflow.extend(operation_to_workflow(op))

    print(f"[heat-demo] bridge translated {len(plan)} UO(s) → "
          f"{len(workflow)} workflow step(s)")

    runner = MatterixWorkflowRunner(env=env, robot_asset="robot")
    print("[heat-demo] running on real Matterix...")
    result = runner.run_workflow(workflow)

    print(
        f"[heat-demo] completed={result.completed} success={result.success} "
        f"failure={result.failure} step_count={result.step_count}"
    )
    if result.final_observation is not None:
        obs = result.final_observation
        print(
            f"[heat-demo] final ee={tuple(round(c, 3) for c in obs.ee_pose.position)} "
            f"gripper_closed={obs.gripper_closed} "
            f"gripper_width={obs.gripper_width}"
        )

    # Try to surface the heater state from the raw obs (calibration check).
    raw = result.raw_final_obs or {}
    policy = raw.get("policy", {}) if isinstance(raw, dict) else {}
    if policy:
        heater_on = policy.get("ika_plate_is_heater_on")
        plate_temp = policy.get("ika_plate_temperature")
        beaker_temp = policy.get("beaker_temperature")
        print(
            f"[heat-demo] semantic state — "
            f"heater_on={heater_on} plate_temp={plate_temp} "
            f"beaker_temp={beaker_temp}"
        )

    env.close()
    simulation_app.close()


if __name__ == "__main__":
    main()
