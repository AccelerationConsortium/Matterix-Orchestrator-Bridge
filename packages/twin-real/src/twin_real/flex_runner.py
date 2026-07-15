"""Workflow-level execution boundary for the real Flex SiLA connector."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from twin_core.workflow_parser import ParsedStep, ParsedWorkflow

from twin_real.flex_adapter import FlexStepError, FlexWorkflowAdapter
from twin_real.flex_contract import FlexCommand, FlexResultValue
from twin_real.flex_sila import FlexMachineError, FlexMachineStatus


class FlexTransport(Protocol):
    """Execution surface implemented by the gRPC client and offline fakes."""

    async def execute(self, command: FlexCommand) -> FlexResultValue: ...

    async def machine_status(self) -> FlexMachineStatus: ...

    async def close(self) -> None: ...


class FlexParallelExecutionError(FlexStepError):
    """Flattened parallel hardware steps require an external scheduler."""

    def __init__(self, step_id: str, thread_name: str | None) -> None:
        self.thread_name = thread_name
        super().__init__(
            step_id,
            "belongs to parallel thread "
            f"{thread_name!r}; dispatch it with execute_step() from the mixed-device scheduler",
        )


class FlexMixedWorkflowError(FlexStepError):
    """Whole-workflow execution cannot silently skip another device's steps."""

    def __init__(self, skipped_step_ids: list[str]) -> None:
        self.skipped_step_ids = skipped_step_ids
        super().__init__(
            skipped_step_ids[0],
            "run() accepts Flex-only workflows; dispatch mixed workflows "
            "step-by-step from the owning scheduler",
        )


@dataclass(frozen=True)
class CompiledFlexWorkflow:
    """Fully validated Flex subset of an external mixed-device workflow."""

    name: str
    version: str
    commands: list[FlexCommand]
    skipped_step_ids: list[str]


@dataclass(frozen=True)
class FlexExecutionRecord:
    """One completed SiLA command and its post-command status evidence."""

    command: FlexCommand
    response: FlexResultValue
    machine_status: FlexMachineStatus | None = None


@dataclass
class FlexWorkflowRunResult:
    """Completed Flex-only command stream."""

    workflow_name: str
    workflow_version: str
    records: list[FlexExecutionRecord] = field(default_factory=list)
    skipped_step_ids: list[str] = field(default_factory=list)
    completed: bool = False


class FlexWorkflowExecutionError(RuntimeError):
    """A Flex-only run failed after zero or more recorded side effects."""

    def __init__(
        self,
        command: FlexCommand,
        partial_result: FlexWorkflowRunResult,
        cause: Exception,
    ) -> None:
        self.command = command
        self.partial_result = partial_result
        self.cause = cause
        super().__init__(
            f"Flex workflow failed at step {command.step_id!r}; "
            f"{len(partial_result.records)} prior command(s) were fully recorded. "
            f"The current command may have side effects and must be reconciled "
            f"before retry: {cause}"
        )


@dataclass
class FlexWorkflowRunner:
    """Compile and execute the Flex-owned portion of a parsed workflow.

    ``run()`` is intentionally sequential and rejects flattened parallel Flex
    steps before touching hardware.  A mixed-device orchestrator should retain
    phase/thread ownership and call ``execute_step()`` at the appropriate time.
    """

    adapter: FlexWorkflowAdapter
    transport: FlexTransport
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def compile(self, workflow: ParsedWorkflow) -> CompiledFlexWorkflow:
        """Validate every Flex step before any command reaches hardware."""
        commands: list[FlexCommand] = []
        skipped: list[str] = []
        for step in workflow.steps:
            command = self.adapter.adapt(step)
            if command is None:
                skipped.append(step.step_id)
                continue
            if step.is_parallel:
                raise FlexParallelExecutionError(step.step_id, step.thread_name)
            commands.append(command)
        return CompiledFlexWorkflow(
            name=workflow.name,
            version=workflow.version,
            commands=commands,
            skipped_step_ids=skipped,
        )

    async def execute_step(self, step: ParsedStep) -> FlexExecutionRecord | None:
        """Execute one scheduler-owned step; return ``None`` for another device."""
        command = self.adapter.adapt(step)
        if command is None:
            return None
        return await self.execute_command(command)

    async def execute_command(self, command: FlexCommand) -> FlexExecutionRecord:
        """Execute one precompiled command and enforce its safety status guard."""
        async with self._lock:
            response = await self.transport.execute(command)
            status = None
            if command.verify_machine_status:
                status = await self.transport.machine_status()
                if status.is_error_state:
                    raise FlexMachineError(status)
            return FlexExecutionRecord(
                command=command,
                response=response,
                machine_status=status,
            )

    async def run(self, workflow: ParsedWorkflow) -> FlexWorkflowRunResult:
        """Precompile then execute a sequential workflow to completion."""
        compiled = self.compile(workflow)
        if compiled.skipped_step_ids:
            raise FlexMixedWorkflowError(compiled.skipped_step_ids)
        result = FlexWorkflowRunResult(
            workflow_name=compiled.name,
            workflow_version=compiled.version,
        )
        for command in compiled.commands:
            try:
                record = await self.execute_command(command)
            except Exception as exc:
                raise FlexWorkflowExecutionError(command, result, exc) from exc
            result.records.append(record)
        result.completed = True
        return result

    async def close(self) -> None:
        """Close the underlying connector transport."""
        async with self._lock:
            await self.transport.close()
