"""Unit tests for twin_core.safety and twin_sim batch data models.

All tests run without Matterix installed — they construct BatchRunResult
and RiskProfile directly from synthetic data.
"""

from __future__ import annotations

import pytest

from twin_core.safety import SafetySignal
from twin_sim.batch_runner import BatchRunResult, RiskProfile, StepStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_batch(
    n_envs: int,
    success: int,
    failure: int,
    step_stats: list[StepStats] | None = None,
    env_success_steps: list[int] | None = None,
    env_failure_steps: list[int] | None = None,
) -> BatchRunResult:
    """Build a synthetic BatchRunResult for testing."""
    timed_out = n_envs - success - failure
    ss = step_stats or []
    return BatchRunResult(
        n_envs=n_envs,
        success_count=success,
        failure_count=failure,
        timed_out_count=timed_out,
        success_rate=success / n_envs if n_envs else 0.0,
        failure_rate=failure / n_envs if n_envs else 0.0,
        total_physics_steps=len(ss),
        step_stats=ss,
        env_success_steps=env_success_steps or ([-1] * n_envs),
        env_failure_steps=env_failure_steps or ([-1] * n_envs),
        final_observations=[None] * n_envs,
    )


def _step_series(n_envs: int, failure_at_steps: dict[int, int]) -> list[StepStats]:
    """Build a step_stats list where `failure_at_steps` maps step→new_failures."""
    cum_failed = 0
    stats = []
    total_steps = max(failure_at_steps.keys()) if failure_at_steps else 10
    for i in range(1, total_steps + 1):
        cum_failed += failure_at_steps.get(i, 0)
        stats.append(StepStats(
            step_index=i,
            n_active=n_envs - cum_failed,
            n_succeeded=0,
            n_failed=cum_failed,
        ))
    return stats


# ---------------------------------------------------------------------------
# SafetySignal
# ---------------------------------------------------------------------------


def test_safety_signal_fields() -> None:
    sig = SafetySignal(
        level="warning",
        step_index=42,
        source="failure_rate",
        message="test",
        metadata={"x": 1},
    )
    assert sig.level == "warning"
    assert sig.step_index == 42
    assert sig.metadata["x"] == 1


def test_safety_signal_frozen() -> None:
    sig = SafetySignal(level="info", step_index=0, source="s", message="m")
    with pytest.raises((AttributeError, TypeError)):
        sig.level = "critical"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StepStats
# ---------------------------------------------------------------------------


def test_step_stats_frozen() -> None:
    ss = StepStats(step_index=1, n_active=900, n_succeeded=50, n_failed=50)
    with pytest.raises((AttributeError, TypeError)):
        ss.n_active = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RiskProfile.from_batch — overall failure rate signals
# ---------------------------------------------------------------------------


class TestRiskProfileOverallSignals:
    def test_no_failures_produces_no_signals(self) -> None:
        batch = _make_batch(n_envs=100, success=100, failure=0)
        profile = RiskProfile.from_batch(batch)
        assert profile.signals == []

    def test_low_failure_rate_produces_info(self) -> None:
        batch = _make_batch(n_envs=100, success=90, failure=5)
        profile = RiskProfile.from_batch(batch)
        assert len(profile.signals) == 1
        assert profile.signals[0].level == "info"
        assert profile.signals[0].source == "failure_rate"

    def test_warning_threshold_crossed(self) -> None:
        batch = _make_batch(n_envs=100, success=75, failure=25)
        profile = RiskProfile.from_batch(batch, warning_threshold=0.20)
        overall = [s for s in profile.signals if s.step_index == -1]
        assert len(overall) == 1
        assert overall[0].level == "warning"

    def test_critical_threshold_crossed(self) -> None:
        batch = _make_batch(n_envs=100, success=40, failure=60)
        profile = RiskProfile.from_batch(
            batch, warning_threshold=0.20, critical_threshold=0.50
        )
        overall = [s for s in profile.signals if s.step_index == -1]
        assert len(overall) == 1
        assert overall[0].level == "critical"

    def test_rates_stored_on_profile(self) -> None:
        batch = _make_batch(n_envs=200, success=150, failure=50)
        profile = RiskProfile.from_batch(batch)
        assert profile.success_rate == pytest.approx(0.75)
        assert profile.failure_rate == pytest.approx(0.25)
        assert profile.n_envs == 200


