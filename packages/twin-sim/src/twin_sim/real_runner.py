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


@dataclass
class WorkflowRunResult:
    """Outcome of a Matterix workflow run."""

    completed: bool
    success: bool
    failure: bool
    step_count: int
    final_observation: Observation | None
    raw_final_obs: dict[str, Any] | None = None  # for debugging / calibration
    extras: dict[str, Any] = field(default_factory=dict)


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

        # Each step lowers to one or more matterix_sm Cfgs (heat → 3 cfgs).
        actions: list[Any] = []
        for step in workflow:
            cfgs = self._step_to_matterix_cfg(step)
            if isinstance(cfgs, list):
                actions.extend(cfgs)
            else:
                actions.append(cfgs)

        sm = StateMachine(
            num_envs=self.env.num_envs,
            dt=self.env.step_dt,
            device=self.env.device,
        )
        sm.set_action_sequence(actions)

        obs, _ = self.env.reset()
        sm.reset()

        step_count = 0
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
            final_observation=self._obs_to_twin(obs),
            raw_final_obs=obs,
        )

    # -- translation: WorkflowStep → matterix_sm config -----------------

    def _step_to_matterix_cfg(self, step: WorkflowStep) -> Any:
        """Translate one WorkflowStep into a matterix_sm action config.

        Note: action_space_info is asset-specific. Default is FRANKA_IK
        (matches the stock beaker-lift task). Override by subclassing.
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
            raise SimRuntimeUnavailable(
                "matterix_sm required for translation"
            ) from exc

        if step.primitive == "pick_object":
            if not step.target_object:
                raise SchemaError("pick_object requires target_object")
            return PickObjectCfg(
                agent_assets=self.robot_asset,
                object=step.target_object,
                action_space_info=FRANKA_IK_ACTION_SPACE,
            )
        if step.primitive == "place_at":
            if not step.target_object:
                raise SchemaError("place_at requires target_object")
            # PlaceObjectCfg uses `target=`, not `object=`. The cfg
            # internally always targets the asset's `pre_place` + `place`
            # frames — `target_frame` on our WorkflowStep is therefore
            # informational only (used by fake sim, ignored here).
            return PlaceObjectCfg(
                agent_assets=self.robot_asset,
                target=step.target_object,
                action_space_info=FRANKA_IK_ACTION_SPACE,
            )
        if step.primitive == "heat":
            return self._heat_step_to_cfgs(step)
        raise SchemaError(
            f"primitive {step.primitive!r} has no matterix_sm mapping"
        )

    def _heat_step_to_cfgs(self, step: WorkflowStep) -> list[Any]:
        """Translate a single 'heat' WorkflowStep to a 3-Cfg sequence.

        Returns [TurnOnHeaterCfg(on, with target_temp), WaitCfg(duration),
        TurnOnHeaterCfg(off)] — the canonical pattern from
        `matterix_sm.semantic_actions.heater_action` docstring.
        """
        try:
            from matterix_sm import (  # type: ignore[import-not-found]
                TurnOnHeaterCfg,
                WaitCfg,
            )
        except ImportError as exc:  # pragma: no cover - runtime-only
            raise SimRuntimeUnavailable("matterix_sm required") from exc

        if not step.target_object:
            raise SchemaError("heat requires target_object (the heater asset name)")
        target_temp_k = step.extras.get("target_temperature_k")
        duration_s = step.extras.get("duration_s")
        if not isinstance(target_temp_k, (int, float)):
            raise SchemaError(
                "heat extras must include 'target_temperature_k' (Kelvin)"
            )
        if not isinstance(duration_s, (int, float)):
            raise SchemaError(
                "heat extras must include 'duration_s' (seconds)"
            )
        return [
            TurnOnHeaterCfg(
                asset_name=step.target_object,
                value=True,
                target_temperature=float(target_temp_k),
            ),
            WaitCfg(duration=float(duration_s)),
            TurnOnHeaterCfg(asset_name=step.target_object, value=False),
        ]

    # -- translation: Matterix obs → twin Observation ------------------

    def _obs_to_twin(self, obs: dict[str, Any] | None) -> Observation | None:
        """Translate Matterix nested-tensor obs → twin Observation.

        Calibration point — keys come from
        `test_franka_beaker_lift.ObservationManagerCfg`. Adjust if the
        env config changes the key naming convention.
        """
        if obs is None:
            return None
        try:
            articulations = obs["articulations"][self.robot_asset]
            ee_pos = articulations["robot__ee_world_pos"]
            ee_quat = articulations["robot__ee_world_quat"]
            gripper_pos = articulations.get("robot__gripper_pos")
        except KeyError:
            # Calibration mismatch — surface the raw obs for the caller
            # to inspect rather than failing silently.
            return None

        # Tensors are [num_envs, dim]. Take env 0 and convert to plain Python.
        ee_pos_l = [float(v) for v in ee_pos[0].tolist()]
        ee_quat_l = [float(v) for v in ee_quat[0].tolist()]
        ee_pose = Pose(
            position=(ee_pos_l[0], ee_pos_l[1], ee_pos_l[2]),
            orientation=(ee_quat_l[0], ee_quat_l[1], ee_quat_l[2], ee_quat_l[3]),
        )

        gripper_width = None
        gripper_closed = False
        if gripper_pos is not None:
            # Robotiq85: total opening = sum of two finger joints. Use
            # threshold below half-open as "closed".
            width = float(sum(gripper_pos[0].tolist()))
            gripper_width = width
            gripper_closed = width < 0.04

        return Observation(
            ee_pose=ee_pose,
            gripper_closed=gripper_closed,
            gripper_width=gripper_width,
        )
