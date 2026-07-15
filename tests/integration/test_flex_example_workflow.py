"""Offline end-to-end tests for the committed Flex example workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from twin_core import (
    DeckPoint,
    FlexMount,
    ParsedWorkflow,
    StaticFlexConfig,
    parse_workflow_json,
)
from twin_real import (
    FlexCommand,
    FlexEStopState,
    FlexMachineStatus,
    FlexResultValue,
    FlexTipPresence,
    FlexWorkflowAdapter,
    FlexWorkflowRunner,
)


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "examples" / "workflows" / "flex_tip_lifecycle.json"
CONFIG = ROOT / "examples" / "flex_dt_config.json"


@dataclass
class RecordingFlexTransport:
    """Deterministic SiLA stand-in that records the commands sent by the DT."""

    commands: list[FlexCommand] = field(default_factory=list)
    machine_status_reads: int = 0
    closed: bool = False

    async def execute(self, command: FlexCommand) -> FlexResultValue:
        self.commands.append(command)
        if command.method == "PickUpTip":
            return FlexTipPresence.PRESENT
        if command.method == "GetTipPresence":
            return FlexTipPresence.PRESENT
        if command.method == "DropTip":
            return FlexTipPresence.ABSENT
        return None

    async def machine_status(self) -> FlexMachineStatus:
        self.machine_status_reads += 1
        return FlexMachineStatus(
            estop=FlexEStopState.DISENGAGED,
            door_open=False,
            is_error_state=False,
            message="simulated machine healthy",
        )

    async def close(self) -> None:
        self.closed = True


def _example_runner(
    transport: RecordingFlexTransport,
) -> tuple[FlexWorkflowRunner, ParsedWorkflow]:
    config = StaticFlexConfig.load_json(CONFIG)
    workflow = parse_workflow_json(WORKFLOW)
    adapter = FlexWorkflowAdapter(
        deck=config.deck_resolver(),
        instruments=config.instrument_resolver(),
    )
    return FlexWorkflowRunner(adapter=adapter, transport=transport), workflow


def test_example_workflow_compiles_to_expected_flex_sila_commands() -> None:
    transport = RecordingFlexTransport()
    runner, workflow = _example_runner(transport)

    compiled = runner.compile(workflow)

    assert [command.method for command in compiled.commands] == [
        "Home",
        "PickUpTip",
        "GetTipPresence",
        "DropTip",
    ]
    assert compiled.skipped_step_ids == []
    assert transport.commands == []

    pickup, drop = compiled.commands[1], compiled.commands[3]
    assert pickup.parameters["mount"] is FlexMount.RIGHT
    assert (
        pickup.parameters["location"]
        == DeckPoint(
            x=64.0,
            y=150.0,
            z=100.0,
        ).model_dump()
    )
    assert (
        drop.parameters["location"]
        == DeckPoint(
            x=392.0,
            y=150.0,
            z=100.0,
        ).model_dump()
    )


@pytest.mark.asyncio
async def test_example_workflow_runs_end_to_end_with_a_test_transport() -> None:
    transport = RecordingFlexTransport()
    runner, workflow = _example_runner(transport)

    result = await runner.run(workflow)
    await runner.close()

    assert result.completed is True
    assert [record.response for record in result.records] == [
        None,
        FlexTipPresence.PRESENT,
        FlexTipPresence.PRESENT,
        FlexTipPresence.ABSENT,
    ]
    assert transport.machine_status_reads == 3
    assert transport.closed is True


def test_example_calibration_is_deliberately_not_hardware_enabled() -> None:
    config = StaticFlexConfig.load_json(CONFIG)

    assert config.calibration_confirmed is False
