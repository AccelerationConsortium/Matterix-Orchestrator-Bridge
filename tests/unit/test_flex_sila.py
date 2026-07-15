"""Offline tests for raw SiLA observable and property calls."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

import pytest

from twin_real import (
    FLEX_FEATURE_ENDPOINTS,
    FlexCommand,
    FlexEStopState,
    FlexExecutionMode,
    FlexFeature,
    FlexMachineStatus,
    FlexSiLACommandError,
    FlexSiLACommandTimeout,
    FlexSiLAContractError,
    FlexSiLATransport,
    FlexTipPresence,
)


class FakeCodec:
    def __init__(self) -> None:
        self.encoded: list[tuple[str, dict[str, object]]] = []
        self.decoded: list[tuple[str, bytes]] = []

    async def encode(self, path: str, value: dict[str, object]) -> bytes:
        self.encoded.append((path, value))
        return b"encoded"

    async def decode(self, path: str, buffer: bytes) -> dict[str, object]:
        self.decoded.append((path, buffer))
        if path.endswith("Get_MachineStatus_Responses"):
            return {
                "MachineStatus": {
                    "estop": "DISENGAGED",
                    "door_open": False,
                    "is_error_state": False,
                    "message": "ok",
                }
            }
        if path.endswith("GetTipPresence_Responses"):
            return {"TipPresence": "PRESENT"}
        return {"Response": "done"}


class FakeWire:
    def decode_confirmation(self, payload: bytes) -> str:
        assert payload == b"confirmation"
        return "uuid-1"

    def encode_execution_uuid(self, value: str) -> bytes:
        assert value == "uuid-1"
        return b"uuid"


@dataclass
class FakeCode:
    name: str


class FakeRpcError(Exception):
    def __init__(self, code: str, details: str) -> None:
        self._code = FakeCode(code)
        self._details = base64.b64encode(details.encode()).decode()
        super().__init__(details)

    def code(self) -> FakeCode:
        return self._code

    def details(self) -> str:
        return self._details


@dataclass
class FakeCall:
    responses: list[bytes | Exception]
    requests: list[bytes] = field(default_factory=list)

    async def __call__(self, request: bytes) -> bytes:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeChannel:
    def __init__(self, calls: dict[str, FakeCall]) -> None:
        self.calls = calls
        self.paths: list[str] = []
        self.closed = False

    def unary_unary(self, path: str) -> FakeCall:
        self.paths.append(path)
        return self.calls[path]

    async def close(self) -> None:
        self.closed = True


def _observable_command() -> FlexCommand:
    return FlexCommand(
        step_id="home",
        action="robot.home",
        feature=FlexFeature.MOTION_CONTROL,
        method="Home",
        execution_mode=FlexExecutionMode.OBSERVABLE,
    )


@pytest.mark.asyncio
async def test_observable_command_polls_until_result_is_ready() -> None:
    package = FLEX_FEATURE_ENDPOINTS[FlexFeature.MOTION_CONTROL].package
    service = f"{package}.MotionControlFeature"
    start_path = f"/{service}/Home"
    result_path = f"/{service}/Home_Result"
    channel = FakeChannel(
        {
            start_path: FakeCall([b"confirmation"]),
            result_path: FakeCall(
                [
                    FakeRpcError("ABORTED", "Result is not ready"),
                    b"result",
                ]
            ),
        }
    )
    codec = FakeCodec()
    transport = FlexSiLATransport(
        channel=channel,
        codec=codec,
        wire=FakeWire(),
        poll_interval_s=0.0001,
    )

    response = await transport.execute(_observable_command())

    assert response is None
    assert channel.calls[result_path].requests == [b"uuid", b"uuid"]
    assert codec.encoded == [(f"{package}.Home_Parameters", {})]
    assert codec.decoded == [(f"{package}.Home_Responses", b"result")]


@pytest.mark.asyncio
async def test_unobservable_tip_query_uses_immediate_command_shape() -> None:
    package = FLEX_FEATURE_ENDPOINTS[FlexFeature.TIP_CONTROLLER].package
    service = f"{package}.TipController"
    path = f"/{service}/GetTipPresence"
    channel = FakeChannel({path: FakeCall([b"presence"])})
    codec = FakeCodec()
    transport = FlexSiLATransport(channel=channel, codec=codec, wire=FakeWire())
    command = FlexCommand(
        step_id="tip",
        action="robot.get_tip_presence",
        feature=FlexFeature.TIP_CONTROLLER,
        method="GetTipPresence",
        parameters={"mount": "LEFT"},
        execution_mode=FlexExecutionMode.UNOBSERVABLE,
    )

    result = await transport.execute(command)

    assert result is FlexTipPresence.PRESENT
    assert codec.encoded == [
        (f"{package}.GetTipPresence_Parameters", {"mount": "LEFT"})
    ]
    assert channel.calls[path].requests == [b"encoded"]


@pytest.mark.asyncio
async def test_machine_status_property_is_decoded_without_parameters() -> None:
    package = FLEX_FEATURE_ENDPOINTS[FlexFeature.MOTION_CONTROL].package
    service = f"{package}.MotionControlFeature"
    path = f"/{service}/Get_MachineStatus"
    channel = FakeChannel({path: FakeCall([b"status"])})
    codec = FakeCodec()
    transport = FlexSiLATransport(channel=channel, codec=codec, wire=FakeWire())

    status = await transport.machine_status()

    assert status == FlexMachineStatus(
        estop=FlexEStopState.DISENGAGED,
        door_open=False,
        is_error_state=False,
        message="ok",
    )
    assert codec.encoded == []
    assert channel.calls[path].requests == [b""]


@pytest.mark.asyncio
async def test_defined_execution_error_keeps_decoded_sila_details() -> None:
    package = FLEX_FEATURE_ENDPOINTS[FlexFeature.MOTION_CONTROL].package
    service = f"{package}.MotionControlFeature"
    path = f"/{service}/Home"
    channel = FakeChannel(
        {path: FakeCall([FakeRpcError("ABORTED", "NotHomedError: recover")])}
    )
    transport = FlexSiLATransport(
        channel=channel,
        codec=FakeCodec(),
        wire=FakeWire(),
    )

    with pytest.raises(FlexSiLACommandError, match="NotHomedError"):
        await transport.execute(_observable_command())


@pytest.mark.asyncio
async def test_unknown_method_is_rejected_before_rpc_path_construction() -> None:
    transport = FlexSiLATransport(
        channel=FakeChannel({}),
        codec=FakeCodec(),
        wire=FakeWire(),
    )
    command = FlexCommand(
        step_id="bad",
        action="robot.bad",
        feature=FlexFeature.MOTION_CONTROL,
        method="Home/../../EmergencyStop",
    )

    with pytest.raises(FlexSiLAContractError, match="not allowed"):
        await transport.execute(command)


@pytest.mark.asyncio
async def test_wrong_execution_mode_is_rejected_before_rpc() -> None:
    transport = FlexSiLATransport(
        channel=FakeChannel({}),
        codec=FakeCodec(),
        wire=FakeWire(),
    )
    command = _observable_command().model_copy(
        update={"execution_mode": FlexExecutionMode.UNOBSERVABLE}
    )

    with pytest.raises(FlexSiLAContractError, match="expected observable"):
        await transport.execute(command)


@pytest.mark.asyncio
async def test_malformed_connector_response_is_not_silently_defaulted() -> None:
    package = FLEX_FEATURE_ENDPOINTS[FlexFeature.MOTION_CONTROL].package
    service = f"{package}.MotionControlFeature"
    start_path = f"/{service}/GetPosition"
    result_path = f"/{service}/GetPosition_Result"
    channel = FakeChannel(
        {
            start_path: FakeCall([b"confirmation"]),
            result_path: FakeCall([b"result"]),
        }
    )

    class MissingCoordinateCodec(FakeCodec):
        async def decode(self, path: str, buffer: bytes) -> dict[str, object]:
            return {"Position": {"x": 1.0, "y": 2.0}}

    transport = FlexSiLATransport(
        channel=channel,
        codec=MissingCoordinateCodec(),
        wire=FakeWire(),
    )
    command = FlexCommand(
        step_id="position",
        action="robot.get_position",
        feature=FlexFeature.MOTION_CONTROL,
        method="GetPosition",
        parameters={"mount": "LEFT"},
    )

    with pytest.raises(FlexSiLAContractError, match="missing field 'z'"):
        await transport.execute(command)


@pytest.mark.asyncio
async def test_observable_result_call_has_a_real_deadline() -> None:
    package = FLEX_FEATURE_ENDPOINTS[FlexFeature.MOTION_CONTROL].package
    service = f"{package}.MotionControlFeature"
    start_path = f"/{service}/Home"
    result_path = f"/{service}/Home_Result"

    class HangingCall:
        async def __call__(self, request: bytes) -> bytes:
            await __import__("asyncio").sleep(60)
            return b"never"

    channel = FakeChannel({start_path: FakeCall([b"confirmation"])})
    channel.calls[result_path] = HangingCall()
    transport = FlexSiLATransport(
        channel=channel,
        codec=FakeCodec(),
        wire=FakeWire(),
        timeout_s=0.01,
    )

    with pytest.raises(FlexSiLACommandTimeout, match="result not received"):
        await transport.execute(_observable_command())


@pytest.mark.asyncio
async def test_close_closes_channel() -> None:
    channel = FakeChannel({})
    transport = FlexSiLATransport(
        channel=channel,
        codec=FakeCodec(),
        wire=FakeWire(),
    )

    await transport.close()

    assert channel.closed is True


def test_feature_endpoints_match_flex_connector_fqns() -> None:
    assert FLEX_FEATURE_ENDPOINTS[FlexFeature.MOTION_CONTROL].package == (
        "sila2.ca.accelerationconsortium.robots.motioncontrolfeature.v1"
    )
    assert FLEX_FEATURE_ENDPOINTS[FlexFeature.TIP_CONTROLLER].package == (
        "sila2.ca.accelerationconsortium.robots.tipcontroller.v1"
    )
    assert FLEX_FEATURE_ENDPOINTS[FlexFeature.GRIPPER].service == "GripperFeature"
    assert FLEX_FEATURE_ENDPOINTS[FlexFeature.PIPETTE].service == "PipetteFeature"
