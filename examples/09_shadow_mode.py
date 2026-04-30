"""Shadow mode demo: sim and real-stub run lockstep, divergence detected.

Run:
    uv run python examples/09_shadow_mode.py

Demonstrates the second-half value claim from the project:
"DT is useful for real experiments". Specifically, this shows DT
catching that a real-hardware calibration drift would have produced
a different actual position than what sim predicted — without anyone
needing to know in advance which step would diverge.

Setup:
  - Sim backend: FakeMatterixEnv (no calibration drift)
  - Real backend: RealStubBackend with `position_bias_m=(0.03, 0, 0)`
    — simulates a 3cm calibration offset in X. The bridge does NOT
    know about this offset; it sends the same Action stream to both.
  - Arbiter mode: SHADOW. Both backends run in lockstep, ee_pose
    compared per step. Threshold 0.02m (2cm) — bias > threshold.

Expected output:
  - Both runs complete (this is observation, not failure).
  - 8 of 8 steps fire DivergenceAlert. Bias persists in the real-stub
    state across gripper-only steps, so divergence is sticky once it
    appears — no escape until a corrective Action lands.
  - Each alert prints sim vs real ee_pose + Euclidean distance.
"""

from __future__ import annotations

from twin_core import Arbiter, Mode, PickAndPlace
from twin_real import RealStubBackend
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService


def main() -> None:
    arbiter = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(
            latency_seconds=(0.0, 0.0),
            # Pretend the real Franka has a 3cm X-axis calibration drift
            # that DT does not model. Bridge sends sim the unbiased target,
            # real-stub applies the bias on every step.
            position_bias_m=(0.03, 0.0, 0.0),
        ),
        frames=StaticFrameService.default_for_demo(),
        mode=Mode.SHADOW,
        divergence_threshold_m=0.02,
    )

    plan = [
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="ika_plate",
            target_frame="place",
        ),
    ]

    result = arbiter.run(plan)
    print(f"mode={result.mode.value} ok={result.ok}")
    print(f"sim steps={len(result.sim_run.steps)} "
          f"real steps={len(result.real_run.steps)}")
    print(f"divergence_threshold={arbiter.divergence_threshold_m}m")
    print(f"alerts fired: {len(result.divergence_alerts)}\n")

    if not result.divergence_alerts:
        print("No divergence — sim and real agreed within threshold.")
        return

    print("Divergence trace:")
    for alert in result.divergence_alerts:
        sim_p = tuple(round(c, 4) for c in alert.sim_ee_pose.position)
        real_p = tuple(round(c, 4) for c in alert.real_ee_pose.position)
        print(
            f"  step={alert.step_index} (op={alert.operation_index})  "
            f"sim={sim_p}  real={real_p}  "
            f"|d|={alert.distance_m:.4f}m"
        )

    print(
        f"\nDT caught a {arbiter.divergence_threshold_m * 100:.0f}cm+ "
        f"divergence on {len(result.divergence_alerts)} of "
        f"{len(result.sim_run.steps)} steps "
        "— without prior knowledge of where the real hardware would drift."
    )


if __name__ == "__main__":
    main()
