"""SiLA-specific command contract kept inside the real Flex adapter layer."""

from __future__ import annotations

from enum import Enum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from twin_core.flex import DeckPoint, FlexMount


class FlexFeature(str, Enum):
    """Flex SiLA feature families used by the client."""

    MOTION_CONTROL = "motion_control"
    TIP_CONTROLLER = "tip_controller"
    GRIPPER = "gripper"
    PIPETTE = "pipette"


class FlexExecutionMode(str, Enum):
    """SiLA command execution modes needed by the client."""

    OBSERVABLE = "observable"
    UNOBSERVABLE = "unobservable"
    PROPERTY = "property"


class FlexCommand(BaseModel):
    """One validated invocation of a pinned Flex SiLA feature."""

    model_config = ConfigDict(frozen=True)

    step_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    feature: FlexFeature
    method: str = Field(min_length=1)
    parameters: dict[str, object] = Field(default_factory=dict)
    execution_mode: FlexExecutionMode = FlexExecutionMode.OBSERVABLE
    verify_machine_status: bool = False


class FlexTipPresence(str, Enum):
    """Normalized physical tip sensor state."""

    ABSENT = "ABSENT"
    PRESENT = "PRESENT"


class FlexEStopState(str, Enum):
    """Closed MachineStatus E-stop vocabulary declared by the connector FDL."""

    DISENGAGED = "DISENGAGED"
    PHYSICALLY_ENGAGED = "PHYSICALLY_ENGAGED"
    LOGICALLY_ENGAGED = "LOGICALLY_ENGAGED"
    NOT_PRESENT = "NOT_PRESENT"


class FlexLightsState(BaseModel):
    """Normalized Flex button and rail light state."""

    model_config = ConfigDict(frozen=True)

    button: bool
    rails: bool


class FlexPipetteInfo(BaseModel):
    """Normalized attached-pipette metadata."""

    model_config = ConfigDict(frozen=True)

    mount: FlexMount
    attached: bool
    model: str
    name: str
    pipette_id: str
    channels: int
    min_volume: FiniteFloat
    max_volume: FiniteFloat
    has_tip: bool


class FlexMachineStatus(BaseModel):
    """Normalized MotionControl.MachineStatus safety evidence."""

    model_config = ConfigDict(frozen=True)

    estop: FlexEStopState
    door_open: bool
    is_error_state: bool
    message: str


FlexResultValue: TypeAlias = (
    None
    | DeckPoint
    | FlexTipPresence
    | FlexLightsState
    | tuple[FlexPipetteInfo, ...]
    | FlexMachineStatus
    | str
)
