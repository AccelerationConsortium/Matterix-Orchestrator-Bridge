"""Batch risk analysis: N parallel Matterix envs → SafetySignal list.

Run on the lab Linux machine ONLY (Isaac Lab + matterix_sm installed):

    uv run --no-sync python examples/10_batch_analysis.py --num_envs 64
    # For a full statistical run:
    uv run --no-sync python examples/10_batch_analysis.py --num_envs 1000

What this does
--------------
1. Launches Matterix with num_envs parallel environments (all on GPU).
2. Runs the same PickAndPlace workflow across all envs simultaneously.
3. Collects per-env success/failure and per-step aggregate stats.
4. Builds a RiskProfile and prints SafetySignals for the orchestrator.

The wall-clock time for N=1000 is roughly the same as N=1 because Matterix
is fully GPU-vectorised. Use this to get a statistically meaningful failure
rate before the first real experiment.

SafetySignal output format
--------------------------
  [CRITICAL] step=-1  source=failure_rate   ... overall rate exceeds 50%
  [WARNING]  step=42  source=failure_rate   ... 12% of envs failed at step 42
  [INFO]     step=-1  source=failure_rate   ... overall rate 8%

The orchestrator consumes this list to decide:
  - critical → do not run the real experiment; investigate Matterix results
  - warning  → proceed with tighter monitoring on the flagged step
  - info     → proceed normally, log the rate
"""

from __future__ import annotations

import argparse


def main() -> None:
    from isaaclab.app import AppLauncher  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        default="Matterix-Test-Beaker-Lift-Franka-v1",
        help="Matterix task name.",
    )
    parser.add_argument(
        "--num_envs",
        type=int,
        default=64,
        help="Parallel environments (use 1000 for production-quality stats).",
    )
    parser.add_argument(
        "--warning_threshold",
        type=float,
        default=0.20,
        help="Failure rate above which a warning signal is emitted (default 20%%).",
    )
    parser.add_argument(
        "--critical_threshold",
        type=float,
        default=0.50,
        help="Failure rate above which a critical signal is emitted (default 50%%).",
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()

    app_launcher = AppLauncher(headless=args.headless)
    simulation_app = app_launcher.app

    from twin_core import PickAndPlace, operation_to_workflow
    from twin_sim import MatterixBatchRunner, RiskProfile, make_real_env

    print(f"[batch] task={args.task!r}  num_envs={args.num_envs}")
    env = make_real_env(
        task=args.task,
        num_envs=args.num_envs,
        device=args.device,
        headless=args.headless,
    )
    print(f"[batch] env ready: step_dt={env.step_dt}  device={env.device}")

    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="beaker",
            target_frame="dropoff_a1",
        )
    )

    runner = MatterixBatchRunner(env=env, robot_asset="robot")
    print(f"[batch] running {args.num_envs} parallel envs...")
    result = runner.run_batch(workflow)

    print(
        f"\n[batch] results — "
        f"success={result.success_count}/{result.n_envs} "
        f"({result.success_rate:.1%})  "
        f"failure={result.failure_count}/{result.n_envs} "
        f"({result.failure_rate:.1%})  "
        f"timed_out={result.timed_out_count}  "
        f"total_steps={result.total_physics_steps}"
    )

    profile = RiskProfile.from_batch(
        result,
        warning_threshold=args.warning_threshold,
        critical_threshold=args.critical_threshold,
    )

    if profile.mean_steps_to_success is not None:
        print(f"[batch] mean steps to success: {profile.mean_steps_to_success:.1f}")
    if profile.mean_steps_to_failure is not None:
        print(f"[batch] mean steps to failure: {profile.mean_steps_to_failure:.1f}")
    if profile.risky_steps:
        print(f"[batch] risky physics steps: {profile.risky_steps}")

    print(f"\n[batch] SafetySignals ({len(profile.signals)} total):")
    if not profile.signals:
        print("  (none — workflow looks safe at this sample size)")
    for sig in profile.signals:
        step_str = f"step={sig.step_index}" if sig.step_index != -1 else "overall"
        print(f"  [{sig.level.upper():8s}] {step_str:12s}  {sig.message}")

    env.close()
    simulation_app.close()


if __name__ == "__main__":
    main()
