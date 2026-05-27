"""Unit tests for twin_core.result_schema — bridge result JSON serialiser.

All tests run without Matterix. Inputs are constructed from synthetic
dataclasses / simple objects so the schema contract is validated in
isolation from the sim runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from twin_core.result_schema import (
    batch_run_to_dict,
    shadow_run_to_dict,
    single_run_to_dict,
)
from twin_core.safety import SafetySignal
from twin_core.schemas import Observation, Pose


# ---------------------------------------------------------------------------
# Synthetic fixture helpers
# ---------------------------------------------------------------------------


def _pose(x: float = 0.1, y: float = 0.2, z: float = 0.3) -> Pose:
    return Pose(position=(x, y, z), orientation=(0.0, 0.0, 0.0, 1.0))


def _obs(gripper_closed: bool = False, gripper_width: float | None = 0.08) -> Observation:
    return Observation(
        ee_pose=_pose(),
        gripper_closed=gripper_closed,
        gripper_width=gripper_width,
    )


@dataclass
class FakeWorkflowRunResult:
    completed: bool = True
    success: bool = True
    failure: bool = False
    step_count: int = 500
    final_observation: Observation | None = None
    step_observations: list[Any] = field(default_factory=list)
    semantic_events: list[Any] = field(default_factory=list)
    raw_final_obs: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeRiskProfile:
    n_envs: int = 100
    total_physics_steps: int = 800
    success_rate: float = 0.90
    failure_rate: float = 0.10
    timeout_rate: float = 0.00
    mean_steps_to_success: float | None = 750.0
    mean_steps_to_failure: float | None = 300.0
    risky_steps: list[int] = field(default_factory=list)
    signals: list[SafetySignal] = field(default_factory=list)
    step_stats: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class FakeDivergenceAlert:
    operation_index: int
    step_index: int
    sim_ee_pose: Pose
    real_ee_pose: Pose
    distance_m: float


@dataclass
class FakeArbiterResult:
    ok: bool = True
    halted_before_real: bool = False
    halt_reason: str | None = None
    divergence_alerts: list[FakeDivergenceAlert] = field(default_factory=list)


# ---------------------------------------------------------------------------
# single_run_to_dict
# ---------------------------------------------------------------------------


class TestSingleRunToDict:
    def test_required_envelope_keys_present(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(), step_dt=0.016)
        for key in ("schema_version", "run_id", "timestamp_utc", "mode",
                    "decision", "timing", "risk", "safety_signals",
                    "divergence", "outcome", "final_observation"):
            assert key in result, f"missing key: {key}"

    def test_mode_is_single(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(), step_dt=0.016)
        assert result["mode"] == "single"

    def test_timing_computed_correctly(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(step_count=500), step_dt=0.016)
        assert result["timing"]["sim_step_count"] == 500
        assert result["timing"]["sim_step_dt_s"] == pytest.approx(0.016)
        assert result["timing"]["estimated_duration_s"] == pytest.approx(8.0)

    def test_outcome_fields(self) -> None:
        result = single_run_to_dict(
            FakeWorkflowRunResult(completed=True, success=True, failure=False),
            step_dt=0.016,
        )
        assert result["outcome"] == {"completed": True, "success": True, "failure": False}

    def test_no_signals_gives_proceed_high_confidence(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(), step_dt=0.016)
        assert result["decision"]["proceed"] is True
        assert result["decision"]["confidence"] == "high"

    def test_final_observation_serialised(self) -> None:
        obs = _obs(gripper_closed=True, gripper_width=0.01)
        result = single_run_to_dict(
            FakeWorkflowRunResult(final_observation=obs), step_dt=0.016
        )
        fo = result["final_observation"]
        assert fo is not None
        assert fo["gripper_closed"] is True
        assert fo["ee_pose"]["position"] == [0.1, 0.2, 0.3]

    def test_no_observation_gives_null(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(), step_dt=0.016)
        assert result["final_observation"] is None

    def test_risk_is_null(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(), step_dt=0.016)
        assert result["risk"] is None

    def test_run_id_override(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(), step_dt=0.016, run_id="test-123")
        assert result["run_id"] == "test-123"

    def test_json_serialisable(self) -> None:
        result = single_run_to_dict(FakeWorkflowRunResult(final_observation=_obs()), step_dt=0.016)
        json.dumps(result)  # must not raise


# ---------------------------------------------------------------------------
# batch_run_to_dict
# ---------------------------------------------------------------------------


class TestBatchRunToDict:
    def test_mode_is_batch(self) -> None:
        result = batch_run_to_dict(FakeRiskProfile(), step_dt=0.016)
        assert result["mode"] == "batch"

    def test_risk_block_populated(self) -> None:
        profile = FakeRiskProfile(n_envs=1000, success_rate=0.88, failure_rate=0.12)
        result = batch_run_to_dict(profile, step_dt=0.016)
        risk = result["risk"]
        assert risk["n_envs"] == 1000
        assert risk["success_rate"] == pytest.approx(0.88)
        assert risk["failure_rate"] == pytest.approx(0.12)

    def test_timing_estimated(self) -> None:
        profile = FakeRiskProfile(total_physics_steps=1000)
        result = batch_run_to_dict(profile, step_dt=0.02)
        assert result["timing"]["estimated_duration_s"] == pytest.approx(20.0)

    def test_no_signals_proceed_true(self) -> None:
        result = batch_run_to_dict(FakeRiskProfile(signals=[]), step_dt=0.016)
        assert result["decision"]["proceed"] is True
        assert result["decision"]["confidence"] == "high"

    def test_warning_signal_low_confidence(self) -> None:
        sig = SafetySignal(level="warning", step_index=-1, source="failure_rate", message="8%")
        profile = FakeRiskProfile(signals=[sig])
        result = batch_run_to_dict(profile, step_dt=0.016)
        assert result["decision"]["proceed"] is True
        assert result["decision"]["confidence"] == "low"

    def test_critical_signal_no_proceed(self) -> None:
        sig = SafetySignal(level="critical", step_index=-1, source="failure_rate", message="60%")
        profile = FakeRiskProfile(signals=[sig])
        result = batch_run_to_dict(profile, step_dt=0.016)
        assert result["decision"]["proceed"] is False
        assert result["decision"]["confidence"] == "high"

    def test_signals_serialised(self) -> None:
        sig = SafetySignal(level="info", step_index=5, source="failure_rate", message="low")
        result = batch_run_to_dict(FakeRiskProfile(signals=[sig]), step_dt=0.016)
        assert len(result["safety_signals"]) == 1
        assert result["safety_signals"][0]["level"] == "info"
        assert result["safety_signals"][0]["step_index"] == 5

    def test_risky_steps_in_risk_block(self) -> None:
        profile = FakeRiskProfile(risky_steps=[7, 42])
        result = batch_run_to_dict(profile, step_dt=0.016)
        assert result["risk"]["risky_steps"] == [7, 42]

    def test_outcome_is_null(self) -> None:
        result = batch_run_to_dict(FakeRiskProfile(), step_dt=0.016)
        assert result["outcome"] is None

    def test_json_serialisable(self) -> None:
        sig = SafetySignal(level="warning", step_index=3, source="s", message="m")
        result = batch_run_to_dict(FakeRiskProfile(signals=[sig]), step_dt=0.016)
        json.dumps(result)


# ---------------------------------------------------------------------------
# shadow_run_to_dict
# ---------------------------------------------------------------------------


class TestShadowRunToDict:
    def test_mode_is_shadow(self) -> None:
        result = shadow_run_to_dict(FakeArbiterResult())
        assert result["mode"] == "shadow"

    def test_no_divergence_high_confidence(self) -> None:
        result = shadow_run_to_dict(FakeArbiterResult(divergence_alerts=[]))
        assert result["divergence"]["detected"] is False
        assert result["divergence"]["alert_count"] == 0
        assert result["decision"]["confidence"] == "high"
        assert result["decision"]["proceed"] is True

    def test_divergence_detected_low_confidence(self) -> None:
        alert = FakeDivergenceAlert(
            operation_index=0,
            step_index=3,
            sim_ee_pose=_pose(0.1, 0.2, 0.3),
            real_ee_pose=_pose(0.13, 0.2, 0.3),
            distance_m=0.03,
        )
        result = shadow_run_to_dict(FakeArbiterResult(divergence_alerts=[alert]))
        assert result["divergence"]["detected"] is True
        assert result["divergence"]["alert_count"] == 1
        assert result["decision"]["proceed"] is True
        assert result["decision"]["confidence"] == "low"

    def test_alert_fields_serialised(self) -> None:
        alert = FakeDivergenceAlert(
            operation_index=1,
            step_index=5,
            sim_ee_pose=_pose(0.1, 0.2, 0.3),
            real_ee_pose=_pose(0.13, 0.2, 0.3),
            distance_m=0.03,
        )
        result = shadow_run_to_dict(FakeArbiterResult(divergence_alerts=[alert]))
        a = result["divergence"]["alerts"][0]
        assert a["operation_index"] == 1
        assert a["step_index"] == 5
        assert a["distance_m"] == pytest.approx(0.03)
        assert len(a["sim_position"]) == 3
        assert len(a["real_position"]) == 3

    def test_outcome_block_populated(self) -> None:
        result = shadow_run_to_dict(FakeArbiterResult(ok=True, halted_before_real=False))
        assert result["outcome"]["ok"] is True
        assert result["outcome"]["halted_before_real"] is False

    def test_timing_is_null(self) -> None:
        result = shadow_run_to_dict(FakeArbiterResult())
        assert result["timing"] is None

    def test_json_serialisable(self) -> None:
        alert = FakeDivergenceAlert(
            operation_index=0, step_index=1,
            sim_ee_pose=_pose(), real_ee_pose=_pose(0.15, 0.2, 0.3),
            distance_m=0.05,
        )
        result = shadow_run_to_dict(FakeArbiterResult(divergence_alerts=[alert]))
        json.dumps(result)


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


def test_schema_version_is_1_0() -> None:
    for result in [
        single_run_to_dict(FakeWorkflowRunResult(), step_dt=0.016),
        batch_run_to_dict(FakeRiskProfile(), step_dt=0.016),
        shadow_run_to_dict(FakeArbiterResult()),
    ]:
        assert result["schema_version"] == "1.0"
