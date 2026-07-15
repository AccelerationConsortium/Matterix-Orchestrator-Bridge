"""Tests for external workflow step to Flex SiLA command adaptation."""

from __future__ import annotations

import pytest

from twin_core import (
    DeckPoint,
    FlexMount,
    StaticFlexDeckResolver,
    StaticFlexInstrumentResolver,
    WellAnchor,
)
from twin_core.workflow_parser import ParsedStep
from twin_real import (
    FLEX_ACTIONS,
    FlexExecutionMode,
    FlexFeature,
    FlexStepError,
    FlexWorkflowAdapter,
)


@pytest.fixture
def adapter() -> FlexWorkflowAdapter:
    deck = StaticFlexDeckResolver(
        anchors={
            ("electrode_tip_rack", "A2", WellAnchor.TOP): DeckPoint(
                x=100.0,
                y=50.0,
                z=20.0,
            ),
            ("wash_station", "A1", WellAnchor.TOP): DeckPoint(
                x=200.0,
                y=60.0,
                z=10.0,
            ),
        },
        tip_lengths_mm={("electrode_tip_rack", "A2"): 95.6},
    )
    instruments = StaticFlexInstrumentResolver({"p1000_single_gen2": FlexMount.RIGHT})
    return FlexWorkflowAdapter(deck=deck, instruments=instruments)


def _step(action: str, params: dict | None = None, step_id: str = "s1") -> ParsedStep:
    return ParsedStep(
        step_id=step_id,
        action=action,
        device="robot",
        params=params or {},
        description="",
        category="sim",
        estimated_duration_s=None,
    )


def test_move_to_well_resolves_asset_anchor_and_offsets(
    adapter: FlexWorkflowAdapter,
) -> None:
    command = adapter.adapt(
        _step(
            "robot.move_to_well",
            {
                "labware": "electrode_tip_rack",
                "well": "A2",
                "pipette": "p1000_single_gen2",
                "offset_start": "top",
                "offset_x": -6.3,
                "offset_y": 1.5,
                "offset_z": 17.0,
                "speed": 200,
            },
        )
    )

    assert command is not None
    assert command.feature is FlexFeature.MOTION_CONTROL
    assert command.method == "MoveTo"
    assert command.parameters == {
        "mount": FlexMount.RIGHT,
        "x": 93.7,
        "y": 51.5,
        "z": 37.0,
        "speed": 200.0,
    }
    assert command.verify_machine_status is True


def test_pick_up_tip_matches_tip_controller_contract(
    adapter: FlexWorkflowAdapter,
) -> None:
    command = adapter.adapt(
        _step(
            "robot.pick_up_tip",
            {
                "labware": "electrode_tip_rack",
                "well": "A2",
                "pipette": "p1000_single_gen2",
                "offset_z": -3.0,
            },
        )
    )

    assert command is not None
    assert command.feature is FlexFeature.TIP_CONTROLLER
    assert command.method == "PickUpTip"
    assert command.execution_mode is FlexExecutionMode.OBSERVABLE
    assert command.parameters == {
        "mount": FlexMount.RIGHT,
        "location": {"x": 100.0, "y": 50.0, "z": 17.0},
        "tip_length": 95.6,
        "prep_after": False,
    }


def test_drop_tip_and_presence_use_correct_execution_modes(
    adapter: FlexWorkflowAdapter,
) -> None:
    drop = adapter.adapt(
        _step(
            "robot.drop_tip",
            {
                "labware": "wash_station",
                "well": "A1",
                "pipette": "p1000_single_gen2",
            },
        )
    )
    presence = adapter.adapt(
        _step(
            "robot.get_tip_presence",
            {"pipette": "p1000_single_gen2"},
        )
    )

    assert drop is not None and drop.method == "DropTip"
    assert drop.execution_mode is FlexExecutionMode.OBSERVABLE
    assert presence is not None and presence.method == "GetTipPresence"
    assert presence.execution_mode is FlexExecutionMode.UNOBSERVABLE


