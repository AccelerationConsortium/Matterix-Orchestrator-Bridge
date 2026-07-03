"""Inspect SDL1Chem/Uoroboros workflow JSON adapter output.

This script does not import SDL1Chem. It reads the fixed workflow JSON shape
and reports which UO blocks can currently be mapped into bridge WorkflowSteps.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from twin_core import Sdl1ChemWorkflowMapping, load_sdl1chem_workflow_json
from twin_core.operations import operation_to_workflow


DEFAULT_WORKFLOW_JSON = (
    Path(__file__).parent / "workflows" / "sdl1chem_robot_loop_excerpt.json"
)


def format_adapter_report(mapping: Sdl1ChemWorkflowMapping) -> str:
    lines = [
        f"SDL1Chem workflow: {mapping.name or '<unnamed>'} (version {mapping.version})",
        "Source format: blocks[*].uo_path from fixed SDL1Chem/Uoroboros JSON",
        "Bridge chain: SDL1Chem block -> UnitOperation -> WorkflowStep",
        "",
        "Mapped blocks:",
    ]

    if not mapping.loaded_workflow.operations:
        lines.append("- <none>")
    for block, loaded_op in zip(
        mapping.mapped_blocks,
        mapping.loaded_workflow.operations,
        strict=True,
    ):
        op_name = type(loaded_op.operation).__name__
        lines.append(f"- {block.block_id}: {block.uo_path} -> {op_name}")
        for step in operation_to_workflow(loaded_op.operation):
            target = step.target_object or "<none>"
            lines.append(f"  - WorkflowStep({step.primitive}, target={target})")

    lines.extend(["", "Unsupported blocks:"])
    if not mapping.unsupported_blocks:
        lines.append("- <none>")
    for block in mapping.unsupported_blocks:
        lines.append(f"- {block.block_id}: {block.uo_path}")

    lines.append("")
    lines.append(f"Mapped UnitOperations: {len(mapping.loaded_workflow.operations)}")
    lines.append(f"Unsupported UO blocks: {len(mapping.unsupported_blocks)}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-inspect SDL1Chem workflow JSON adapter mappings."
    )
    parser.add_argument(
        "workflow_json",
        nargs="?",
        type=Path,
        default=DEFAULT_WORKFLOW_JSON,
        help="Path to SDL1Chem/Uoroboros workflow JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mapping = load_sdl1chem_workflow_json(args.workflow_json)
    print(format_adapter_report(mapping))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