# ---------------------------------------------------------------------------
# RiskProfile.from_batch — risky step detection
# ---------------------------------------------------------------------------


class TestRiskProfileRiskySteps:
    def test_spike_at_single_step_detected(self) -> None:
        n = 100
        # 10 envs fail suddenly at step 7 (10% spike > 5% threshold)
        stats = _step_series(n, {7: 10})
        batch = _make_batch(n_envs=n, success=90, failure=10, step_stats=stats)
        profile = RiskProfile.from_batch(batch, risky_step_delta=0.05)
        assert 7 in profile.risky_steps

    def test_small_failure_not_flagged_as_risky(self) -> None:
        n = 100
        # Only 3 envs fail at step 5 (3% < 5% threshold)
        stats = _step_series(n, {5: 3})
        batch = _make_batch(n_envs=n, success=97, failure=3, step_stats=stats)
        profile = RiskProfile.from_batch(batch, risky_step_delta=0.05)
        assert profile.risky_steps == []

    def test_risky_step_generates_signal(self) -> None:
        n = 100
        stats = _step_series(n, {3: 30})  # 30% spike
        batch = _make_batch(n_envs=n, success=70, failure=30, step_stats=stats)
        profile = RiskProfile.from_batch(batch)
        step_signals = [s for s in profile.signals if s.step_index == 3]
        assert len(step_signals) == 1
        assert step_signals[0].level in ("warning", "critical")

    def test_multiple_risky_steps_all_flagged(self) -> None:
        n = 200
        stats = _step_series(n, {2: 20, 8: 20})  # two spikes of 10% each
        batch = _make_batch(n_envs=n, success=160, failure=40, step_stats=stats)
        profile = RiskProfile.from_batch(batch, risky_step_delta=0.05)
        assert 2 in profile.risky_steps
        assert 8 in profile.risky_steps


# ---------------------------------------------------------------------------
# RiskProfile.from_batch — mean steps
# ---------------------------------------------------------------------------


class TestRiskProfileMeanSteps:
    def test_mean_steps_to_success(self) -> None:
        n = 4
        batch = _make_batch(
            n_envs=n,
            success=4,
            failure=0,
            env_success_steps=[10, 20, 30, 40],
        )
        profile = RiskProfile.from_batch(batch)
        assert profile.mean_steps_to_success == pytest.approx(25.0)
        assert profile.mean_steps_to_failure is None

    def test_mean_steps_to_failure(self) -> None:
        n = 4
        batch = _make_batch(
            n_envs=n,
            success=0,
            failure=4,
            env_failure_steps=[5, 10, 15, 20],
        )
        profile = RiskProfile.from_batch(batch)
        assert profile.mean_steps_to_failure == pytest.approx(12.5)
        assert profile.mean_steps_to_success is None

    def test_no_completions_gives_none(self) -> None:
        batch = _make_batch(n_envs=10, success=0, failure=0)
        profile = RiskProfile.from_batch(batch)
        assert profile.mean_steps_to_success is None
        assert profile.mean_steps_to_failure is None


# ---------------------------------------------------------------------------
# RiskProfile.from_batch — signal ordering
# ---------------------------------------------------------------------------


def test_signals_ordered_critical_before_warning_before_info() -> None:
    n = 100
    # 60% failure overall (critical) + risky step at step 2 (warning/critical)
    stats = _step_series(n, {2: 10, 5: 50})
    batch = _make_batch(n_envs=n, success=40, failure=60, step_stats=stats)
    profile = RiskProfile.from_batch(
        batch, warning_threshold=0.20, critical_threshold=0.50
    )
    levels = [s.level for s in profile.signals]
    order = {"critical": 0, "warning": 1, "info": 2}
    assert levels == sorted(levels, key=lambda l: order[l])


# ---------------------------------------------------------------------------
# BatchRunResult construction sanity
# ---------------------------------------------------------------------------


def test_batch_result_rates_sum_correctly() -> None:
    n = 1000
    s, f = 850, 120
    batch = _make_batch(n_envs=n, success=s, failure=f)
    assert batch.timed_out_count == n - s - f
    assert batch.success_rate == pytest.approx(s / n)
    assert batch.failure_rate == pytest.approx(f / n)
