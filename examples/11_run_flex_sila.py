"""Compile or execute a sequential orchestrator workflow on Flex SiLA 2.

Compilation is the default and never opens a hardware connection.  Add
``--execute --host HOST`` only after the config coordinates have been checked
against the current deck and the connector is running.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from twin_core import StaticFlexConfig, parse_workflow_json
from twin_real import FlexSiLATransport, FlexWorkflowAdapter, FlexWorkflowRunner


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "workflow",
        nargs="?",
        default="examples/workflows/flex_tip_lifecycle.json",
    )
    parser.add_argument("--config", default="examples/flex_dt_config.json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=50051)
    security = parser.add_mutually_exclusive_group()
    security.add_argument(
        "--tls-ca",
        type=Path,
        help="PEM CA certificate used to authenticate the connector",
    )
    security.add_argument(
        "--insecure",
        action="store_true",
        help="Explicitly allow plaintext gRPC for a trusted simulator/lab network",
    )
    args = parser.parse_args()

    config = StaticFlexConfig.load_json(args.config)
    workflow = parse_workflow_json(args.workflow)
    adapter = FlexWorkflowAdapter(
        deck=config.deck_resolver(),
        instruments=config.instrument_resolver(),
    )

    if not args.execute:
        runner = FlexWorkflowRunner(adapter=adapter, transport=_CompileOnlyTransport())
        compiled = runner.compile(workflow)
        for command in compiled.commands:
            print(
                f"{command.step_id}: {command.feature.value}.{command.method} "
                f"{command.parameters}"
            )
        return 0

    if not args.host:
        parser.error("--host is required with --execute")
    if not config.calibration_confirmed:
        parser.error(
            "the config is not marked calibration_confirmed=true; "
            "verify every coordinate before hardware execution"
        )
    if args.tls_ca is None and not args.insecure:
        parser.error("--execute requires --tls-ca PATH or explicit --insecure")
    root_certificates = args.tls_ca.read_bytes() if args.tls_ca else None
    transport = await FlexSiLATransport.connect(
        args.host,
        args.port,
        tls=args.tls_ca is not None,
        root_certificates=root_certificates,
    )
    runner = FlexWorkflowRunner(adapter=adapter, transport=transport)
    try:
        result = await runner.run(workflow)
        print(f"completed={result.completed} commands={len(result.records)}")
    finally:
        await runner.close()
    return 0


class _CompileOnlyTransport:
    """Unreachable placeholder because compilation performs no I/O."""

    async def execute(self, command):
        raise RuntimeError("compile-only transport cannot execute commands")

    async def machine_status(self):
        raise RuntimeError("compile-only transport has no machine status")

    async def close(self) -> None:
        return None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
