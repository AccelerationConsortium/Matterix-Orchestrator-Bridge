"""StaticFrameService: in-memory FrameService for the configs-only path.

Sim backend's "real" FrameService will read frames from USD asset config.
For the PoC (and for safety-layer tests that must run without Matterix),
this static registry mirrors the asset frames documented in the plan.

The registry covers stock Matterix demo assets (beaker_500ml,
optical_table). Once Matterix is installed, swap this for a USD reader —
the contract (FrameService.lookup) does not change.
"""

from __future__ import annotations

from twin_core.errors import FrameNotFound
from twin_core.schemas import Pose


class StaticFrameService:
    """FrameService backed by a Python dict registry."""

    def __init__(self, registry: dict[str, dict[str, Pose]]) -> None:
        self._registry = registry

    def lookup(self, asset_id: str, frame_name: str) -> Pose:
        try:
            return self._registry[asset_id][frame_name]
        except KeyError as exc:
            raise FrameNotFound(asset_id, frame_name) from exc

    def has_frame(self, asset_id: str, frame_name: str) -> bool:
        return asset_id in self._registry and frame_name in self._registry[asset_id]

    @classmethod
    def default_for_demo(cls) -> "StaticFrameService":
        """Stock Matterix demo assets (beaker_500ml + optical_table).

        Frame conventions per plan §5/A4: pre_grasp/grasp/post_grasp on
        the manipulated object; dropoff_* on the surface.
        """
        return cls(
            registry={
                "beaker_500ml": {
                    "pre_grasp": Pose(position=(0.40, 0.00, 0.20)),
                    "grasp": Pose(position=(0.40, 0.00, 0.10)),
                    "post_grasp": Pose(position=(0.40, 0.00, 0.30)),
                },
                "optical_table": {
                    "dropoff_a1": Pose(position=(0.60, 0.20, 0.10)),
                    "dropoff_a2": Pose(position=(0.60, 0.30, 0.10)),
                    "pre_dropoff_a1": Pose(position=(0.60, 0.20, 0.30)),
                    "pre_dropoff_a2": Pose(position=(0.60, 0.30, 0.30)),
                },
            }
        )
