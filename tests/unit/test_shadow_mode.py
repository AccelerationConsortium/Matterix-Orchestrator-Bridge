"""Unit tests for SHADOW mode + DivergenceAlert detection."""

from __future__ import annotations

from twin_core import Arbiter, Mode, PickAndPlace
from twin_real import RealStubBackend
from twin_sim import FakeMatterixEnv, SimBackend, StaticFrameService


def _frames() -> StaticFrameService:
    return StaticFrameService.default_for_demo()


def _plan() -> list[PickAndPlace]:
    return [
        PickAndPlace(
            source_object="beaker",
            source_frame="grasp",
            target_object="ika_plate",
            target_frame="place",
        )
    ]


def test_shadow_mode_runs_both_backends() -> None:
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.SHADOW,
    )
    result = arb.run(_plan())
    assert result.ok
    assert result.sim_run is not None and result.sim_run.completed
    assert result.real_run is not None and result.real_run.completed
    # Same plan → same number of steps in both records.
    assert len(result.sim_run.steps) == len(result.real_run.steps) == 8


def test_shadow_mode_no_divergence_when_backends_agree() -> None:
    """Without position_bias, sim and real-stub apply target_pose
    identically → no alerts."""
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.SHADOW,
        divergence_threshold_m=0.02,
    )
    result = arb.run(_plan())
    assert result.divergence_alerts == []


def test_shadow_mode_detects_calibration_drift() -> None:
    """Bias real-stub by 3cm in X; threshold 2cm → expect alerts on
    every step that has a target_pose."""
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(
            latency_seconds=(0.0, 0.0),
            position_bias_m=(0.03, 0.0, 0.0),
        ),
        frames=_frames(),
        mode=Mode.SHADOW,
        divergence_threshold_m=0.02,
    )
    result = arb.run(_plan())
    # 8 lowered Actions. Bias persists in real-stub's _ee_pose across
    # gripper-only steps (no target_pose → ee not updated → previous
    # biased pose stays). Sim's last-pose also stays. Divergence is
    # therefore sticky — all 8 steps fire alerts at ~3cm.
    assert len(result.divergence_alerts) == 8
    for a in result.divergence_alerts:
        assert a.distance_m > 0.02
        assert 0.025 < a.distance_m < 0.035  # ~3cm bias


def test_shadow_mode_records_pairwise_step_observations() -> None:
    """sim_run.steps[i] and real_run.steps[i] correspond to the same
    Action at the same step index."""
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(
            latency_seconds=(0.0, 0.0),
            position_bias_m=(0.05, 0.0, 0.0),
        ),
        frames=_frames(),
        mode=Mode.SHADOW,
    )
    result = arb.run(_plan())
    for sim_step, real_step in zip(result.sim_run.steps, result.real_run.steps):
        assert sim_step.action == real_step.action  # same Action sent to both
        assert sim_step.operation_index == real_step.operation_index
        assert sim_step.action_index == real_step.action_index


def test_shadow_mode_high_threshold_suppresses_small_divergence() -> None:
    """1cm bias under a 5cm threshold → no alert."""
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(
            latency_seconds=(0.0, 0.0),
            position_bias_m=(0.01, 0.0, 0.0),
        ),
        frames=_frames(),
        mode=Mode.SHADOW,
        divergence_threshold_m=0.05,
    )
    result = arb.run(_plan())
    assert result.divergence_alerts == []
    assert result.ok


def test_shadow_mode_preflight_failure_halts_before_any_dispatch() -> None:
    """Bad plan → preflight halts; neither backend sees anything."""
    arb = Arbiter(
        sim_backend=SimBackend(FakeMatterixEnv()),
        real_backend=RealStubBackend(latency_seconds=(0.0, 0.0)),
        frames=_frames(),
        mode=Mode.SHADOW,
    )
    bad = [
        PickAndPlace(
            source_object="beaker",
            source_frame="post_grasp",  # schema reject
            target_object="ika_plate",
            target_frame="place",
        )
    ]
    result = arb.run(bad)
    assert not result.ok
    assert result.halted_before_real
    assert result.sim_run is None
    assert result.real_run is None
    assert result.divergence_alerts == []
