"""Arbiter — mode-driven dispatch between sim and real backends (FR-5.x).

Three modes:
  * sim_only            — preflight + run on sim. Real is not touched.
  * real_only           — preflight + run on real. Sim is not consulted.
  * sim_first_then_real — preflight + sim dry-run (gate). Only on gate
                          pass do we run on real. Failed gate propagates
                          the structured error and never touches real.

Lives in twin-core (not its own package) because it's small and depends
only on the contract layer plus a sim-side dry-run callable. The
dry-run callable is injected so twin-core does not import twin-sim
(keeps the dependency direction one-way).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable

from twin_core.lowering import lower_workflow
from twin_core.operations import UnitOperation, WorkflowDict, operation_to_workflow
from twin_core.orchestrator import MiniOrchestrator, RunRecord, StepRecord
from twin_core.protocols import ExecutorBackend, FrameService
from twin_core.schemas import Observation, Pose
from twin_core.validation import CheckResult, preflight


class Mode(str, Enum):
    SIM_ONLY = "sim_only"
    REAL_ONLY = "real_only"
    SIM_FIRST_THEN_REAL = "sim_first_then_real"
    SHADOW = "shadow"


@dataclass(frozen=True)
class DivergenceAlert:
    """Fired during SHADOW mode when sim and real ee_pose diverge.

    Not raised — collected on `ArbiterResult.divergence_alerts` so the
    caller decides whether to log, alert, or halt downstream actions.
    """

    operation_index: int
    step_index: int
    sim_ee_pose: Pose
    real_ee_pose: Pose
    distance_m: float


# Signature: dry_run(workflow, sim_backend, frames) -> CheckResult-like
# We use a Protocol via Callable + duck-typing on `.ok`, `.error_class`,
# `.reason`, `.failed_step_index` — DryRunResult from twin_sim conforms.
DryRunFn = Callable[[WorkflowDict, ExecutorBackend, FrameService], "DryRunLike"]


class DryRunLike:
    ok: bool
    error_class: str | None
    reason: str | None
    failed_step_index: int | None


@dataclass
class ArbiterResult:
    """Outcome of an Arbiter.run() call."""

    mode: Mode
    preflight_result: CheckResult
    sim_dry_run: CheckResult | None = None
    real_run: RunRecord | None = None
    sim_run: RunRecord | None = None
    halted_before_real: bool = False
    halt_reason: str | None = None
    divergence_alerts: list[DivergenceAlert] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if not self.preflight_result.ok:
            return False
        if self.halted_before_real:
            return False
        if self.mode == Mode.SIM_ONLY:
            return self.sim_run is not None and self.sim_run.completed
        if self.mode == Mode.REAL_ONLY:
            return self.real_run is not None and self.real_run.completed
        if self.mode == Mode.SHADOW:
            # Shadow ok = both runs completed. Divergence alerts are an
            # observation, not a failure — caller decides what to do.
            return (
                self.sim_run is not None
                and self.sim_run.completed
                and self.real_run is not None
                and self.real_run.completed
            )
        # sim_first_then_real
        return self.real_run is not None and self.real_run.completed


@dataclass
class Arbiter:
    """Mode-driven dispatch with sim-first gating."""

    sim_backend: ExecutorBackend
    real_backend: ExecutorBackend
    frames: FrameService
    mode: Mode = Mode.SIM_FIRST_THEN_REAL
    dry_run_fn: DryRunFn | None = None  # required when mode uses sim gate
    divergence_threshold_m: float = 0.02  # SHADOW mode ee-pose tolerance
    _ops: list[UnitOperation] = field(default_factory=list, init=False, repr=False)

    def run(self, operations: Iterable[UnitOperation]) -> ArbiterResult:
        ops = list(operations)
        # Build the combined workflow once for preflight + dry-run.
        workflow: WorkflowDict = []
        for op in ops:
            workflow.extend(operation_to_workflow(op))

        pre = preflight(workflow, self.frames)
        result = ArbiterResult(mode=self.mode, preflight_result=pre)
        if not pre.ok:
            result.halted_before_real = True
            result.halt_reason = f"preflight {pre.error_class}: {pre.reason}"
            return result

        if self.mode == Mode.SIM_ONLY:
            result.sim_run = self._dispatch(self.sim_backend, ops)
            return result

        if self.mode == Mode.REAL_ONLY:
            result.real_run = self._dispatch(self.real_backend, ops)
            return result

        if self.mode == Mode.SHADOW:
            sim_run, real_run, alerts = self._dispatch_shadow(ops)
            result.sim_run = sim_run
            result.real_run = real_run
            result.divergence_alerts = alerts
            return result

        # sim_first_then_real
        if self.dry_run_fn is None:
            raise ValueError(
                "Mode.SIM_FIRST_THEN_REAL requires `dry_run_fn` to be set"
            )
        dr = self.dry_run_fn(workflow, self.sim_backend, self.frames)
        result.sim_dry_run = CheckResult(
            ok=dr.ok,
            error_class=dr.error_class,
            reason=dr.reason,
            step_index=dr.failed_step_index,
        )
        if not dr.ok:
            result.halted_before_real = True
            result.halt_reason = f"sim dry-run {dr.error_class}: {dr.reason}"
            return result

        result.real_run = self._dispatch(self.real_backend, ops)
        return result

    def _dispatch(
        self, backend: ExecutorBackend, ops: list[UnitOperation]
    ) -> RunRecord:
        return MiniOrchestrator(backend=backend, frames=self.frames).run(ops)

    def _dispatch_shadow(
        self, ops: list[UnitOperation]
    ) -> tuple[RunRecord, RunRecord, list[DivergenceAlert]]:
        """Lockstep: same Action goes to both backends, observations
        compared per step. Records both runs + any alerts.

        Each backend is reset once at the start; lowering happens once
        (sim and real consume identical Action streams). Divergence is
        computed on ee_pose only — joint-level divergence would need
        backend-specific obs to compare.
        """
        sim_obs = self.sim_backend.reset()
        real_obs = self.real_backend.reset()
        sim_record = RunRecord(initial_observation=sim_obs)
        real_record = RunRecord(initial_observation=real_obs)
        alerts: list[DivergenceAlert] = []

        global_step = 0
        for op_index, op in enumerate(ops):
            workflow = operation_to_workflow(op)
            actions = lower_workflow(workflow, self.frames)
            for act_index, action in enumerate(actions):
                sim_obs = self.sim_backend.step(action)
                real_obs = self.real_backend.step(action)
                sim_record.steps.append(
                    StepRecord(
                        operation_index=op_index,
                        action_index=act_index,
                        action=action,
                        observation=sim_obs,
                    )
                )
                real_record.steps.append(
                    StepRecord(
                        operation_index=op_index,
                        action_index=act_index,
                        action=action,
                        observation=real_obs,
                    )
                )

                dist = _ee_distance(sim_obs, real_obs)
                if dist > self.divergence_threshold_m:
                    alerts.append(
                        DivergenceAlert(
                            operation_index=op_index,
                            step_index=global_step,
                            sim_ee_pose=sim_obs.ee_pose,
                            real_ee_pose=real_obs.ee_pose,
                            distance_m=dist,
                        )
                    )
                global_step += 1

        sim_record.completed = True
        real_record.completed = True
        return sim_record, real_record, alerts


def _ee_distance(sim_obs: Observation, real_obs: Observation) -> float:
    sx, sy, sz = sim_obs.ee_pose.position
    rx, ry, rz = real_obs.ee_pose.position
    return ((sx - rx) ** 2 + (sy - ry) ** 2 + (sz - rz) ** 2) ** 0.5
