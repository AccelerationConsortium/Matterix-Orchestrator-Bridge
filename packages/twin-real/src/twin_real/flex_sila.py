"""Async SiLA 2 transport for the Opentrons Flex connector.

The transport deliberately depends on small structural protocols so unit tests
remain offline.  ``connect()`` imports gRPC and the connector codec lazily;
normal imports of ``twin_real`` therefore do not require Flex dependencies.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import math
from typing import Any, Awaitable, Callable, Mapping, Protocol

from twin_core.flex import DeckPoint, FlexMount

from twin_real.flex_contract import (
    FlexCommand,
    FlexEStopState,
    FlexExecutionMode,
    FlexFeature,
    FlexLightsState,
    FlexMachineStatus,
    FlexPipetteInfo,
    FlexResultValue,
    FlexTipPresence,
)


class FlexSiLAError(RuntimeError):
    """Base error for Flex SiLA transport failures."""


class FlexSiLADependencyError(FlexSiLAError):
    """Optional SiLA client dependencies or the connector codec are absent."""


class FlexSiLAConnectionError(FlexSiLAError):
    """The client could not establish or maintain a connector connection."""


class FlexSiLACommandError(FlexSiLAError):
    """The connector rejected or failed a command."""

    def __init__(self, command: FlexCommand, details: str) -> None:
        self.command = command
        self.details = details
        super().__init__(
            f"Flex SiLA {command.method} failed for step {command.step_id!r}: {details}"
        )


class FlexSiLACommandTimeout(FlexSiLACommandError):
    """An observable command did not produce a result before its deadline."""


class FlexSiLAContractError(FlexSiLACommandError):
    """A command does not belong to the pinned Flex SiLA client contract."""


class FlexMachineError(FlexSiLAError):
    """Post-command MachineStatus reports a hardware safety/error state."""

    def __init__(self, status: "FlexMachineStatus") -> None:
        self.status = status
        super().__init__(
            "Flex entered an error state after a command: "
            f"estop={status.estop.value}, door_open={status.door_open}, "
            f"message={status.message!r}"
        )


@dataclass(frozen=True)
class FlexFeatureEndpoint:
    """Raw gRPC package and service names generated from a SiLA FDL."""

    package: str
    service: str


FLEX_FEATURE_ENDPOINTS: Mapping[FlexFeature, FlexFeatureEndpoint] = {
    FlexFeature.MOTION_CONTROL: FlexFeatureEndpoint(
        package="sila2.ca.accelerationconsortium.robots.motioncontrolfeature.v1",
        service="MotionControlFeature",
    ),
    FlexFeature.TIP_CONTROLLER: FlexFeatureEndpoint(
        package="sila2.ca.accelerationconsortium.robots.tipcontroller.v1",
        service="TipController",
    ),
    FlexFeature.GRIPPER: FlexFeatureEndpoint(
        package="sila2.ca.accelerationconsortium.robots.gripperfeature.v1",
        service="GripperFeature",
    ),
    FlexFeature.PIPETTE: FlexFeatureEndpoint(
        package="sila2.ca.accelerationconsortium.robots.pipettefeature.v1",
        service="PipetteFeature",
    ),
}

FLEX_SILA_METHODS: Mapping[
    FlexFeature,
    Mapping[str, FlexExecutionMode],
] = {
    FlexFeature.MOTION_CONTROL: {
        "Home": FlexExecutionMode.OBSERVABLE,
        "HomeMount": FlexExecutionMode.OBSERVABLE,
        "MoveTo": FlexExecutionMode.OBSERVABLE,
        "MoveRelative": FlexExecutionMode.OBSERVABLE,
        "GetPosition": FlexExecutionMode.OBSERVABLE,
        "PrepareForAspirate": FlexExecutionMode.OBSERVABLE,
        "Aspirate": FlexExecutionMode.OBSERVABLE,
        "Dispense": FlexExecutionMode.OBSERVABLE,
        "BlowOut": FlexExecutionMode.OBSERVABLE,
        "EmergencyStop": FlexExecutionMode.OBSERVABLE,
        "Pause": FlexExecutionMode.OBSERVABLE,
        "Resume": FlexExecutionMode.OBSERVABLE,
        "SetLights": FlexExecutionMode.OBSERVABLE,
        "Get_MachineStatus": FlexExecutionMode.PROPERTY,
    },
    FlexFeature.TIP_CONTROLLER: {
        "PickUpTip": FlexExecutionMode.OBSERVABLE,
        "DropTip": FlexExecutionMode.OBSERVABLE,
        "GetTipPresence": FlexExecutionMode.UNOBSERVABLE,
    },
    FlexFeature.GRIPPER: {
        "Grip": FlexExecutionMode.OBSERVABLE,
        "Ungrip": FlexExecutionMode.OBSERVABLE,
        "HomeJaw": FlexExecutionMode.OBSERVABLE,
    },
    FlexFeature.PIPETTE: {
        "GetAttachedPipettes": FlexExecutionMode.OBSERVABLE,
    },
}


class FlexProtobufCodec(Protocol):
    """Subset of the Unitelabs protobuf codec needed by this client."""

    async def encode(self, path: str, value: dict[str, object]) -> bytes: ...

    async def decode(self, path: str, buffer: bytes) -> dict[str, object]: ...


class UnaryCallable(Protocol):
    def __call__(self, request: bytes) -> Awaitable[bytes]: ...


class FlexGrpcChannel(Protocol):
    """Structural subset of ``grpc.aio.Channel`` used by the transport."""

    def unary_unary(self, path: str) -> UnaryCallable: ...

    async def close(self) -> None: ...


class SiLACommandWire(Protocol):
    """Encode/decode the standard observable-command envelope."""

    def decode_confirmation(self, payload: bytes) -> str: ...

    def encode_execution_uuid(self, value: str) -> bytes: ...


class StandardSiLACommandWire:
    """Observable-command envelope backed by ``unitelabs-sila``."""

    def decode_confirmation(self, payload: bytes) -> str:
        try:
            from sila.server import CommandConfirmation
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise FlexSiLADependencyError(
                "unitelabs-sila is required for observable Flex commands"
            ) from exc
        confirmation = CommandConfirmation.decode(payload)
        return confirmation.command_execution_uuid.value

    def encode_execution_uuid(self, value: str) -> bytes:
        try:
            from sila.server import CommandExecutionUUID
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise FlexSiLADependencyError(
                "unitelabs-sila is required for observable Flex commands"
            ) from exc
        return CommandExecutionUUID(value=value).encode()


@dataclass
class _ConnectorCodecOwner:
    generator: Any

    async def close(self) -> None:
        await self.generator.aclose()


@dataclass
class FlexSiLATransport:
    """Execute typed Flex commands against a SiLA 2 gRPC server."""

    channel: FlexGrpcChannel
    codec: FlexProtobufCodec
    timeout_s: float = 60.0
    poll_interval_s: float = 0.05
    wire: SiLACommandWire | None = None
    codec_owner: _ConnectorCodecOwner | None = None

    def __post_init__(self) -> None:
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be greater than zero")
        if self.wire is None:
            self.wire = StandardSiLACommandWire()

    @classmethod
    async def connect(
        cls,
        host: str,
        port: int = 50051,
        *,
        tls: bool = False,
        root_certificates: bytes | None = None,
        codec: FlexProtobufCodec | None = None,
        timeout_s: float = 60.0,
        connect_timeout_s: float = 10.0,
        poll_interval_s: float = 0.05,
    ) -> "FlexSiLATransport":
        """Open a ready gRPC channel and prepare the Flex protobuf codec.

        When ``codec`` is omitted, the installed
        ``unitelabs-opentrons-flex`` package is used to compile the connector's
        exact feature definitions locally.  This matches the connector's own
        smoke-client strategy and prevents hand-written protobuf drift.
        """
        if not host:
            raise ValueError("host must not be empty")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if connect_timeout_s <= 0:
            raise ValueError("connect_timeout_s must be greater than zero")

        try:
            import grpc
            import grpc.aio
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise FlexSiLADependencyError(
                "grpcio is required; install the twin-real 'flex' extra"
            ) from exc

        owner: _ConnectorCodecOwner | None = None
        if codec is None:
            codec, owner = await _build_connector_codec()

        address = f"{host}:{port}"
        if tls:
            credentials = grpc.ssl_channel_credentials(
                root_certificates=root_certificates
            )
            channel = grpc.aio.secure_channel(address, credentials)
        else:
            channel = grpc.aio.insecure_channel(address)

        try:
            await asyncio.wait_for(channel.channel_ready(), connect_timeout_s)
        except Exception as exc:
            await channel.close()
            if owner is not None:
                await owner.close()
            raise FlexSiLAConnectionError(
                f"Could not connect to Flex SiLA server at {address}"
            ) from exc

        return cls(
            channel=channel,
            codec=codec,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            codec_owner=owner,
        )

    async def execute(self, command: FlexCommand) -> FlexResultValue:
        """Execute one observable command, unobservable command, or property."""
        expected_mode = FLEX_SILA_METHODS[command.feature].get(command.method)
        if expected_mode is None:
            raise FlexSiLAContractError(
                command,
                f"method is not allowed for {command.feature.value}",
            )
        if command.execution_mode is not expected_mode:
            raise FlexSiLAContractError(
                command,
                f"expected {expected_mode.value}, got {command.execution_mode.value}",
            )
        endpoint = FLEX_FEATURE_ENDPOINTS[command.feature]
        if command.execution_mode is FlexExecutionMode.OBSERVABLE:
            decoded = await self._call_observable(endpoint, command)
        else:
            decoded = await self._call_immediate(endpoint, command)
        return _normalize_response(command, decoded)

    async def machine_status(self) -> FlexMachineStatus:
        """Read the standard post-motion safety property."""
        command = FlexCommand(
            step_id="__machine_status__",
            action="robot.get_machine_status",
            feature=FlexFeature.MOTION_CONTROL,
            method="Get_MachineStatus",
            execution_mode=FlexExecutionMode.PROPERTY,
        )
        status = await self.execute(command)
        if not isinstance(status, FlexMachineStatus):
            raise FlexSiLACommandError(command, "invalid MachineStatus response")
        return status

    async def close(self) -> None:
        """Close the remote channel and any local codec provider."""
        try:
            await self.channel.close()
        finally:
            if self.codec_owner is not None:
                await self.codec_owner.close()
                self.codec_owner = None

    async def _call_immediate(
        self,
        endpoint: FlexFeatureEndpoint,
        command: FlexCommand,
    ) -> dict[str, object]:
        request = b""
        if command.execution_mode is FlexExecutionMode.UNOBSERVABLE:
            request = await self.codec.encode(
                f"{endpoint.package}.{command.method}_Parameters",
                command.parameters,
            )
        call = self.channel.unary_unary(self._rpc_path(endpoint, command.method))
        try:
            response = await asyncio.wait_for(call(request), self.timeout_s)
        except asyncio.TimeoutError as exc:
            raise FlexSiLACommandTimeout(
                command,
                f"no response within {self.timeout_s:g}s",
            ) from exc
        except Exception as exc:
            raise self._rpc_error(command, exc) from exc
        return await self.codec.decode(
            f"{endpoint.package}.{command.method}_Responses",
            response,
        )

    async def _call_observable(
        self,
        endpoint: FlexFeatureEndpoint,
        command: FlexCommand,
    ) -> dict[str, object]:
        request = await self.codec.encode(
            f"{endpoint.package}.{command.method}_Parameters",
            command.parameters,
        )
        start = self.channel.unary_unary(self._rpc_path(endpoint, command.method))
        try:
            confirmation_payload = await asyncio.wait_for(
                start(request),
                self.timeout_s,
            )
            wire = self.wire
            if wire is None:  # Defensive; __post_init__ always supplies it.
                raise FlexSiLADependencyError("SiLA command wire codec is missing")
            execution_uuid = wire.decode_confirmation(confirmation_payload)
            uuid_payload = wire.encode_execution_uuid(execution_uuid)
        except asyncio.TimeoutError as exc:
            raise FlexSiLACommandTimeout(
                command,
                f"confirmation not received within {self.timeout_s:g}s",
            ) from exc
        except FlexSiLAError:
            raise
        except Exception as exc:
            raise self._rpc_error(command, exc) from exc

        result_call = self.channel.unary_unary(
            self._rpc_path(endpoint, f"{command.method}_Result")
        )
        deadline = asyncio.get_running_loop().time() + self.timeout_s
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise FlexSiLACommandTimeout(
                    command,
                    f"result not ready within {self.timeout_s:g}s",
                )
            try:
                response = await asyncio.wait_for(
                    result_call(uuid_payload),
                    timeout=remaining,
                )
                return await self.codec.decode(
                    f"{endpoint.package}.{command.method}_Responses",
                    response,
                )
            except asyncio.TimeoutError as exc:
                raise FlexSiLACommandTimeout(
                    command,
                    f"result not received within {self.timeout_s:g}s",
                ) from exc
            except Exception as exc:
                if not _is_result_not_ready(exc):
                    raise self._rpc_error(command, exc) from exc
                if asyncio.get_running_loop().time() >= deadline:
                    raise FlexSiLACommandTimeout(
                        command,
                        f"result not ready within {self.timeout_s:g}s",
                    ) from exc
                await asyncio.sleep(self.poll_interval_s)

    @staticmethod
    def _rpc_path(endpoint: FlexFeatureEndpoint, method: str) -> str:
        return f"/{endpoint.package}.{endpoint.service}/{method}"

    @staticmethod
    def _rpc_error(command: FlexCommand, exc: Exception) -> FlexSiLAError:
        details = _decoded_details(exc)
        code = _rpc_code_name(exc)
        if code:
            return FlexSiLACommandError(command, f"{code}: {details}")
        return FlexSiLAConnectionError(
            f"Flex SiLA call failed for {command.method}: {details}"
        )


async def _build_connector_codec() -> tuple[FlexProtobufCodec, _ConnectorCodecOwner]:
    """Compile exact messages without starting a second gRPC server.

    The connector generator registers feature definitions before yielding, so
    its protobuf collection is ready without ``connector.start()``.  The
    generator still instantiates an OT3 simulator and is closed with the
    transport.
    """
    try:
        from unitelabs.cdk import SiLAServerConfig
        from unitelabs.opentrons_flex import OpentronsFlexConfig, create_app
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise FlexSiLADependencyError(
            "The Flex protobuf codec requires unitelabs-opentrons-flex; "
            "install the connector package or inject a compatible codec"
        ) from exc

    config = OpentronsFlexConfig(
        use_simulator=True,
        sila_server=SiLAServerConfig(hostname="127.0.0.1", port=0, tls=False),
        cloud_server_endpoint=None,
        discovery=None,
    )
    generator = create_app(config)
    connector = await generator.__anext__()
    return connector.sila_server.protobuf, _ConnectorCodecOwner(generator)


def _field(value: object, name: str, default: object) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


_MISSING = object()


def _required_field(
    command: FlexCommand,
    value: object,
    name: str,
) -> object:
    result = _field(value, name, _MISSING)
    if result is _MISSING:
        raise FlexSiLAContractError(command, f"response is missing field {name!r}")
    return result


def _required_bool(command: FlexCommand, value: object, name: str) -> bool:
    result = _required_field(command, value, name)
    if not isinstance(result, bool):
        raise FlexSiLAContractError(command, f"response field {name!r} is not boolean")
    return result


def _required_int(command: FlexCommand, value: object, name: str) -> int:
    result = _required_field(command, value, name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise FlexSiLAContractError(
            command, f"response field {name!r} is not an integer"
        )
    return result


def _required_number(command: FlexCommand, value: object, name: str) -> float:
    result = _required_field(command, value, name)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise FlexSiLAContractError(command, f"response field {name!r} is not numeric")
    number = float(result)
    if not math.isfinite(number):
        raise FlexSiLAContractError(command, f"response field {name!r} is not finite")
    return number


def _required_string(command: FlexCommand, value: object, name: str) -> str:
    result = _required_field(command, value, name)
    if not isinstance(result, str):
        raise FlexSiLAContractError(command, f"response field {name!r} is not a string")
    return result


def _normalize_response(
    command: FlexCommand,
    decoded: dict[str, object],
) -> FlexResultValue:
    value = next(iter(decoded.values()), None)
    if command.method in {
        "Home",
        "HomeMount",
        "PrepareForAspirate",
        "Aspirate",
        "Dispense",
        "BlowOut",
        "Grip",
        "Ungrip",
        "HomeJaw",
    }:
        return None
    if command.method in {"MoveTo", "MoveRelative", "GetPosition"}:
        return DeckPoint(
            x=_required_number(command, value, "x"),
            y=_required_number(command, value, "y"),
            z=_required_number(command, value, "z"),
        )
    if command.method in {"PickUpTip", "DropTip", "GetTipPresence"}:
        name = getattr(value, "name", None)
        if name is None:
            name = str(value).rsplit(".", maxsplit=1)[-1]
        try:
            return FlexTipPresence(str(name))
        except ValueError:
            raise FlexSiLAContractError(
                command,
                f"unknown tip-presence value {name!r}",
            ) from None
    if command.method == "SetLights":
        return FlexLightsState(
            button=_required_bool(command, value, "button"),
            rails=_required_bool(command, value, "rails"),
        )
    if command.method == "GetAttachedPipettes":
        if not isinstance(value, list):
            raise FlexSiLAContractError(command, "pipette response is not a list")
        return tuple(_normalize_pipette(command, item) for item in value)
    if command.method == "Get_MachineStatus":
        raw_estop = _required_string(command, value, "estop")
        try:
            estop = FlexEStopState(raw_estop)
        except ValueError:
            raise FlexSiLAContractError(
                command,
                f"unknown MachineStatus estop value {raw_estop!r}",
            ) from None
        return FlexMachineStatus(
            estop=estop,
            door_open=_required_bool(command, value, "door_open"),
            is_error_state=_required_bool(command, value, "is_error_state"),
            message=_required_string(command, value, "message"),
        )
    if command.method in {"EmergencyStop", "Pause", "Resume"}:
        if not isinstance(value, str):
            raise FlexSiLAContractError(command, "response is not a string")
        return value
    raise FlexSiLAContractError(command, "response normalizer is missing")


def _normalize_pipette(command: FlexCommand, value: object) -> FlexPipetteInfo:
    raw_mount = _required_field(command, value, "mount")
    mount_name = getattr(raw_mount, "name", raw_mount)
    try:
        mount = FlexMount(str(mount_name).upper())
    except ValueError:
        raise FlexSiLAContractError(
            command,
            f"unknown pipette mount {mount_name!r}",
        ) from None
    return FlexPipetteInfo(
        mount=mount,
        attached=_required_bool(command, value, "attached"),
        model=_required_string(command, value, "model"),
        name=_required_string(command, value, "name"),
        pipette_id=_required_string(command, value, "pipette_id"),
        channels=_required_int(command, value, "channels"),
        min_volume=_required_number(command, value, "min_volume"),
        max_volume=_required_number(command, value, "max_volume"),
        has_tip=_required_bool(command, value, "has_tip"),
    )


def _rpc_code_name(exc: Exception) -> str:
    code_fn = getattr(exc, "code", None)
    if not callable(code_fn):
        return ""
    code = code_fn()
    name = getattr(code, "name", None)
    return str(name or code)


def _decoded_details(exc: Exception) -> str:
    details_fn: Callable[[], object] | None = getattr(exc, "details", None)
    if not callable(details_fn):
        return str(exc)
    raw = details_fn()
    if isinstance(raw, bytes):
        payload = raw
    else:
        payload = str(raw or "").encode()
    try:
        return base64.b64decode(payload, validate=True).decode(errors="replace")
    except (ValueError, UnicodeError):
        return payload.decode(errors="replace")


def _is_result_not_ready(exc: Exception) -> bool:
    return _rpc_code_name(
        exc
    ).upper() == "ABORTED" and "Result is not ready" in _decoded_details(exc)
