"""Linux-lab smoke test: drive REAL Matterix via twin-sim runner.

Run on the lab machine ONLY (Linux + Isaac Lab + matterix_sm + matterix_tasks):

    # 1. Activate the conda env where Isaac Lab + Matterix are installed
    conda activate <isaaclab-env>

    # 2. From the bridge repo root:
    uv run python examples/06_run_real_matterix.py --headless

    # If running with the Matterix launcher script (preserves env vars):
    /path/to/Matterix/matterix.sh -p examples/06_run_real_matterix.py --headless

This is the end-to-end verification path. It:
  1. Launches Omniverse via AppLauncher (required before gym.make).
  2. Constructs the stock beaker-lift task env via make_real_env().
  3. Translates a twin PickAndPlace into a Matterix WorkflowDict.
  4. Drives the env via MatterixWorkflowRunner (uses matterix_sm.StateMachine).
  5. Reports success/failure + final ee + gripper state.

Calibration points to check on first run (see docs/findings.md A2/A4):
  * `MatterixWorkflowRunner._obs_to_twin` reads keys
    `obs["articulations"]["robot"]["robot__ee_world_pos"]` etc. If the
    task config renames them, update the runner.
  * `_step_to_matterix_cfg` maps to PickObjectCfg/PlaceObjectCfg with
    `agent_assets="robot"`. The stock beaker-lift task uses this name;
    other tasks may differ.
"""

from __future__ import annotations

import argparse


def main() -> None:
    # Omniverse must be launched BEFORE importing isaaclab/gym task code.
    # AppLauncher.add_app_launcher_args adds --headless, --device, etc.
    from isaaclab.app import AppLauncher  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        default="Matterix-Test-Beaker-Lift-Franka-v1",
        help="Matterix task name (default: stock beaker-lift Franka v1).",
    )
    parser.add_argument(
        "--target_object",
        default="beaker",
        help="Asset name to pick (must exist on the env's scene).",
    )
    parser.add_argument(
        "--num_envs",
        type=int,
        default=1,
        help="Parallel envs. Smoke test uses 1.",
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()

    app_launcher = AppLauncher(headless=args.headless)
    simulation_app = app_launcher.app

    # Imports that depend on Omniverse running.
    from twin_core import PickAndPlace, operation_to_workflow
    from twin_sim import MatterixWorkflowRunner, make_real_env

    print(f"[smoke] launching task={args.task!r} num_envs={args.num_envs}")
    env = make_real_env(
        task=args.task,
        num_envs=args.num_envs,
        device=args.device,
        headless=args.headless,
    )
    print(
        f"[smoke] env ready: num_envs={env.num_envs} "
        f"step_dt={env.step_dt} device={env.device}"
    )

    # The stock beaker-lift task only registers a `pickup_beaker` workflow
    # (no place). For the smoke test, drive a single pick_object step via
    # the runner; place_at would require a task that has a dropoff frame
    # configured on the optical_table asset.
    op = PickAndPlace(
        source_object=args.target_object,
        source_frame="grasp",
        target_object=args.target_object,  # same asset for the smoke test
        target_frame="dropoff_a1",
    )
    workflow = operation_to_workflow(op)
    # Run only the pick_object step on the stock task (no dropoff frames).
    workflow_for_smoke = workflow[:1]

    runner = MatterixWorkflowRunner(env=env, robot_asset="robot")
    print(f"[smoke] running workflow ({len(workflow_for_smoke)} step(s))...")
    result = runner.run_workflow(workflow_for_smoke)

    print(
        f"[smoke] completed={result.completed} success={result.success} "
        f"failure={result.failure} step_count={result.step_count}"
    )
    if result.final_observation is not None:
        obs = result.final_observation
        print(
            f"[smoke] final ee={tuple(round(c, 3) for c in obs.ee_pose.position)} "
            f"gripper_closed={obs.gripper_closed} "
            f"gripper_width={obs.gripper_width}"
        )
    else:
        print(
            "[smoke] WARNING: could not translate final obs — runner returned "
            "raw_final_obs for inspection. Check key naming in "
            "MatterixWorkflowRunner._obs_to_twin against your task's "
            "ObservationManagerCfg."
        )

    env.close()
    simulation_app.close()


if __name__ == "__main__":
    main()
