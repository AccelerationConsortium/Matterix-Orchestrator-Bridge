"""Inspect JSON -> UnitOperation -> WorkflowStep -> Matterix Cfg mapping.

This is a dry inspection tool. It does not import Isaac Lab or matterix_sm, so
it can run on a laptop where the real Matterix runtime is unavailable.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from twin_core import LoadedWorkflow, WorkflowStep, load_operations_json
from twin_core.operations import operation_to_workflow


DEFAULT_WORKFLOW_JSON = Path(__file__).parent / "workflows" / "matterix_heat_workflow.json"


def matterix_cfg_names(step: WorkflowStep) -> list[str]:
    """Return the Matterix Cfg class names used by real_runner for a step."""
    if step.primitive == "pick_object":
        return ["PickObjectCfg"]
    if step.primitive == "place_at":
        return ["PlaceObjectCfg"]
    if step.primitive == "heat":
        return [
            "TurnOnHeaterCfg(value=True)",
            "WaitCfg",
            "TurnOnHeaterCfg(value=False)",
        ]
    return [f"<no Matterix mapping for {step.primitive!r}>"]


def format_mapping(loaded: LoadedWorkflow) -> str:
    lines = [
        f"Workflow: {loaded.name or '<unnamed>'} (version {loaded.version})",
        "Mapping chain: workflow JSON -> UnitOperation -> WorkflowStep -> matterix_sm Cfg",
        "",
    ]

    total_cfgs = 0
    for loaded_op in loaded.operations:
        op_name = type(loaded_op.operation).__name__
        lines.append(
            f"- {loaded_op.operation_id}: {loaded_op.operation_type} -> {op_name}"
        )
        for step in operation_to_workflow(loaded_op.operation):
            cfgs = matterix_cfg_names(step)
            total_cfgs += len(cfgs)
            target = step.target_object or "<none>"
            lines.append(
                f"  - WorkflowStep({step.primitive}, target={target}) -> "
                + " + ".join(cfgs)
            )

    lines.extend(["", f"Total Matterix cfgs: {total_cfgs}"])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-inspect the workflow JSON to Matterix Cfg mapping."
    )
    parser.add_argument(
        "workflow_json",
        nargs="?",
        type=Path,
        default=DEFAULT_WORKFLOW_JSON,
        help="Path to workflow JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    loaded = load_operations_json(args.workflow_json)
    print(format_mapping(loaded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
