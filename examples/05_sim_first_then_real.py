"""Day 8 demo: Arbitrator with sim_first_then_real gating (Demo 3 from charter §3).

Run:
    uv run python examples/05_sim_first_then_real.py

Feeds two workflows through the arbiter:
  - WF3-equivalent: dropoff_a1 inside a no-go region in sim. Gate fails,
    real backend is NEVER touched.
  - WF4-equivalent: clean. Gate passes, real backend executes.

Expected output: WF3 halts before real (real_run is None); WF4 reaches
real and completes.
"""

from __future__ import annotations

from twin_core import Arbiter, Mode, PickAndPlace
from twin_real import RealStubBackend
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService, dry_run


def make_arbiter(
    nogo_aabb: tuple[tuple[float, float, float], tuple[float, float, float]] | None,
) -> Arbiter:
    return Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv(nogo_aabb=nogo_aabb)),
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=StaticFrameService.default_for_demo(),
        mode=Mode.SIM_FIRST_THEN_REAL,
        dry_run_fn=dry_run,
    )


def report(label: str, result) -> None:
    print(f"\n{label}")
    print(f"  mode={result.mode.value} ok={result.ok}")
    print(f"  preflight: ok={result.preflight_result.ok}")
    if result.sim_dry_run is not None:
        print(
            f"  sim_dry_run: ok={result.sim_dry_run.ok} "
            f"reason={result.sim_dry_run.reason}"
        )
    print(f"  halted_before_real={result.halted_before_real}")
    if result.halt_reason:
        print(f"  halt_reason: {result.halt_reason}")
    if result.real_run is None:
        print("  real_run: NOT EXECUTED")
    else:
        print(
            f"  real_run: completed={result.real_run.completed} "
            f"steps={len(result.real_run.steps)}"
        )


def main() -> None:
    plan = [
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="grasp",
            target_object="optical_table",
            target_frame="dropoff_a1",
        )
    ]

    # Case 1: sim sees a no-go region covering dropoff_a1 → gate fails.
    arbiter_blocked = make_arbiter(
        nogo_aabb=((0.55, 0.15, 0.05), (0.65, 0.25, 0.40))
    )
    result_blocked = arbiter_blocked.run(plan)
    report("Case 1 — sim gate blocks: WF3-equivalent", result_blocked)

    # Case 2: clean sim → gate passes → real executes.
    arbiter_clean = make_arbiter(nogo_aabb=None)
    result_clean = arbiter_clean.run(plan)
    report("Case 2 — sim gate passes: WF4-equivalent", result_clean)


if __name__ == "__main__":
    main()
