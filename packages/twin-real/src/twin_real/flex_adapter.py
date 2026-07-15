"""Adapt external ``robot.*`` workflow steps to Flex SiLA commands."""

from __future__ import annotations

import math
from dataclasses import dataclass

from twin_core.flex import (
    DeckPoint,
    FlexContractError,
    FlexDeckResolver,
    FlexInstrumentNotFound,
    FlexInstrumentResolver,
    FlexMount,
    WellAnchor,
)
from twin_core.workflow_parser import ParsedStep

from twin_real.flex_contract import FlexCommand, FlexExecutionMode, FlexFeature


class FlexStepError(FlexContractError):
    """An orchestrator step cannot be translated to the Flex contract."""

    def __init__(self, step_id: str, reason: str) -> None:
        self.step_id = step_id
        self.reason = reason
        super().__init__(f"Flex step {step_id!r}: {reason}")


FLEX_ACTIONS: frozenset[str] = frozenset(
    {
        "robot.home",
        "robot.home_mount",
        "robot.move_to",
        "robot.move_to_well",
        "robot.move_relative",
        "robot.get_position",
        "robot.pick_up_tip",
        "robot.drop_tip",
        "robot.get_tip_presence",
        "robot.prepare_for_aspirate",
        "robot.aspirate",
        "robot.dispense",
        "robot.blow_out",
        "robot.pause",
        "robot.resume",
        "robot.emergency_stop",
        "robot.set_lights",
        "robot.grip",
        "robot.ungrip",
        "robot.home_gripper_jaw",
        "robot.get_attached_pipettes",
        "robot.get_machine_status",
    }
)


