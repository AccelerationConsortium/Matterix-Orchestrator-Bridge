"""twin-core: shared protocols, schemas, and contracts.

This package has zero runtime dependencies on Matterix or Isaac Sim.
Everything here must be importable on a CPU-only machine in <1s.
"""

from twin_core.arbiter import Arbiter, ArbiterResult, DivergenceAlert, Mode
from twin_core.errors import (
    FrameNotFound,
    PhysicalInfeasibility,
    SchemaError,
    StateMachineViolation,
    ValidationError,
)
from twin_core.lowering import lower_workflow
from twin_core.operations import (
    Heat,
    PickAndPlace,
    UnitOperation,
    WorkflowDict,
    operation_to_workflow,
)
from twin_core.orchestrator import MiniOrchestrator, RunRecord, StepRecord
from twin_core.protocols import ExecutorBackend, FrameService
from twin_core.validation import (
    CheckResult,
    frame_check,
    preflight,
    schema_check,
    state_check,
)
from twin_core.safety import SafetySignal
from twin_core.schemas import (
    Action,
    GripperCommand,
    Observation,
    Pose,
    PrimitiveName,
    WorkflowStep,
)

__all__ = [
    "Action",
    "Arbiter",
    "SafetySignal",
    "ArbiterResult",
    "CheckResult",
    "DivergenceAlert",
    "ExecutorBackend",
    "FrameNotFound",
    "FrameService",
    "GripperCommand",
    "Heat",
    "MiniOrchestrator",
    "Mode",
    "Observation",
    "PhysicalInfeasibility",
    "PickAndPlace",
    "Pose",
    "PrimitiveName",
    "RunRecord",
    "SchemaError",
    "StateMachineViolation",
    "StepRecord",
    "UnitOperation",
    "ValidationError",
    "WorkflowDict",
    "WorkflowStep",
    "frame_check",
    "lower_workflow",
    "operation_to_workflow",
    "preflight",
    "schema_check",
    "state_check",
]
