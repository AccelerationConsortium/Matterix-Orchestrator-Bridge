"""Transport-neutral contracts for executing orchestrator steps on Flex.

The orchestrator owns symbolic names such as ``reactor/C5`` while the Flex
SiLA connector accepts absolute deck coordinates in millimetres.  This module
keeps that calibration boundary explicit: a resolver supplies coordinates and
instrument mounts, then the real-hardware package can emit SiLA commands
without importing DT assets or labware definitions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class FlexContractError(ValueError):
    """Base error for invalid or unresolved Flex bridge input."""


class FlexLocationNotFound(FlexContractError):
    """A symbolic labware/well anchor has no calibrated deck position."""

    def __init__(self, labware: str, well: str, anchor: "WellAnchor") -> None:
        self.labware = labware
        self.well = well
        self.anchor = anchor
        super().__init__(
            f"No Flex deck location for {labware!r}/{well!r} at {anchor.value!r}"
        )


class FlexInstrumentNotFound(FlexContractError):
    """An orchestrator pipette name has no configured Flex mount."""

    def __init__(self, instrument: str) -> None:
        self.instrument = instrument
        super().__init__(f"No Flex mount configured for instrument {instrument!r}")


class FlexMount(str, Enum):
    """Instrument mount identifiers used by the Flex SiLA features."""

    LEFT = "LEFT"
    RIGHT = "RIGHT"
    GRIPPER = "GRIPPER"


class WellAnchor(str, Enum):
    """Reference point within a well before workflow offsets are applied."""

    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class DeckPoint(BaseModel):
    """Absolute Flex deck position in millimetres."""

    model_config = ConfigDict(frozen=True)

    x: FiniteFloat
    y: FiniteFloat
    z: FiniteFloat

    def offset(
        self,
        *,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> "DeckPoint":
        """Return this point translated by a finite millimetre offset."""
        return DeckPoint(x=self.x + x, y=self.y + y, z=self.z + z)


class FlexDeckAnchorConfig(BaseModel):
    """One JSON-serializable calibrated anchor supplied by the DT asset."""

    model_config = ConfigDict(frozen=True)

    labware: str = Field(min_length=1)
    well: str = Field(min_length=1)
    anchor: WellAnchor
    point: DeckPoint
    tip_length_mm: FiniteFloat | None = None

    @model_validator(mode="after")
    def _valid_tip_length(self) -> "FlexDeckAnchorConfig":
        if self.tip_length_mm is not None and not 0.0 < self.tip_length_mm <= 100.0:
            raise ValueError("tip_length_mm must be greater than 0 and at most 100")
        return self


class StaticFlexConfig(BaseModel):
    """Temporary JSON-backed calibration until the Flex DT asset owns it."""

    model_config = ConfigDict(frozen=True)

    anchors: list[FlexDeckAnchorConfig]
    instruments: dict[str, FlexMount]
    calibration_confirmed: bool = False

    @model_validator(mode="after")
    def _unique_anchors(self) -> "StaticFlexConfig":
        seen: set[tuple[str, str, WellAnchor]] = set()
        tip_lengths: dict[tuple[str, str], float] = {}
        for anchor in self.anchors:
            key = (anchor.labware, anchor.well, anchor.anchor)
            if key in seen:
                raise ValueError(
                    "duplicate Flex anchor "
                    f"{anchor.labware!r}/{anchor.well!r}/{anchor.anchor.value!r}"
                )
            seen.add(key)
            if anchor.tip_length_mm is None:
                continue
            tip_key = (anchor.labware, anchor.well)
            current = float(anchor.tip_length_mm)
            previous = tip_lengths.get(tip_key)
            if previous is not None and previous != current:
                raise ValueError(
                    f"conflicting tip lengths for {anchor.labware!r}/{anchor.well!r}"
                )
            tip_lengths[tip_key] = current
        return self

    @classmethod
    def load_json(cls, source: str | Path) -> "StaticFlexConfig":
        """Load and validate a temporary Flex DT calibration file."""
        path = Path(source)
        return cls.model_validate(json.loads(path.read_text()))

    def deck_resolver(self) -> "StaticFlexDeckResolver":
        """Build the resolver consumed by :class:`FlexWorkflowAdapter`."""
        anchors = {
            (entry.labware, entry.well, entry.anchor): entry.point
            for entry in self.anchors
        }
        tip_lengths = {
            (entry.labware, entry.well): float(entry.tip_length_mm)
            for entry in self.anchors
            if entry.tip_length_mm is not None
        }
        return StaticFlexDeckResolver(
            anchors=anchors,
            tip_lengths_mm=tip_lengths,
        )

    def instrument_resolver(self) -> "StaticFlexInstrumentResolver":
        """Build the workflow-alias to physical-mount resolver."""
        return StaticFlexInstrumentResolver(mounts=self.instruments)


@runtime_checkable
class FlexDeckResolver(Protocol):
    """Resolve symbolic workflow locations through the current DT asset."""

    def resolve(
        self,
        labware: str,
        well: str,
        anchor: WellAnchor,
        *,
        offset_x_mm: float = 0.0,
        offset_y_mm: float = 0.0,
        offset_z_mm: float = 0.0,
    ) -> DeckPoint: ...

    def tip_length_mm(self, labware: str, well: str) -> float | None: ...


@runtime_checkable
class FlexInstrumentResolver(Protocol):
    """Resolve an orchestrator instrument name to a physical Flex mount."""

    def mount_for(self, instrument: str) -> FlexMount: ...


@dataclass
class StaticFlexDeckResolver:
    """In-memory resolver used before the Flex DT asset is available.

    ``anchors`` is keyed by ``(labware, well, WellAnchor)``.  The future DT
    asset adapter only needs to implement :class:`FlexDeckResolver`; callers
    and the SiLA execution layer remain unchanged.
    """

    anchors: Mapping[tuple[str, str, WellAnchor], DeckPoint]
    tip_lengths_mm: Mapping[tuple[str, str], float] = field(default_factory=dict)

    def resolve(
        self,
        labware: str,
        well: str,
        anchor: WellAnchor,
        *,
        offset_x_mm: float = 0.0,
        offset_y_mm: float = 0.0,
        offset_z_mm: float = 0.0,
    ) -> DeckPoint:
        try:
            point = self.anchors[(labware, well, anchor)]
        except KeyError:
            raise FlexLocationNotFound(labware, well, anchor) from None
        return point.offset(x=offset_x_mm, y=offset_y_mm, z=offset_z_mm)

    def tip_length_mm(self, labware: str, well: str) -> float | None:
        value = self.tip_lengths_mm.get((labware, well))
        return float(value) if value is not None else None


@dataclass
class StaticFlexInstrumentResolver:
    """In-memory mapping from workflow pipette aliases to Flex mounts."""

    mounts: Mapping[str, FlexMount]

    def mount_for(self, instrument: str) -> FlexMount:
        try:
            return self.mounts[instrument]
        except KeyError:
            raise FlexInstrumentNotFound(instrument) from None