@dataclass(frozen=True)
class FlexWorkflowAdapter:
    """Compile one parsed external workflow step into one SiLA invocation.

    Unsupported non-Flex steps return ``None`` so the mixed-instrument
    orchestrator remains the owner of PLC, potentiostat, and wait actions.
    Invalid Flex steps fail loudly instead of being silently skipped.
    """

    deck: FlexDeckResolver
    instruments: FlexInstrumentResolver

    def adapt(self, step: ParsedStep) -> FlexCommand | None:
        if step.device != "robot":
            if step.action in FLEX_ACTIONS:
                raise FlexStepError(
                    step.step_id,
                    f"action {step.action!r} conflicts with device {step.device!r}",
                )
            return None
        if step.action not in FLEX_ACTIONS:
            raise FlexStepError(
                step.step_id,
                f"unsupported Flex robot action {step.action!r}",
            )

        handlers = {
            "robot.home": self._home,
            "robot.home_mount": self._home_mount,
            "robot.move_to": self._move_to,
            "robot.move_to_well": self._move_to_well,
            "robot.move_relative": self._move_relative,
            "robot.get_position": self._get_position,
            "robot.pick_up_tip": self._pick_up_tip,
            "robot.drop_tip": self._drop_tip,
            "robot.get_tip_presence": self._get_tip_presence,
            "robot.prepare_for_aspirate": self._prepare_for_aspirate,
            "robot.aspirate": self._aspirate,
            "robot.dispense": self._dispense,
            "robot.blow_out": self._blow_out,
            "robot.pause": self._pause,
            "robot.resume": self._resume,
            "robot.emergency_stop": self._emergency_stop,
            "robot.set_lights": self._set_lights,
            "robot.grip": self._grip,
            "robot.ungrip": self._ungrip,
            "robot.home_gripper_jaw": self._home_gripper_jaw,
            "robot.get_attached_pipettes": self._get_attached_pipettes,
            "robot.get_machine_status": self._get_machine_status,
        }
        return handlers[step.action](step)

    def _command(
        self,
        step: ParsedStep,
        feature: FlexFeature,
        method: str,
        parameters: dict[str, object] | None = None,
        *,
        mode: FlexExecutionMode = FlexExecutionMode.OBSERVABLE,
        verify: bool = False,
    ) -> FlexCommand:
        return FlexCommand(
            step_id=step.step_id,
            action=step.action,
            feature=feature,
            method=method,
            parameters=parameters or {},
            execution_mode=mode,
            verify_machine_status=verify,
        )

    def _home(self, step: ParsedStep) -> FlexCommand:
        return self._command(step, FlexFeature.MOTION_CONTROL, "Home", verify=True)

    def _home_mount(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "HomeMount",
            {"mount": self._mount(step)},
            verify=True,
        )

    def _move_to(self, step: ParsedStep) -> FlexCommand:
        point = DeckPoint(
            x=self._number(step, "x"),
            y=self._number(step, "y"),
            z=self._number(step, "z"),
        )
        return self._move_command(step, point)

    def _move_to_well(self, step: ParsedStep) -> FlexCommand:
        point = self._resolve_location(step)
        return self._move_command(step, point)

    def _move_command(
        self,
        step: ParsedStep,
        point: DeckPoint,
    ) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "MoveTo",
            {
                "mount": self._mount(step),
                "x": point.x,
                "y": point.y,
                "z": point.z,
                "speed": self._nonnegative(step, "speed", 0.0),
            },
            verify=True,
        )

    def _move_relative(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "MoveRelative",
            {
                "mount": self._mount(step),
                "delta_x": self._optional_number(step, "delta_x", 0.0),
                "delta_y": self._optional_number(step, "delta_y", 0.0),
                "delta_z": self._optional_number(step, "delta_z", 0.0),
                "speed": self._nonnegative(step, "speed", 0.0),
            },
            verify=True,
        )

    def _get_position(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "GetPosition",
            {"mount": self._mount(step)},
        )

    def _pick_up_tip(self, step: ParsedStep) -> FlexCommand:
        labware, well = self._labware_well(step)
        tip_length = step.params.get("tip_length_mm")
        if tip_length is None:
            tip_length = self.deck.tip_length_mm(labware, well)
        if tip_length is None:
            raise FlexStepError(
                step.step_id,
                "pick_up_tip requires tip_length_mm or resolver tip geometry",
            )
        tip_length_value = self._finite_value(step, "tip_length_mm", tip_length)
        if not 0.0 < tip_length_value <= 100.0:
            raise FlexStepError(
                step.step_id,
                "tip_length_mm must be greater than 0 and at most 100",
            )
        point = self._resolve_location(step)
        return self._command(
            step,
            FlexFeature.TIP_CONTROLLER,
            "PickUpTip",
            {
                "mount": self._pipette_mount(step),
                "location": point.model_dump(),
                "tip_length": tip_length_value,
                "prep_after": self._boolean(step, "prep_after", False),
            },
            verify=True,
        )

    def _drop_tip(self, step: ParsedStep) -> FlexCommand:
        point = self._resolve_location(step)
        return self._command(
            step,
            FlexFeature.TIP_CONTROLLER,
            "DropTip",
            {
                "mount": self._pipette_mount(step),
                "location": point.model_dump(),
                "home_after": self._boolean(step, "home_after", False),
            },
            verify=True,
        )

    def _get_tip_presence(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.TIP_CONTROLLER,
            "GetTipPresence",
            {"mount": self._pipette_mount(step)},
            mode=FlexExecutionMode.UNOBSERVABLE,
        )

    def _prepare_for_aspirate(self, step: ParsedStep) -> FlexCommand:
        return self._mount_motion(step, "PrepareForAspirate")

    def _aspirate(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "Aspirate",
            {
                "mount": self._pipette_mount(step),
                "volume": self._nonnegative_alias(step, "volume_ul", "volume"),
                "rate": self._positive(step, "rate", 1.0),
            },
            verify=True,
        )

    def _dispense(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "Dispense",
            {
                "mount": self._pipette_mount(step),
                "volume": self._nonnegative_alias(step, "volume_ul", "volume"),
                "rate": self._positive(step, "rate", 1.0),
                "push_out": self._nonnegative(step, "push_out_ul", 0.0),
            },
            verify=True,
        )

    def _blow_out(self, step: ParsedStep) -> FlexCommand:
        return self._mount_motion(step, "BlowOut")

    def _mount_motion(self, step: ParsedStep, method: str) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            method,
            {"mount": self._pipette_mount(step)},
            verify=True,
        )

    def _pause(self, step: ParsedStep) -> FlexCommand:
        return self._command(step, FlexFeature.MOTION_CONTROL, "Pause")

    def _resume(self, step: ParsedStep) -> FlexCommand:
        return self._command(step, FlexFeature.MOTION_CONTROL, "Resume")

    def _emergency_stop(self, step: ParsedStep) -> FlexCommand:
        return self._command(step, FlexFeature.MOTION_CONTROL, "EmergencyStop")

    def _set_lights(self, step: ParsedStep) -> FlexCommand:
        on = self._boolean(step, "on", True)
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "SetLights",
            {
                "button": self._boolean(step, "button", on),
                "rails": self._boolean(step, "rails", on),
            },
        )

    def _grip(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.GRIPPER,
            "Grip",
            {"force": self._range(step, "force_n", 5.0, 5.0, 25.0)},
            verify=True,
        )

    def _ungrip(self, step: ParsedStep) -> FlexCommand:
        return self._command(step, FlexFeature.GRIPPER, "Ungrip", verify=True)

    def _home_gripper_jaw(self, step: ParsedStep) -> FlexCommand:
        return self._command(step, FlexFeature.GRIPPER, "HomeJaw", verify=True)

    def _get_attached_pipettes(self, step: ParsedStep) -> FlexCommand:
        return self._command(step, FlexFeature.PIPETTE, "GetAttachedPipettes")

    def _get_machine_status(self, step: ParsedStep) -> FlexCommand:
        return self._command(
            step,
            FlexFeature.MOTION_CONTROL,
            "Get_MachineStatus",
            mode=FlexExecutionMode.PROPERTY,
        )

    def _resolve_location(self, step: ParsedStep) -> DeckPoint:
        labware, well = self._labware_well(step)
        anchor = self._anchor(step)
        return self.deck.resolve(
            labware,
            well,
            anchor,
            offset_x_mm=self._optional_number(step, "offset_x", 0.0),
            offset_y_mm=self._optional_number(step, "offset_y", 0.0),
            offset_z_mm=self._optional_number(step, "offset_z", 0.0),
        )

    def _labware_well(self, step: ParsedStep) -> tuple[str, str]:
        return self._string(step, "labware"), self._string(step, "well")

    def _anchor(self, step: ParsedStep) -> WellAnchor:
        raw = step.params.get("offset_start", WellAnchor.TOP.value)
        if isinstance(raw, WellAnchor):
            return raw
        try:
            return WellAnchor(str(raw).lower())
        except ValueError:
            allowed = ", ".join(anchor.value for anchor in WellAnchor)
            raise FlexStepError(
                step.step_id,
                f"offset_start must be one of: {allowed}",
            ) from None

    def _mount(self, step: ParsedStep) -> FlexMount:
        raw = step.params.get("mount")
        if raw is not None:
            if isinstance(raw, FlexMount):
                return raw
            try:
                return FlexMount(str(raw).upper())
            except ValueError:
                raise FlexStepError(
                    step.step_id,
                    f"unknown Flex mount {raw!r}",
                ) from None
        return self._pipette_mount(step)

    def _pipette_mount(self, step: ParsedStep) -> FlexMount:
        instrument = self._string(step, "pipette")
        try:
            mount = self.instruments.mount_for(instrument)
        except FlexInstrumentNotFound as exc:
            raise FlexStepError(step.step_id, str(exc)) from exc
        if mount is FlexMount.GRIPPER:
            raise FlexStepError(
                step.step_id,
                f"pipette {instrument!r} resolves to the gripper mount",
            )
        return mount

    def _string(self, step: ParsedStep, key: str) -> str:
        value = step.params.get(key)
        if not isinstance(value, str) or not value:
            raise FlexStepError(step.step_id, f"requires non-empty string {key!r}")
        return value

    def _number(self, step: ParsedStep, key: str) -> float:
        if key not in step.params:
            raise FlexStepError(step.step_id, f"requires numeric {key!r}")
        return self._finite_value(step, key, step.params[key])

    def _number_alias(self, step: ParsedStep, preferred: str, fallback: str) -> float:
        if preferred in step.params:
            return self._finite_value(step, preferred, step.params[preferred])
        return self._number(step, fallback)

    def _nonnegative_alias(
        self, step: ParsedStep, preferred: str, fallback: str
    ) -> float:
        value = self._number_alias(step, preferred, fallback)
        if value < 0:
            raise FlexStepError(step.step_id, f"{preferred!r} must be non-negative")
        return value

    def _optional_number(self, step: ParsedStep, key: str, default: float) -> float:
        return self._finite_value(step, key, step.params.get(key, default))

    def _nonnegative(self, step: ParsedStep, key: str, default: float) -> float:
        value = self._optional_number(step, key, default)
        if value < 0:
            raise FlexStepError(step.step_id, f"{key!r} must be non-negative")
        return value

    def _positive(self, step: ParsedStep, key: str, default: float) -> float:
        value = self._optional_number(step, key, default)
        if value <= 0:
            raise FlexStepError(step.step_id, f"{key!r} must be greater than zero")
        return value

    def _range(
        self,
        step: ParsedStep,
        key: str,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        value = self._optional_number(step, key, default)
        if not minimum <= value <= maximum:
            raise FlexStepError(
                step.step_id,
                f"{key!r} must be between {minimum:g} and {maximum:g}",
            )
        return value

    def _finite_value(self, step: ParsedStep, key: str, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FlexStepError(step.step_id, f"{key!r} must be numeric")
        converted = float(value)
        if not math.isfinite(converted):
            raise FlexStepError(step.step_id, f"{key!r} must be finite")
        return converted

    def _boolean(self, step: ParsedStep, key: str, default: bool) -> bool:
        value = step.params.get(key, default)
        if not isinstance(value, bool):
            raise FlexStepError(step.step_id, f"{key!r} must be boolean")
        return value
