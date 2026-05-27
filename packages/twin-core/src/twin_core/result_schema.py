"""Bridge result schema — serialises run outcomes to JSON for orchestrator consumption.

This is the data-sharing layer (Gap B): the bridge converts its internal
dataclasses into a stable JSON envelope that NIMO (or any orchestrator)
can consume to decide:

  1. proceed?          decision.proceed + decision.confidence
  2. how long did it take?  timing.estimated_duration_s
  3. what failed?      safety_signals + divergence

Three entry-points, one per run mode:

    single_run_to_dict(result, step_dt=env.step_dt)   # WorkflowRunResult
    batch_run_to_dict(profile, step_dt=env.step_dt)   # RiskProfile
    shadow_run_to_dict(result)                         # ArbiterResult

All return a plain dict serialisable with json.dumps().

Schema version: "1.0"
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from twin_core.arbiter import ArbiterResult
    from twin_core.safety import SafetySignal
    from twin_core.schemas import Observation


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_id() -> str:
    return str(uuid.uuid4())


def _observation_to_dict(obs: Observation | None) -> dict[str, Any] | None:
    if obs is None:
        return None
    return {
        "ee_pose": {
            "position": list(obs.ee_pose.position),
            "orientation": list(obs.ee_pose.orientation),
        },
        "gripper_closed": obs.gripper_closed,
        "gripper_width": obs.gripper_width,
    }


def _signal_to_dict(sig: SafetySignal) -> dict[str, Any]:
    return {
        "level": sig.level,
        "step_index": sig.step_index,
        "source": sig.source,
        "message": sig.message,
        "metadata": dict(sig.metadata),
    }


def _decision_from_signals(
    signals: list[SafetySignal],
    *,
    halted: bool = False,
    halt_reason: str | None = None,
) -> dict[str, Any]:
    """Derive proceed/confidence from safety signals and halt state."""
    if halted:
        return {
            "proceed": False,
            "confidence": "high",
            "reason": halt_reason or "sim gate failed — halted before real",
        }
    if any(s.level == "critical" for s in signals):
        msgs = [s.message for s in signals if s.level == "critical"]
        return {
            "proceed": False,
            "confidence": "high",
            "reason": "; ".join(msgs),
        }
    if any(s.level == "warning" for s in signals):
        return {
            "proceed": True,
            "confidence": "low",
            "reason": "warning signal — proceed with tighter monitoring",
        }
    return {"proceed": True, "confidence": "high", "reason": "no safety signals"}


# ---------------------------------------------------------------------------
# Public serialisers
# ---------------------------------------------------------------------------


def single_run_to_dict(
    result: Any,
    *,
    step_dt: float,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Serialise a WorkflowRunResult to the bridge result envelope.

    Args:
        result:  WorkflowRunResult from MatterixWorkflowRunner.run_workflow()
        step_dt: env.step_dt — physics timestep in seconds
        run_id:  optional caller-supplied UUID; generated if omitted
    """
    estimated_s = round(result.step_count * step_dt, 3)
    return {
        "schema_version": "1.0",
        "run_id": run_id or _fresh_id(),
        "timestamp_utc": _now_utc(),
        "mode": "single",
        "decision": _decision_from_signals(
            [],
            halted=False,
        ),
        "timing": {
            "sim_step_count": result.step_count,
            "sim_step_dt_s": step_dt,
            "estimated_duration_s": estimated_s,
        },
        "risk": None,
        "safety_signals": [],
        "divergence": {"detected": False, "alert_count": 0, "alerts": []},
        "outcome": {
            "completed": result.completed,
            "success": result.success,
            "failure": result.failure,
        },
        "final_observation": _observation_to_dict(result.final_observation),
    }


def batch_run_to_dict(
    profile: Any,
    *,
    step_dt: float,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Serialise a RiskProfile to the bridge result envelope.

    Args:
        profile: RiskProfile from RiskProfile.from_batch()
        step_dt: env.step_dt — physics timestep in seconds
        run_id:  optional caller-supplied UUID; generated if omitted
    """
    signals: list[SafetySignal] = profile.signals
    estimated_s = round(profile.total_physics_steps * step_dt, 3)
    return {
        "schema_version": "1.0",
        "run_id": run_id or _fresh_id(),
        "timestamp_utc": _now_utc(),
        "mode": "batch",
        "decision": _decision_from_signals(signals),
        "timing": {
            "sim_step_count": profile.total_physics_steps,
            "sim_step_dt_s": step_dt,
            "estimated_duration_s": estimated_s,
            "mean_steps_to_success": profile.mean_steps_to_success,
            "mean_steps_to_failure": profile.mean_steps_to_failure,
        },
        "risk": {
            "n_envs": profile.n_envs,
            "success_rate": profile.success_rate,
            "failure_rate": profile.failure_rate,
            "timeout_rate": profile.timeout_rate,
            "mean_steps_to_success": profile.mean_steps_to_success,
            "mean_steps_to_failure": profile.mean_steps_to_failure,
            "risky_steps": list(profile.risky_steps),
        },
        "safety_signals": [_signal_to_dict(s) for s in signals],
        "divergence": {"detected": False, "alert_count": 0, "alerts": []},
        "outcome": None,
        "final_observation": None,
    }


def shadow_run_to_dict(
    result: ArbiterResult,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Serialise an ArbiterResult (SHADOW mode) to the bridge result envelope.

    Divergence alerts are observational — they set confidence=low but do
    not block proceed. The orchestrator decides whether to halt based on
    its own policy; the bridge reports what the DT observed.

    Args:
        result: ArbiterResult from Arbiter.run() with mode=SHADOW
        run_id: optional caller-supplied UUID; generated if omitted
    """
    alerts = [
        {
            "operation_index": a.operation_index,
            "step_index": a.step_index,
            "sim_position": list(a.sim_ee_pose.position),
            "real_position": list(a.real_ee_pose.position),
            "distance_m": round(a.distance_m, 6),
        }
        for a in result.divergence_alerts
    ]

    divergence_detected = len(alerts) > 0

    if divergence_detected:
        decision: dict[str, Any] = {
            "proceed": True,
            "confidence": "low",
            "reason": (
                f"{len(alerts)} divergence alert(s) detected — "
                "calibration check recommended before next real run"
            ),
        }
    else:
        decision = {"proceed": True, "confidence": "high", "reason": "no divergence detected"}

    return {
        "schema_version": "1.0",
        "run_id": run_id or _fresh_id(),
        "timestamp_utc": _now_utc(),
        "mode": "shadow",
        "decision": decision,
        "timing": None,
        "risk": None,
        "safety_signals": [],
        "divergence": {
            "detected": divergence_detected,
            "alert_count": len(alerts),
            "alerts": alerts,
        },
        "outcome": {
            "ok": result.ok,
            "halted_before_real": result.halted_before_real,
            "halt_reason": result.halt_reason,
        },
        "final_observation": None,
    }
