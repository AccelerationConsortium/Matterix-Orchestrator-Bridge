"""Unit tests for MiniOrchestrator."""

from __future__ import annotations

from twin_core import MiniOrchestrator, PickAndPlace
from twin_core.mock_backend import MockBackend
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService


def test_orchestrator_run_completes_with_mock_backend() -> None:
    orch = MiniOrchestrator(
        backend=MockBackend(),
        frames=StaticFrameService.default_for_demo(),
    )
    record = orch.run(
        [
            PickAndPlace(
                source_object="beaker",
                source_frame="grasp",
                target_object="table",
                target_frame="dropoff_a1",
            )
        ]
    )
    assert record.completed
    assert len(record.steps) == 8


def test_orchestrator_grips_beaker_in_sim() -> None:
    orch = MiniOrchestrator(
        backend=SimBackend(FakeMatterixEnv()),
        frames=StaticFrameService.default_for_demo(),
    )
    record = orch.run(
        [
            PickAndPlace(
                source_object="beaker",
                source_frame="grasp",
                target_object="table",
                target_frame="dropoff_a1",
            )
        ]
    )
    # After full PickAndPlace, beaker should have moved to near dropoff_a1.
    final_obs = record.steps[-1].observation
    beaker_world = final_obs.asset_frames["beaker"]["world"]
    # dropoff_a1 is at (0.6, 0.2, 0.10) in the demo registry.
    assert abs(beaker_world.position[0] - 0.6) < 0.05
    assert abs(beaker_world.position[1] - 0.2) < 0.05
