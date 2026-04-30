"""Unit tests for the Arbiter (FR-5.x)."""

from __future__ import annotations

import pytest

from twin_core import Arbiter, Mode, PickAndPlace
from twin_core.mock_backend import MockBackend
from twin_real import RealStubBackend
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService, dry_run


def _frames() -> StaticFrameService:
    return StaticFrameService.default_for_demo()


def _clean_plan() -> list[PickAndPlace]:
    return [
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="grasp",
            target_object="optical_table",
            target_frame="dropoff_a1",
        )
    ]


def test_sim_only_does_not_touch_real() -> None:
    real = RealStubBackend(latency_seconds=(0.0, 0.0))
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=real,
        frames=_frames(),
        mode=Mode.SIM_ONLY,
    )
    result = arb.run(_clean_plan())
    assert result.ok
    assert result.sim_run is not None and result.sim_run.completed
    assert result.real_run is None


def test_real_only_does_not_consult_sim() -> None:
    arb = Arbiter(
        sim_backend=MockBackend(),  # not consulted; cheap to construct
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.REAL_ONLY,
    )
    result = arb.run(_clean_plan())
    assert result.ok
    assert result.real_run is not None and result.real_run.completed
    assert result.sim_run is None
    assert result.sim_dry_run is None


def test_sim_first_passes_clean_plan_to_real() -> None:
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.SIM_FIRST_THEN_REAL,
        dry_run_fn=dry_run,
    )
    result = arb.run(_clean_plan())
    assert result.ok
    assert result.sim_dry_run is not None and result.sim_dry_run.ok
    assert result.real_run is not None and result.real_run.completed
    assert not result.halted_before_real


def test_sim_first_blocks_real_when_sim_fails() -> None:
    sim = SimBackend(
        FakeMatterixEnv(nogo_aabb=((0.55, 0.15, 0.05), (0.65, 0.25, 0.40)))
    )
    arb = Arbiter(
        sim_backend=sim,
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.SIM_FIRST_THEN_REAL,
        dry_run_fn=dry_run,
    )
    result = arb.run(_clean_plan())
    assert not result.ok
    assert result.sim_dry_run is not None and not result.sim_dry_run.ok
    assert result.sim_dry_run.error_class == "PhysicalInfeasibility"
    assert result.real_run is None  # CRUCIAL — real never sees a bad plan
    assert result.halted_before_real
    assert result.halt_reason is not None
    assert "PhysicalInfeasibility" in result.halt_reason


def test_preflight_failure_halts_before_any_backend() -> None:
    bad_plan = [
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="post_grasp",  # schema reject
            target_object="optical_table",
            target_frame="dropoff_a1",
        )
    ]
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.SIM_FIRST_THEN_REAL,
        dry_run_fn=dry_run,
    )
    result = arb.run(bad_plan)
    assert not result.ok
    assert not result.preflight_result.ok
    assert result.preflight_result.error_class == "SchemaError"
    assert result.sim_dry_run is None
    assert result.sim_run is None
    assert result.real_run is None
    assert result.halted_before_real


def test_sim_first_requires_dry_run_fn() -> None:
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.SIM_FIRST_THEN_REAL,
        dry_run_fn=None,
    )
    with pytest.raises(ValueError):
        arb.run(_clean_plan())
