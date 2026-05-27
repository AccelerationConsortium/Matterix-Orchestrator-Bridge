"""twin-sim: Matterix-backed sim ExecutorBackend (gated runtime)."""

from twin_sim.backend import (
    FakeMatterixEnv,
    MatterixEnvLike,
    SimBackend,
    SimRuntimeUnavailable,
    make_real_env,
)
from twin_sim.dry_run import DryRunResult, dry_run
from twin_sim.frame_service import StaticFrameService
from twin_sim.batch_runner import BatchRunResult, MatterixBatchRunner, RiskProfile, StepStats
from twin_sim.real_runner import MatterixWorkflowRunner, WorkflowRunResult

__all__ = [
    "BatchRunResult",
    "DryRunResult",
    "FakeMatterixEnv",
    "MatterixBatchRunner",
    "MatterixEnvLike",
    "MatterixWorkflowRunner",
    "RiskProfile",
    "SimBackend",
    "SimRuntimeUnavailable",
    "StaticFrameService",
    "StepStats",
    "WorkflowRunResult",
    "dry_run",
    "make_real_env",
]
