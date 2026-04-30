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
from twin_sim.real_runner import MatterixWorkflowRunner, WorkflowRunResult

__all__ = [
    "DryRunResult",
    "FakeMatterixEnv",
    "MatterixEnvLike",
    "MatterixWorkflowRunner",
    "SimBackend",
    "SimRuntimeUnavailable",
    "StaticFrameService",
    "WorkflowRunResult",
    "dry_run",
    "make_real_env",
]
