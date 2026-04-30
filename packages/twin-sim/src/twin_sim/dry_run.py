"""Sim dry-run — fast-forward a workflow in sim, return ok / fail + reason.

Used by the safety layer (Day 6-7) and the arbitrator's
sim_first_then_real mode (Day 8). Catches PhysicalInfeasibility raised
by the underlying env (e.g., FakeMatterixEnv's nogo_aabb collision).
"""

from __future__ import annotations

from dataclasses import dataclass

from twin_core.errors import ValidationError
from twin_core.lowering import lower_workflow
from twin_core.operations import WorkflowDict
from twin_core.protocols import FrameService

from twin_sim.backend import SimBackend


@dataclass
class DryRunResult:
    """Outcome of a sim dry-run."""

    ok: bool
    reason: str | None = None
    error_class: str | None = None
    failed_step_index: int | None = None


def dry_run(
    workflow: WorkflowDict,
    backend: SimBackend,
    frames: FrameService,
) -> DryRunResult:
    """Replay `workflow` against `backend`, returning ok/fail + reason.

    Resets the backend before replay. Any `ValidationError` raised by
    lowering or the env is captured into a structured result instead of
    propagating; non-ValidationError exceptions still propagate (real
    bugs should not be silently swallowed).
    """
    try:
        actions = lower_workflow(workflow, frames)
    except ValidationError as exc:
        return DryRunResult(
            ok=False,
            reason=str(exc),
            error_class=type(exc).__name__,
            failed_step_index=None,
        )

    backend.reset()
    for index, action in enumerate(actions):
        try:
            backend.step(action)
        except ValidationError as exc:
            return DryRunResult(
                ok=False,
                reason=str(exc),
                error_class=type(exc).__name__,
                failed_step_index=index,
            )
    return DryRunResult(ok=True)
