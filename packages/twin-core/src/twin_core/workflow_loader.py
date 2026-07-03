"""Load bridge-level workflow JSON into UnitOperations and WorkflowSteps.

This is the orchestrator-facing JSON bridge used by the Matterix examples.
The stable downstream boundary remains WorkflowStep -> matterix_sm Cfg;
this loader only handles the flexible, experiment-facing UnitOperation layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from twin_core.operations import (
    Heat,
    PickAndPlace,
    UnitOperation,
    WorkflowDict,
    operation_to_workflow,
)


class WorkflowJsonError(ValueError):
    """Raised when a bridge workflow JSON file is malformed or unsupported."""


@dataclass(frozen=True)
class LoadedOperation:
    """One JSON-declared operation plus its typed UnitOperation."""

    operation_id: str
    operation_type: str
    operation: UnitOperation


@dataclass(frozen=True)
class LoadedWorkflow:
    """Typed representation of an orchestrator-style workflow JSON."""

    name: str
    version: str
    operations: list[LoadedOperation]

    def to_workflow_steps(self) -> WorkflowDict:
        """Translate all UnitOperations into bridge WorkflowSteps."""
        workflow: WorkflowDict = []
        for loaded in self.operations:
            workflow.extend(operation_to_workflow(loaded.operation))
        return workflow


def load_operations_json(source: str | Path | dict[str, Any]) -> LoadedWorkflow:
    """Load a bridge workflow JSON into typed UnitOperation instances.

    Expected shape:

        {
          "workflow_name": "matterix-heat-demo",
          "version": "1.0",
          "operations": [
            {"operation": "pick_and_place", "params": {...}},
            {"operation": "heat", "params": {...}}
          ]
        }

    The operation vocabulary is deliberately small and explicit. New UOs
    should be added here case by case, while the Matterix-facing mapping stays
    in twin_sim.real_runner._build_matterix_cfgs().
    """
    data = _load_json(source)
    raw_ops = data.get("operations")
    if not isinstance(raw_ops, list) or not raw_ops:
        raise WorkflowJsonError("workflow JSON requires a non-empty 'operations' list")

    operations: list[LoadedOperation] = []
    for index, raw in enumerate(raw_ops):
        if not isinstance(raw, dict):
            raise WorkflowJsonError(f"operations[{index}] must be an object")
        op_type = _operation_type(raw, index)
        params = _params(raw)
        op_id = str(raw.get("operation_id") or raw.get("id") or f"op_{index}")
        operations.append(
            LoadedOperation(
                operation_id=op_id,
                operation_type=op_type,
                operation=_parse_operation(op_type, params, index),
            )
        )

    return LoadedWorkflow(
        name=str(data.get("workflow_name") or data.get("name") or ""),
        version=str(data.get("version", "1.0")),
        operations=operations,
    )


def load_workflow_steps_json(source: str | Path | dict[str, Any]) -> WorkflowDict:
    """Load a workflow JSON and return bridge WorkflowSteps directly."""
    return load_operations_json(source).to_workflow_steps()


def _load_json(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = Path(source)
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        raise WorkflowJsonError(f"could not read workflow JSON {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowJsonError(f"invalid workflow JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowJsonError("workflow JSON root must be an object")
    return data


def _operation_type(raw: dict[str, Any], index: int) -> str:
    op_type = raw.get("operation") or raw.get("operation_type") or raw.get("type")
    if not isinstance(op_type, str) or not op_type:
        raise WorkflowJsonError(
            f"operations[{index}] requires 'operation', 'operation_type', or 'type'"
        )
    return op_type


def _params(raw: dict[str, Any]) -> dict[str, Any]:
    params = raw.get("params")
    if params is None:
        return raw
    if not isinstance(params, dict):
        raise WorkflowJsonError("operation 'params' must be an object")
    return params


def _parse_operation(op_type: str, params: dict[str, Any], index: int) -> UnitOperation:
    normalized = op_type.lower().replace("-", "_")
    if normalized in {"pick_and_place", "pickandplace"}:
        return PickAndPlace(
            source_object=_require_str(params, "source_object", index),
            source_frame=_require_str(params, "source_frame", index),
            target_object=_require_str(params, "target_object", index),
            target_frame=_require_str(params, "target_frame", index),
        )
    if normalized == "heat":
        return Heat(
            asset_name=_require_str(params, "asset_name", index),
            target_temperature_k=_require_number(
                params, "target_temperature_k", index
            ),
            duration_s=_require_number(params, "duration_s", index),
        )
    raise WorkflowJsonError(f"operations[{index}] unsupported operation {op_type!r}")


def _require_str(params: dict[str, Any], key: str, index: int) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise WorkflowJsonError(f"operations[{index}] requires string param {key!r}")
    return value


def _require_number(params: dict[str, Any], key: str, index: int) -> float:
    value = params.get(key)
    if not isinstance(value, (int, float)):
        raise WorkflowJsonError(f"operations[{index}] requires numeric param {key!r}")
    return float(value)
