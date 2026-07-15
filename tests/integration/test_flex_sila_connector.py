"""Optional real gRPC test against the installed Flex connector simulator."""

from __future__ import annotations

import asyncio

import pytest

grpc_aio = pytest.importorskip("grpc.aio")
OT3API = pytest.importorskip("opentrons.hardware_control.ot3api").OT3API
OT3Mount = pytest.importorskip("opentrons.hardware_control.types").OT3Mount
cdk = pytest.importorskip("unitelabs.cdk")
flex_package = pytest.importorskip("unitelabs.opentrons_flex")

from twin_core import (  # noqa: E402
    DeckPoint,
    FlexMount,
    StaticFlexDeckResolver,
    StaticFlexInstrumentResolver,
    WellAnchor,
    parse_workflow_json,
)
from twin_real import (  # noqa: E402
    FlexSiLATransport,
    FlexWorkflowAdapter,
    FlexWorkflowRunner,
)
from unitelabs.opentrons_flex.features.motion_control import (  # noqa: E402
    MotionControlFeature,
)
from unitelabs.opentrons_flex.features.tip_controller import (  # noqa: E402
    TipController,
)
from unitelabs.opentrons_flex.io import FlexMotionController  # noqa: E402


@pytest.mark.asyncio
async def test_dt_runner_executes_tip_lifecycle_over_real_sila_grpc() -> None:
    api = await OT3API.build_hardware_simulator(
        attached_instruments={
            OT3Mount.LEFT: {"model": "p1000_single_v3.0", "id": "sim-left"},
        }
    )
    await api.home()
    point = await api.gantry_position(OT3Mount.LEFT, refresh=True)
    config = flex_package.OpentronsFlexConfig(
        use_simulator=True,
        sila_server=cdk.SiLAServerConfig(
            hostname="127.0.0.1",
            port=0,
            tls=False,
        ),
        cloud_server_endpoint=None,
        discovery=None,
    )
    connector = cdk.Connector(config)
    motion = FlexMotionController.from_api(api, lock=asyncio.Lock())
    connector.register(MotionControlFeature(motion))
    connector.register(TipController(motion))
    await connector.start()
    channel = grpc_aio.insecure_channel(connector.sila_server._address)

    transport = FlexSiLATransport(
        channel=channel,
        codec=connector.sila_server.protobuf,
    )
    adapter = FlexWorkflowAdapter(
        deck=StaticFlexDeckResolver(
            anchors={
                ("tips", "A1", WellAnchor.TOP): DeckPoint(
                    x=point.x,
                    y=point.y,
                    z=point.z,
                ),
                ("trash", "A1", WellAnchor.TOP): DeckPoint(
                    x=point.x,
                    y=point.y,
                    z=point.z - 95.6,
                ),
            },
            tip_lengths_mm={("tips", "A1"): 95.6},
        ),
        instruments=StaticFlexInstrumentResolver({"pip": FlexMount.LEFT}),
    )
    workflow = parse_workflow_json(
        {
            "workflow_name": "grpc tip lifecycle",
            "version": "1.0",
            "phases": [
                {
                    "phase_name": "tip",
                    "steps": [
                        {
                            "step_id": "pickup",
                            "action": "robot.pick_up_tip",
                            "params": {
                                "pipette": "pip",
                                "labware": "tips",
                                "well": "A1",
                            },
                        },
                        {
                            "step_id": "presence",
                            "action": "robot.get_tip_presence",
                            "params": {"pipette": "pip"},
                        },
                        {
                            "step_id": "position",
                            "action": "robot.get_position",
                            "params": {"pipette": "pip"},
                        },
                        {
                            "step_id": "drop",
                            "action": "robot.drop_tip",
                            "params": {
                                "pipette": "pip",
                                "labware": "trash",
                                "well": "A1",
                            },
                        },
                    ],
                }
            ],
        }
    )
    runner = FlexWorkflowRunner(adapter=adapter, transport=transport)
    try:
        result = await runner.run(workflow)
        assert result.completed is True
        assert [record.command.method for record in result.records] == [
            "PickUpTip",
            "GetTipPresence",
            "GetPosition",
            "DropTip",
        ]
        assert result.records[0].machine_status is not None
        assert result.records[0].machine_status.is_error_state is False
        assert isinstance(result.records[2].response, DeckPoint)
        assert result.records[3].machine_status is not None
        assert result.records[3].machine_status.is_error_state is False
    finally:
        await runner.close()
        await connector.stop()
        await api.clean_up()