@pytest.mark.parametrize(
    ("action", "method"),
    [
        ("robot.home", "Home"),
        ("robot.pause", "Pause"),
        ("robot.resume", "Resume"),
        ("robot.emergency_stop", "EmergencyStop"),
        ("robot.ungrip", "Ungrip"),
        ("robot.home_gripper_jaw", "HomeJaw"),
        ("robot.get_attached_pipettes", "GetAttachedPipettes"),
    ],
)
def test_parameterless_actions_are_covered(
    adapter: FlexWorkflowAdapter,
    action: str,
    method: str,
) -> None:
    command = adapter.adapt(_step(action))
    assert command is not None
    assert command.method == method


def test_liquid_commands_preserve_volume_units(adapter: FlexWorkflowAdapter) -> None:
    aspirate = adapter.adapt(
        _step(
            "robot.aspirate",
            {
                "pipette": "p1000_single_gen2",
                "volume_ul": 20,
                "rate": 0.5,
            },
        )
    )
    dispense = adapter.adapt(
        _step(
            "robot.dispense",
            {
                "pipette": "p1000_single_gen2",
                "volume": 20,
                "push_out_ul": 2,
            },
        )
    )

    assert aspirate is not None
    assert aspirate.parameters["volume"] == 20.0
    assert aspirate.parameters["rate"] == 0.5
    assert dispense is not None
    assert dispense.parameters["volume"] == 20.0
    assert dispense.parameters["push_out"] == 2.0


@pytest.mark.parametrize(
    ("action", "params", "message"),
    [
        (
            "robot.aspirate",
            {"pipette": "p1000_single_gen2", "volume_ul": -1},
            "non-negative",
        ),
        (
            "robot.dispense",
            {"pipette": "p1000_single_gen2", "volume_ul": 1, "rate": 0},
            "greater than zero",
        ),
        (
            "robot.grip",
            {"force_n": 26},
            "between 5 and 25",
        ),
    ],
)
def test_fdl_numeric_constraints_fail_during_dt_preflight(
    adapter: FlexWorkflowAdapter,
    action: str,
    params: dict,
    message: str,
) -> None:
    with pytest.raises(FlexStepError, match=message):
        adapter.adapt(_step(action, params))


def test_pick_up_tip_without_geometry_fails_before_hardware() -> None:
    adapter = FlexWorkflowAdapter(
        deck=StaticFlexDeckResolver(
            anchors={("rack", "A1", WellAnchor.TOP): DeckPoint(x=1, y=2, z=3)}
        ),
        instruments=StaticFlexInstrumentResolver({"pip": FlexMount.LEFT}),
    )

    with pytest.raises(FlexStepError, match="tip_length_mm"):
        adapter.adapt(
            _step(
                "robot.pick_up_tip",
                {"labware": "rack", "well": "A1", "pipette": "pip"},
            )
        )


def test_unknown_non_flex_action_is_left_for_other_executor(
    adapter: FlexWorkflowAdapter,
) -> None:
    step = _step("plc.dispense_ml")
    step.device = "plc"
    assert adapter.adapt(step) is None


def test_unknown_robot_action_fails_instead_of_being_skipped(
    adapter: FlexWorkflowAdapter,
) -> None:
    with pytest.raises(FlexStepError, match="unsupported Flex robot action"):
        adapter.adapt(_step("robot.pickup_tip_typo"))


def test_robot_action_with_conflicting_device_fails(
    adapter: FlexWorkflowAdapter,
) -> None:
    step = _step("robot.home")
    step.device = "plc"

    with pytest.raises(FlexStepError, match="conflicts with device"):
        adapter.adapt(step)


def test_all_declared_flex_actions_have_adapter_handlers(
    adapter: FlexWorkflowAdapter,
) -> None:
    assert "robot.pick_up_tip" in FLEX_ACTIONS
    assert "robot.get_machine_status" in FLEX_ACTIONS
    assert len(FLEX_ACTIONS) == 22
