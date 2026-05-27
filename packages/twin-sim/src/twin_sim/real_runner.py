"""Workflow-level driver for real Matterix (matterix_sm + Isaac Lab env).

The per-step `ExecutorBackend` abstraction in twin-core is the *right*
boundary for the mock and real-stub backends, but real Matterix is
fundamentally a workflow-level system: `matterix_sm.StateMachine` takes
a configured action sequence and runs it as a tensor-vectorized
loop across one or many parallel envs, returning a single
"workflow_done" signal at the end. There is no clean per-step
intercept point that's also performant on GPU.

This module provides the workflow-level path. It translates a twin
`WorkflowDict` into a list of `matterix_sm` compositional action
configs, hands them to `StateMachine`, runs the env loop to completion,
and returns the final twin `Observation` — the same shape downstream
code already consumes.

Module-level helpers (`_build_matterix_cfgs`, `_heat_to_matterix_cfgs`,
`_obs_to_twin`) are shared with `twin_sim.batch_runner` so translation
logic lives in one place.

Usage (Linux + Isaac Lab installed):

    # In examples/06_run_real_matterix.py — Omniverse launcher first
    env = make_real_env(task="Matterix-Test-Beaker-Lift-Franka-v1")
    runner = MatterixWorkflowRunner(env, robot_asset="robot")
    workflow = operation_to_workflow(PickAndPlace(...))
    final_obs = runner.run_workflow(workflow)

This is intentionally NOT an `ExecutorBackend`. It's a separate driver
for the workflow-level path. Phase 2 architecture work: decide whether
to (a) lift `ExecutorBackend.execute_workflow` into the protocol or
(b) split executors into "step-driven" vs. "workflow-driven" tiers.
See findings.md for the architectural rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from twin_core.errors import SchemaError
from twin_core.operations import WorkflowDict
from twin_core.schemas import Observation, Pose, WorkflowStep

from twin_sim.backend import SimRuntimeUnavailable


# ---------------------------------------------------------------------------
# Shared translation helpers (used by both WorkflowRunner and BatchRunner)
# ---------------------------------------------------------------------------


def _build_matterix_cfgs(step: WorkflowStep, robot_asset: str) -> Any:
    """Translate one WorkflowStep into one or more matterix_sm action configs.

    Returns a single Cfg for pick/place, a list[Cfg] for heat.
    Calibration point: action_space_info defaults to FRANKA_IK_ACTION_SPACE.
    """
    try:
        from matterix_sm import (  # type: ignore[import-not-found]
            PickObjectCfg,
            PlaceObjectCfg,
        )
        from matterix_sm.robot_action_spaces import (  # type: ignore[import-not-found]
            FRANKA_IK_ACTION_SPACE,
        )
    except ImportError as exc:  # pragma: no cover - runtime-only
        raise SimRuntimeUnavailable("matterix_sm required for translation") from exc

    if step.primitive == "pick_object":
        if not step.target_object:
            raise SchemaError("pick_object requires target_object")
        return PickObjectCfg(
            agent_assets=robot_asset,
            object=step.target_object,
            action_space_info=FRANKA_IK_ACTION_SPACE,
        )
    if step.primitive == "place_at":
        if not step.target_object:
            raise SchemaError("place_at requires target_object")
        return PlaceObjectCfg(
            agent_assets=robot_asset,
            target=step.target_object,
            action_space_info=FRANKA_IK_ACTION_SPACE,
        )
    if step.primitive == "heat":
        return _heat_to_matterix_cfgs(step)
    raise SchemaError(f"primitive {step.primitive!r} has no matterix_sm mapping")


def _heat_to_matterix_cfgs(step: WorkflowStep) -> list[Any]:
    """Translate a 'heat' WorkflowStep to the canonical 3-Cfg sequence.

    [TurnOnHeaterCfg(on, target_temp), WaitCfg(duration), TurnOnHeaterCfg(off)]
    """
    try:
        from matterix_sm import (  # type: ignore[import-not-found]
            TurnOnHeaterCfg,
            WaitCfg,
        )
    except ImportError as exc:  # pragma: no cover - runtime-only
        raise SimRuntimeUnavailable("matterix_sm required") from exc

    if not step.target_object:
        raise SchemaError("heat requires target_object (heater asset name)")
    target_temp_k = step.extras.get("target_temperature_k")
    duration_s = step.extras.get("duration_s")
    if not isinstance(target_temp_k, (int, float)):
        raise SchemaError("heat extras must include 'target_temperature_k' (Kelvin)")
    if not isinstance(duration_s, (int, float)):
        raise SchemaError("heat extras must include 'duration_s' (seconds)")
    return [
        TurnOnHeaterCfg(
            asset_name=step.target_object,
            value=True,
            target_temperature=float(target_temp_k),
        ),
        WaitCfg(duration=float(duration_s)),
        TurnOnHeaterCfg(asset_name=step.target_object, value=False),
    ]


def _obs_to_twin(
    obs: dict[str, Any] | None,
    robot_asset: str,
    env_idx: int = 0,
) -> Observation | None:
    """Translate Matterix nested-tensor obs → twin Observation for one env.

    `env_idx` selects which row of the [num_envs, dim] tensors to read.
    Calibration point — keys come from ObservationManagerCfg; see findings.md.
    Returns None on key mismatch so callers can surface raw_obs instead.
    """
    if obs is None:
        return None
    try:
        articulations = obs["articulations"][robot_asset]
        ee_pos = articulations["robot__ee_world_pos"]
        ee_quat = articulations["robot__ee_world_quat"]
        gripper_pos = articulations.get("robot__gripper_pos")
    except KeyError:
        return None

    ee_pos_l = [float(v) for v in ee_pos[env_idx].tolist()]
    ee_quat_l = [float(v) for v in ee_quat[env_idx].tolist()]
    ee_pose = Pose(
        position=(ee_pos_l[0], ee_pos_l[1], ee_pos_l[2]),
        orientation=(ee_quat_l[0], ee_quat_l[1], ee_quat_l[2], ee_quat_l[3]),
    )

    gripper_width = None
    gripper_closed = False
    if gripper_pos is not None:
        width = float(sum(gripper_pos[env_idx].tolist()))
        gripper_width = width
        gripper_closed = width < 0.04

    return Observation(
        ee_pose=ee_pose,
        gripper_closed=gripper_closed,
        gripper_width=gripper_width,
    )


def _workflow_to_cfg_list(workflow: WorkflowDict, robot_asset: str) -> list[Any]:
    """Flatten a WorkflowDict into a flat list of matterix_sm Cfgs."""
    cfgs: list[Any] = []
    for step in workflow:
        result = _build_matterix_cfgs(step, robot_asset)
        if isinstance(result, list):
            cfgs.extend(result)
        else:
            cfgs.append(result)
    return cfgs


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class WorkflowRunResult:
    """Outcome of a single Matterix workflow run (num_envs=1 typical)."""

    completed: bool
    success: bool
    failure: bool
    step_count: int
    final_observation: Observation | None
    raw_final_obs: dict[str, Any] | None = None  # for debugging / calibration
    extras: dict[str, Any] = field(default_factory=dict)
    # Per-step twin observations collected during the run loop.
    # Index i corresponds to the observation returned after env.step() i+1.
    step_observations: list[Observation] = field(default_factory=list)
    # Raw semantic_actions emitted by sm.step() each tick, keyed by step index.
    # Shape is calibration-pending until run against real Matterix; stored as
    # Any so the caller can inspect and later define a typed schema.
    semantic_events: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class MatterixWorkflowRunner:
    """Drives a real Matterix env via `matterix_sm.StateMachine`.

    Translates twin `WorkflowStep`s into matterix_sm config classes,
    sets the action sequence, runs the env+sm loop until success or
    failure, and converts the final observation back to twin shape.
    """

    env: Any  # gymnasium env from make_real_env()
    robot_asset: str = "robot"
    max_steps: int = 5000

    def run_workflow(self, workflow: WorkflowDict) -> WorkflowRunResult:
        try:
            import torch  # type: ignore[import-not-found]
            from matterix_sm import StateMachine  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - runtime-only
            raise SimRuntimeUnavailable(
                "matterix_sm + torch required for MatterixWorkflowRunner"
            ) from exc

        cfgs = _workflow_to_cfg_list(workflow, self.robot_asset)

        sm = StateMachine(
            num_envs=self.env.num_envs,
            dt=self.env.step_dt,
            device=self.env.device,
        )
        sm.set_action_sequence(cfgs)

        obs, _ = self.env.reset()
        sm.reset()

        step_count = 0
        step_observations: list[Observation] = []
        semantic_events: list[dict[str, Any]] = []
        with torch.inference_mode():
            while step_count < self.max_steps:
                done = sm.action_sequence_success | sm.action_sequence_failure
                if bool(done.all()):
                    break
                action, semantic_actions = sm.step(obs)
                action = action.to(self.env.device)
                obs, _, terminated, truncated, _ = self.env.step(
                    action, semantic_actions=semantic_actions
                )
                step_count += 1

                twin_obs = _obs_to_twin(obs, self.robot_asset)
                if twin_obs is not None:
                    step_observations.append(twin_obs)
                semantic_events.append({"step": step_count, "raw": semantic_actions})

                reset_ids = (terminated | truncated).nonzero(as_tuple=False).flatten()
                if reset_ids.numel() > 0:
                    sm.reset_envs(reset_ids)

        success = bool(sm.action_sequence_success.all())
        failure = bool(sm.action_sequence_failure.all())
        return WorkflowRunResult(
            completed=success or failure,
            success=success,
            failure=failure,
            step_count=step_count,
            final_observation=_obs_to_twin(obs, self.robot_asset),
            raw_final_obs=obs,
            step_observations=step_observations,
            semantic_events=semantic_events,
        )
