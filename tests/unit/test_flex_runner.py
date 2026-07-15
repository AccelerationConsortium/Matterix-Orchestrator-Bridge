"""Tests for the workflow-level Flex execution boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from twin_core import (
    DeckPoint,
    FlexMount,
    StaticFlexDeckResolver,
    StaticFlexInstrumentResolver,
    WellAnchor,
)
from twin_core.workflow_parser import ParsedStep, ParsedWorkflow
from twin_real import (
    FlexMachineError,
    FlexMachineStatus,
    FlexMixedWorkflowError,
    FlexParallelExecutionError,
    FlexWorkflowAdapter,
    FlexWorkflowExecutionError,
    FlexWorkflowRunner,
)


@dataclass
class FakeTransport:
    status: FlexMachineStatus = field(
        default_factory=lambda: FlexMachineStatus(
            estop="DISENGAGED",
            door_open=False,
            is_error_state=False,
            message="",
        )
    )
    commands: list = field(default_factory=list)
    status_reads: int = 0
    closed: bool = False

    async def execute(self, command):
        self.commands.append(command)
        return None

    async def machine_status(self) -> FlexMachineStatus:
        self.status_reads += 1
        return self.status

    async def close(self) -> None:
        self.closed = True


def _step(
    action: str,
    *,
    step_id: str,
    params: dict | None = None,
    parallel: bool = False,
) -> ParsedStep:
    return ParsedStep(
        step_id=step_id,
        action=action,
        device=action.split(".")[0],
        params=params or {},
        description="",
        category="sim" if action.startswith("robot.") else "pass-through",
        estimated_duration_s=None,
        thread_name="robot_thread" if parallel else None,
        is_parallel=parallel,
    )


def _runner(transport: FakeTransport) -> FlexWorkflowRunner:
    adapter = FlexWorkflowAdapter(
        deck=StaticFlexDeckResolver(
            anchors={("rack", "A1", WellAnchor.TOP): DeckPoint(x=1, y=2, z=3)},
            tip_lengths_mm={("rack", "A1"): 95.6},
        ),
        instruments=StaticFlexInstrumentResolver({"pip": FlexMount.LEFT}),
    )
    return FlexWorkflowRunner(adapter=adapter, transport=transport)


@pytest.mark.asyncio
async def test_run_rejects_mixed_workflow_before_hardware() -> None:
    transport = FakeTransport()
    runner = _runner(transport)
    workflow = ParsedWorkflow(
        name="sequential",
        version="1.0",
        steps=[
            _step("robot.home", step_id="home"),
            _step("plc.dispense_ml", step_id="plc"),
            _step("robot.set_lights", step_id="lights", params={"on": True}),
        ],
        timed_duration_s=0,
        timing_coverage=0,
        has_parallel_phases=False,
        sim_step_count=1,
        timed_only_count=0,
        pass_through_count=2,
        unknown_timing_actions=[],
    )

    with pytest.raises(FlexMixedWorkflowError, match="Flex-only"):
        await runner.run(workflow)

    assert transport.commands == []


def test_compile_reports_non_flex_steps_without_executing() -> None:
    transport = FakeTransport()
    runner = _runner(transport)
    workflow = ParsedWorkflow(
        name="compile",
        version="1.0",
        steps=[
            _step("robot.home", step_id="home"),
            _step("wait", step_id="wait"),
        ],
        timed_duration_s=1,
        timing_coverage=0.5,
        has_parallel_phases=False,
        sim_step_count=1,
        timed_only_count=1,
        pass_through_count=0,
        unknown_timing_actions=[],
    )

    compiled = runner.compile(workflow)

    assert [command.method for command in compiled.commands] == ["Home"]
    assert compiled.skipped_step_ids == ["wait"]
    assert transport.commands == []


@pytest.mark.asyncio
async def test_parallel_step_is_rejected_before_any_hardware_call() -> None:
    transport = FakeTransport()
    runner = _runner(transport)
    workflow = ParsedWorkflow(
        name="parallel",
        version="1.0",
        steps=[
            _step("robot.home", step_id="home"),
            _step("robot.home", step_id="parallel_home", parallel=True),
        ],
        timed_duration_s=0,
        timing_coverage=0,
        has_parallel_phases=True,
        sim_step_count=2,
        timed_only_count=0,
        pass_through_count=0,
        unknown_timing_actions=[],
    )

    with pytest.raises(FlexParallelExecutionError, match="execute_step"):
        await runner.run(workflow)

    assert transport.commands == []


@pytest.mark.asyncio
async def test_scheduler_can_execute_one_parallel_step_explicitly() -> None:
    transport = FakeTransport()
    runner = _runner(transport)

    record = await runner.execute_step(
        _step("robot.home", step_id="home", parallel=True)
    )

    assert record is not None
    assert record.command.method == "Home"


@pytest.mark.asyncio
async def test_run_completes_a_flex_only_workflow() -> None:
    transport = FakeTransport()
    runner = _runner(transport)
    workflow = ParsedWorkflow(
        name="flex-only",
        version="1.0",
        steps=[
            _step("robot.home", step_id="home"),
            _step("robot.set_lights", step_id="lights", params={"on": True}),
        ],
        timed_duration_s=0,
        timing_coverage=0,
        has_parallel_phases=False,
        sim_step_count=1,
        timed_only_count=0,
        pass_through_count=1,
        unknown_timing_actions=[],
    )

    result = await runner.run(workflow)

    assert result.completed is True
    assert [record.command.method for record in result.records] == [
        "Home",
        "SetLights",
    ]


@pytest.mark.asyncio
async def test_run_preserves_partial_result_when_a_later_command_fails() -> None:
    class FailingTransport(FakeTransport):
        async def execute(self, command):
            if command.method == "SetLights":
                raise RuntimeError("connector unavailable")
            return await super().execute(command)

    transport = FailingTransport()
    runner = _runner(transport)
    workflow = ParsedWorkflow(
        name="partial",
        version="1.0",
        steps=[
            _step("robot.home", step_id="home"),
            _step("robot.set_lights", step_id="lights", params={"on": True}),
        ],
        timed_duration_s=0,
        timing_coverage=0,
        has_parallel_phases=False,
        sim_step_count=1,
        timed_only_count=0,
        pass_through_count=1,
        unknown_timing_actions=[],
    )

    with pytest.raises(FlexWorkflowExecutionError) as caught:
        await runner.run(workflow)

    assert caught.value.command.step_id == "lights"
    assert caught.value.partial_result.completed is False
    assert [
        record.command.step_id for record in caught.value.partial_result.records
    ] == ["home"]


@pytest.mark.asyncio
async def test_post_motion_machine_error_is_not_silently_accepted() -> None:
    transport = FakeTransport(
        status=FlexMachineStatus(
            estop="PHYSICALLY_ENGAGED",
            door_open=False,
            is_error_state=True,
            message="E-stop engaged",
        )
    )
    runner = _runner(transport)

    with pytest.raises(FlexMachineError, match="error state"):
        await runner.execute_step(_step("robot.home", step_id="home"))


@pytest.mark.asyncio
async def test_close_delegates_to_transport() -> None:
    transport = FakeTransport()
    runner = _runner(transport)

    await runner.close()

    assert transport.closed is True
