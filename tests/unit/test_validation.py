"""Unit tests for the safety layer (twin_core.validation)."""

from __future__ import annotations

from twin_core import (
    PickAndPlace,
    WorkflowStep,
    frame_check,
    operation_to_workflow,
    preflight,
    schema_check,
    state_check,
)
from twin_sim import StaticFrameService


def _frames() -> StaticFrameService:
    return StaticFrameService.default_for_demo()


# --- schema_check --------------------------------------------------------


def test_schema_check_passes_for_clean_workflow() -> None:
    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="grasp",
            target_object="optical_table",
            target_frame="dropoff_a1",
        )
    )
    assert schema_check(workflow).ok


def test_schema_check_rejects_disallowed_pick_frame() -> None:
    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="post_grasp",
            target_object="optical_table",
            target_frame="dropoff_a1",
        )
    )
    result = schema_check(workflow)
    assert not result.ok
    assert result.error_class == "SchemaError"
    assert result.step_index == 0


def test_schema_check_rejects_bad_place_prefix() -> None:
    workflow = [
        WorkflowStep(primitive="pick_object", target_object="beaker_500ml", target_frame="grasp"),
        WorkflowStep(
            primitive="place_at",
            target_object="optical_table",
            target_frame="random_frame",
        ),
    ]
    result = schema_check(workflow)
    assert not result.ok
    assert result.error_class == "SchemaError"
    assert result.step_index == 1


# --- frame_check ---------------------------------------------------------


def test_frame_check_catches_missing_dropoff_frame() -> None:
    workflow = [
        WorkflowStep(primitive="pick_object", target_object="beaker_500ml", target_frame="grasp"),
        WorkflowStep(
            primitive="place_at",
            target_object="optical_table",
            target_frame="dropoff_zz",
        ),
    ]
    result = frame_check(workflow, _frames())
    assert not result.ok
    assert result.error_class == "FrameNotFound"


# --- state_check ---------------------------------------------------------


def test_state_check_catches_double_pick() -> None:
    workflow = [
        WorkflowStep(primitive="pick_object", target_object="beaker_500ml", target_frame="grasp"),
        WorkflowStep(primitive="pick_object", target_object="beaker_500ml", target_frame="grasp"),
    ]
    result = state_check(workflow)
    assert not result.ok
    assert result.error_class == "StateMachineViolation"
    assert result.step_index == 1


def test_state_check_catches_place_without_pick() -> None:
    workflow = [
        WorkflowStep(
            primitive="place_at", target_object="optical_table", target_frame="dropoff_a1"
        )
    ]
    result = state_check(workflow)
    assert not result.ok
    assert result.error_class == "StateMachineViolation"


# --- preflight (composite) -----------------------------------------------


def test_preflight_passes_for_clean_workflow() -> None:
    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="grasp",
            target_object="optical_table",
            target_frame="dropoff_a1",
        )
    )
    assert preflight(workflow, _frames()).ok


def test_preflight_returns_first_failure_only() -> None:
    # Both schema (bad source_frame) and frame existence would catch this;
    # we expect schema to win because it runs first.
    workflow = operation_to_workflow(
        PickAndPlace(
            source_object="beaker_500ml",
            source_frame="post_grasp",  # schema reject
            target_object="optical_table",
            target_frame="dropoff_zz",  # would-be frame_check reject
        )
    )
    result = preflight(workflow, _frames())
    assert not result.ok
    assert result.error_class == "SchemaError"
