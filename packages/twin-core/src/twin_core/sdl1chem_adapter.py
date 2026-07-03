"""Adapter from fixed SDL1Chem/Uoroboros workflow JSON to bridge workflows.

The SDL1Chem repo owns its UO and workflow formats. This module treats that
format as an external contract and maps selected ``blocks[*].uo_path`` entries
into this repo's bridge-level UnitOperations. Unsupported UOs stay visible in
the mapping report instead of being silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from twin_core.operations import WorkflowDict
from twin_core.workflow_loader import (
    LoadedWorkflow,
    WorkflowJsonError,
    load_operations_json,
)


class Sdl1ChemAdapterError(ValueError):
    """Raised when SDL1Chem workflow JSON cannot be adapted."""


@dataclass(frozen=True)
class Sdl1ChemBlock:
    """One block from SDL1Chem/Uoroboros workflow JSON."""

    block_id: str
    uo_path: str
    description: str = ""


@dataclass(frozen=True)
class Sdl1ChemWorkflowMapping:
    """Result of adapting a SDL1Chem workflow into bridge operations."""

    name: str
    version: str
    loaded_workflow: LoadedWorkflow
    mapped_blocks: list[Sdl1ChemBlock]
    unsupported_blocks: list[Sdl1ChemBlock]

    def to_workflow_steps(self) -> WorkflowDict:
        """Translate mapped UnitOperations into bridge WorkflowSteps."""
        return self.loaded_workflow.to_workflow_steps()


MappingRule = Mapping[str, Any]


DEFAULT_SDL1CHEM_UO_MAPPINGS: dict[str, MappingRule] = {
    "echem-uos:flush_tool_transfer": {
        "operation": "pick_and_place",
        "params": {
            "source_object": "flush_tool",
            "source_frame": "electrode_rack:B1",
            "target_object": "wash_station",
            "target_frame": "B2",
        },
    },
    "echem-uos:insert_electrode": {
        "operation": "pick_and_place",
        "params": {
            "source_object": "electrode",
            "source_frame": "wash_station:A1",
            "target_object": "reactor",
            "target_frame": "active_cell",
        },
    },
    "echem-uos:remove_electrode": {
        "operation": "pick_and_place",
        "params": {
            "source_object": "electrode",
            "source_frame": "reactor:active_cell",
            "target_object": "wash_station",
            "target_frame": "A1",
        },
    },
}


def load_sdl1chem_workflow_json(
    source: str | Path | dict[str, Any],
    *,
    mapping_rules: Mapping[str, MappingRule] | None = None,
    fail_on_unsupported: bool = False,
) -> Sdl1ChemWorkflowMapping:
    """Adapt fixed SDL1Chem workflow JSON into bridge UnitOperations.

    The source format is the Uoroboros-style workflow JSON used by SDL1Chem:

        {
          "name": "sdl1chem-robot-loop",
          "version": "1.0.0",
          "blocks": [
            {"id": "b_insert_electrode", "uo_path": "echem-uos:insert_electrode"}
          ],
          "steps": [...]
        }

    Only UO paths present in ``mapping_rules`` are converted. By default this
    maps the SDL1Chem robot transfer UOs that resemble Matterix pick/place
    semantics. Other blocks remain in ``unsupported_blocks`` for inspection.
    """
    data = _load_json(source)
    blocks = _parse_blocks(data)
    rules = dict(DEFAULT_SDL1CHEM_UO_MAPPINGS)
    if mapping_rules:
        rules.update(mapping_rules)

    mapped_blocks: list[Sdl1ChemBlock] = []
    unsupported_blocks: list[Sdl1ChemBlock] = []
    bridge_ops: list[dict[str, Any]] = []

    for block in blocks:
        rule = rules.get(block.uo_path)
        if rule is None:
            unsupported_blocks.append(block)
            continue

        mapped_blocks.append(block)
        bridge_ops.append(_operation_from_rule(block, rule))

    if fail_on_unsupported and unsupported_blocks:
        unsupported = ", ".join(
            f"{block.block_id} ({block.uo_path})" for block in unsupported_blocks
        )
        raise Sdl1ChemAdapterError(f"unsupported SDL1Chem blocks: {unsupported}")

    name = str(data.get("name") or data.get("workflow_name") or "")
    version = str(data.get("version", "1.0"))
    if bridge_ops:
        loaded = load_operations_json(
            {
                "workflow_name": name,
                "version": version,
                "operations": bridge_ops,
            }
        )
    else:
        loaded = LoadedWorkflow(name=name, version=version, operations=[])

    return Sdl1ChemWorkflowMapping(
        name=name,
        version=version,
        loaded_workflow=loaded,
        mapped_blocks=mapped_blocks,
        unsupported_blocks=unsupported_blocks,
    )


def _load_json(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = Path(source)
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        raise Sdl1ChemAdapterError(f"could not read SDL1Chem workflow JSON {path}") from exc
    except json.JSONDecodeError as exc:
        raise Sdl1ChemAdapterError(
            f"invalid SDL1Chem workflow JSON {path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise Sdl1ChemAdapterError("SDL1Chem workflow JSON root must be an object")
    return data


def _parse_blocks(data: dict[str, Any]) -> list[Sdl1ChemBlock]:
    raw_blocks = data.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise Sdl1ChemAdapterError("SDL1Chem workflow JSON requires non-empty 'blocks'")

    blocks: list[Sdl1ChemBlock] = []
    for index, raw in enumerate(raw_blocks):
        if not isinstance(raw, dict):
            raise Sdl1ChemAdapterError(f"blocks[{index}] must be an object")
        block_id = raw.get("id")
        uo_path = raw.get("uo_path")
        if not isinstance(block_id, str) or not block_id:
            raise Sdl1ChemAdapterError(f"blocks[{index}] requires string 'id'")
        if not isinstance(uo_path, str) or not uo_path:
            raise Sdl1ChemAdapterError(f"blocks[{index}] requires string 'uo_path'")
        description = raw.get("description")
        blocks.append(
            Sdl1ChemBlock(
                block_id=block_id,
                uo_path=uo_path,
                description=description if isinstance(description, str) else "",
            )
        )
    return blocks


def _operation_from_rule(block: Sdl1ChemBlock, rule: MappingRule) -> dict[str, Any]:
    op_type = rule.get("operation") or rule.get("operation_type") or rule.get("type")
    params = rule.get("params", {})
    if not isinstance(op_type, str) or not op_type:
        raise WorkflowJsonError(f"mapping for {block.uo_path!r} requires operation")
    if not isinstance(params, dict):
        raise WorkflowJsonError(f"mapping for {block.uo_path!r} requires object params")
    return {
        "operation_id": block.block_id,
        "operation": op_type,
        "params": dict(params),
    }
