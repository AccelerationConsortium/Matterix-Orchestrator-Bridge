"""Day 6-7 demo: 4 workflows, 3 caught, 1 passes (Demo 2 from charter §3).

Run:
    uv run python examples/04_safety_demo.py

Each workflow is fed through:
  - twin_core.preflight()   — schema + frame + state-machine
  - twin_sim.dry_run()      — physical infeasibility via the fake env

Expected output: WF1 caught by SchemaError, WF2 by FrameNotFound, WF3 by
PhysicalInfeasibility, WF4 passes both checks.
"""

from __future__ import annotations

from dataclasses import dataclass

from twin_core import (
    CheckResult,
    PickAndPlace,
    WorkflowDict,
    WorkflowStep,
    operation_to_workflow,
    preflight,
)
from twin_sim import (
    FakeMatterixEnv,
    SimBackend,
    StaticFrameService,
    dry_run,
)


@dataclass
class DemoCase:
    name: str
    description: str
    workflow: WorkflowDict
    nogo_aabb: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None


def build_cases() -> list[DemoCase]:
    return [
        DemoCase(
            name="WF1",
            description="schema violation — pick_object frame must be 'grasp'",
            workflow=operation_to_workflow(
                PickAndPlace(
                    source_object="beaker_500ml",
                    source_frame="post_grasp",  # not in PICK_OBJECT_ALLOWED_FRAMES
                    target_object="optical_table",
                    target_frame="dropoff_a1",
                )
            ),
        ),
        DemoCase(
            name="WF2",
            description="frame not found — beaker_500ml has no 'lid' frame",
            workflow=[
                # We bypass operation_to_workflow to cleanly target the
                # frame-existence check without tripping the schema layer.
                WorkflowStep(
                    primitive="pick_object",
                    target_object="beaker_500ml",
                    target_frame="grasp",
                ),
                WorkflowStep(
                    primitive="place_at",
                    target_object="optical_table",
                    target_frame="dropoff_z9",  # not declared
                ),
            ],
        ),
        DemoCase(
            name="WF3",
            description="physical infeasibility — dropoff_a1 inside no-go region",
            workflow=operation_to_workflow(
                PickAndPlace(
                    source_object="beaker_500ml",
                    source_frame="grasp",
                    target_object="optical_table",
                    target_frame="dropoff_a1",
                )
            ),
            nogo_aabb=((0.55, 0.15, 0.05), (0.65, 0.25, 0.40)),
        ),
        DemoCase(
            name="WF4",
            description="clean — should pass every check",
            workflow=operation_to_workflow(
                PickAndPlace(
                    source_object="beaker_500ml",
                    source_frame="grasp",
                    target_object="optical_table",
                    target_frame="dropoff_a2",
                )
            ),
        ),
    ]


def report(case_name: str, phase: str, result: CheckResult) -> None:
    if result.ok:
        print(f"  [{case_name}] {phase:<10} ✓ ok")
    else:
        seg = result.plan_segment or {}
        seg_short = (
            f"{seg.get('primitive')} object={seg.get('target_object')} "
            f"frame={seg.get('target_frame')}"
            if seg
            else "(no segment)"
        )
        print(
            f"  [{case_name}] {phase:<10} ✗ {result.error_class}: {result.reason}\n"
            f"           step_index={result.step_index} segment={seg_short}"
        )


def run_case(case: DemoCase, frames: StaticFrameService) -> None:
    print(f"\n{case.name}: {case.description}")

    pre = preflight(case.workflow, frames)
    report(case.name, "preflight", pre)
    if not pre.ok:
        return

    backend = SimBackend(FakeMatterixEnv(nogo_aabb=case.nogo_aabb))
    sim_result = dry_run(case.workflow, backend, frames)
    if sim_result.ok:
        print(f"  [{case.name}] dry_run    ✓ ok")
    else:
        print(
            f"  [{case.name}] dry_run    ✗ {sim_result.error_class}: "
            f"{sim_result.reason} (failed_step={sim_result.failed_step_index})"
        )


def main() -> None:
    frames = StaticFrameService.default_for_demo()
    cases = build_cases()

    print(f"Running safety demo on {len(cases)} workflows...")
    for case in cases:
        run_case(case, frames)

    print("\nSummary: WF1/WF2/WF3 should be caught; WF4 should pass both checks.")


if __name__ == "__main__":
    main()
