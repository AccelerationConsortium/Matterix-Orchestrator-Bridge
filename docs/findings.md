# Findings — Living Log

> Every assumption in `docs/project-charter.md §5` is tracked here.
> Mark verified ✅ / falsified ❌ / deferred ⏸ / partial ◐.
> Don't delete failed attempts — phase 2 inherits the lessons.

## Assumption status

| ID  | Statement | Status | Notes |
|-----|-----------|--------|-------|
| A1  | matterix_sm configs-only is CPU-installable | ✅ verified by source | Confirmed via `source/matterix_sm/_compat.py` in `AccelerationConsortium/Matterix`: explicit fallback when Isaac Lab is not importable. README states *"matterix_sm will auto-detect Isaac Lab and include full functionality"* and supports `pip install -e .[minimal]`. Smoke install on lab machine still TBD. |
| A2  | Matterix obs/action wraps cleanly into ExecutorBackend protocol | ◐ partial → revised | **Partial — with revised design.** Confirmed via inspection of `scripts/run_workflow.py` and `test_franka_beaker_lift.py`: real Matterix is workflow-level, not per-step. Per-step `ExecutorBackend.step()` does NOT cleanly map to `matterix_sm.StateMachine` (which is a vectorised GPU loop). Workflow-level path now wired via new `MatterixWorkflowRunner` (`twin_sim/real_runner.py`); per-step path remains for mock/real-stub/FakeMatterixEnv only. Phase-2: lift `execute_workflow` into the protocol. |
| A3  | `pickup_beaker` workflow runs end-to-end on Day 1 | ⏸ deferred → ready to verify | Smoke test wired in `examples/06_run_real_matterix.py`. Run on Linux lab machine per `docs/lab-quickstart.md`. |
| A4  | Asset frames suffice for PickAndPlace level | ✅ verified by source | Confirmed: `test_franka_beaker_lift.ObservationManagerCfg.RigidObjectsGroup` exposes `beaker__pre_grasp_frame`, `beaker__grasp_frame`, `beaker__post_grasp_frame` — exactly the names in `StaticFrameService.default_for_demo()`. Place-side dropoff frames will need to be added once a task with a dropoff target exists (stock beaker-lift task only does pickup). |

## Confirmed against actual Matterix source

Inspected via `gh api` against `AccelerationConsortium/Matterix` on 2026-04-30.

### How real Matterix actually constructs an env

```python
from isaaclab.app import AppLauncher          # MUST run first
from isaaclab_tasks.utils.parse_cfg import parse_env_cfg
import gymnasium as gym
import matterix_tasks                          # registers tasks

env_cfg = parse_env_cfg(task, device, num_envs, use_fabric=True)
env = gym.make(task, cfg=env_cfg).unwrapped
env.reset()                                    # returns (obs, info)
```

### Real obs shape (from `test_franka_beaker_lift.ObservationManagerCfg`)

Nested dict of torch tensors (`[num_envs, dim]`), keys with `__` separators:

- `obs["articulations"]["robot"]["robot__ee_world_pos"]` (3,)
- `obs["articulations"]["robot"]["robot__ee_world_quat"]` (4,)
- `obs["articulations"]["robot"]["robot__joint_pos"]` (7,)
- `obs["articulations"]["robot"]["robot__gripper_pos"]` (2,) — Robotiq85 fingers
- `obs["rigid_objects"]["beaker"]["beaker__grasp_frame"]` (7-D pose)

### Real action shape

Returned by `matterix_sm.StateMachine.step(obs)` as `(action_tensor, semantic_actions)`.
`env.step(action, semantic_actions=...)` is the (non-standard) call signature.

### Workflow registration

Workflows are part of the env config:

```python
workflows = {
    "pickup_beaker": PickObjectCfg(
        agent_assets="robot",
        object="beaker",
        action_space_info=FRANKA_IK_ACTION_SPACE,
    )
}
```

### `PickObjectCfg` underlying sequence

Per `source/matterix_sm/compositional_actions/pick_object.py`:

```
OpenGripper → MoveToFrame(pre_grasp) → MoveToFrame(grasp) →
CloseGripper → MoveRelative(post_grasp_offset = (0,0,0.1))
```

Our `lower_workflow()` produces a near-identical 4-step pick (we
emit `pre_grasp → grasp → close → post_grasp`; we skip the leading
`OpenGripper` because the gripper starts open, but that's a benign
divergence and Matterix's `OpenGripper` is also a no-op when already open).

## Platform risk

Matterix README badges only list `linux-64` and `windows-64`. Mac
(darwin) is not in the support matrix. The bridge code itself is
cross-platform (we built and tested on darwin). Real Matterix execution
must happen on a Linux box.

## Asset reality vs the bridge's frame service

Inspected `AccelerationConsortium/Matterix_assets` and the stock
`test_franka_beaker_lift` task config on 2026-04-30. Findings below.

### Asset inventory (only 5 USD assets exist)

| Type | Asset | bridge name | notes |
|------|-------|-------------|-------|
| labware | `beaker500ml` | `beaker` | scene-key in stock task. Has `pre_grasp` / `grasp` / `post_grasp` frames (object-local) |
| infrastructure | `table-thorlabs-75x90` | `table` | scene-key in stock task. **No dropoff frames declared** |
| equipment | `IKA-plate-inst` | `hotplate` | not in stock task; needs new task config to use |
| equipment | `scale-IKA` | (unused) | not in stock task |
| robots | `franka-robotiq85` | `robot` | scene-key in stock task |

**Updated `StaticFrameService.default_for_demo()`** to use the real
scene-keys (`beaker`, `table`, `hotplate`) instead of the placeholder
names (`beaker_500ml`, `optical_table`). This means `examples/06`'s
default `--target_object beaker` matches the stock task on first run.

### Frame conventions

Real Matterix frame naming as observed:
- `pick_object` target: always `grasp` (with `pre_grasp` / `post_grasp` for the lift).
- `place_at` target: always `place` (with `pre_place`). PlaceObjectCfg
  hard-codes these names — they MUST exist on the asset USD.
- `dropoff_*`: **not a Matterix convention**. It's our fake-sim multi-slot
  shorthand. The schema_check policy now allows BOTH `place` (Matterix
  canonical) and `dropoff_*` prefix (fake-sim demos).

### sdl1chem catalogue is a different physical stack

Inspected `AccelerationConsortium/sdl1chem` UO catalogue (31 UOs). It
targets **OT-2 robot + PLC pumps + Squidstat potentiostat + relays** —
none of which exist in Matterix. The bridge does NOT mirror these UOs
because they have no Matterix asset to act on. The pattern is what the
bridge follows: each UO is a typed input + typed output, decorated
function. We stay aligned with that pattern; we don't depend on the
specific hardware vocabulary.

Phase-2 question: if a future SDL stack uses Franka + beaker (i.e.,
shares Matterix's hardware), should we wrap matching sdl1chem-style UOs
into the bridge for direct compatibility? Currently undecided — answer
depends on whether `uostore` becomes the standard UO framework.

## Workflow-level vs per-step path (clarification)

The user's question "Is StateMachine the connection entry point?" — yes.

Two execution paths now coexist:

```
                   ┌──────────────────────────────────────┐
                   │  Mock / RealStub / FakeMatterixEnv   │
                   │  (per-step)                          │
PickAndPlace ──┐   │  Action.step(action) loop            │
               │   └──────────────▲───────────────────────┘
WorkflowDict───┤                  │ Action[]
               │                  │ via lower_workflow()
Heat ──────────┘                  │
               │   ┌──────────────┴───────────────────────┐
               │   │  Real Matterix env                   │
               │   │  (workflow-level)                    │
               │   │  matterix_sm.StateMachine.step(obs)  │
               │   │  loop                                │
               └──>│  via MatterixWorkflowRunner          │
                   │  CompositionalActionCfg[] / Cfg[]    │
                   └──────────────────────────────────────┘
```

`MatterixWorkflowRunner.set_action_sequence(...)` is the literal
connection point (the line that hands our translated configs to the
real Matterix StateMachine).

## UnitOperations now defined

| UO | Inputs | Outputs (observable side-effect) | Matterix mapping |
|----|--------|----------------------------------|------------------|
| `PickAndPlace` | source_object, source_frame, target_object, target_frame | beaker moved to target | `PickObjectCfg` → `PlaceObjectCfg` |
| `Heat` | asset_name, target_temperature_k, duration_s | heater state change (IsHeaterOn) | `TurnOnHeaterCfg(on)` → `WaitCfg` → `TurnOnHeaterCfg(off)` |

Adding a new UO is: dataclass + extend `operation_to_workflow` + extend
`_step_to_matterix_cfg` + (optional) extend `lower_workflow` for the
per-step path. Roughly 30-50 lines of code per UO.

## Decisions made under deferred verification

These are recorded so a human can quickly audit them once Matterix is
actually installed.

### D-001: v0 Observation schema fields

Chosen: `ee_pose: Pose`, `gripper_closed: bool`, `extras: dict`.

Reasoning: minimum needed to demonstrate PickAndPlace and to detect
divergence between sim and real-stub. Real Matterix observation manager
likely exposes joint positions, contact forces, and per-camera frames; the
`extras` dict is the calibration escape hatch.

To verify: import Matterix observation manager, dump field names + dtypes,
update `twin_core.schemas.Observation` and the contract tests.

### D-002: v0 Action schema fields

Chosen: `target_pose: Pose | None`, `gripper_command: "open"|"close"|None`,
`extras: dict`.

Reasoning: matches the action_dict abstraction described in plan §6.1
(target pose + gripper cmd is the minimum useful action). Real `action_dict`
may be joint-space deltas or a higher-level (pick_object, frame=...) command.

To verify: dump a single action_dict from a running Matterix env. If it is
joint-space, add a `joint_positions` variant; if it is symbolic, change the
translator (`operation_to_workflow`) rather than the schema.

### D-003: Workflow representation

Chosen: `WorkflowDict = list[dict[str, Any]]` for now, with each dict
containing at minimum `{"action": str, "object": str, "frame": str}`.

Reasoning: Matterix `pickup_beaker` is described as a sequence of named
sub-workflows. Until the actual `WorkflowDict` shape is in hand, keep the
type loose and make the translator the single point of update.

### D-004: FrameService registry

Chosen: a static registry `dict[asset_id, dict[frame_name, Pose]]` for the
configs-only path.

Reasoning: the actual sim path will read from USD asset config; the static
registry mirrors the `beaker_500ml` and `optical_table` frames documented in
plan §5/A4 so safety-layer tests can pass without USD.

To verify: replace registry with a USD reader once Matterix is installed;
contract tests should keep passing.

## Issues encountered

### I-001: `uv sync` did not install workspace packages

Day 0. Root `pyproject.toml` declared workspace members and `tool.uv.sources`
but had no `dependencies = [...]` entry, so `twin-core` was not installed in
the venv and `from twin_core import ...` failed in tests. Fixed by adding
`dependencies = ["twin-core", "twin-sim", "twin-real"]` to `[project]`.

### I-002: `WorkflowDict` import location

Day 2. `twin_core.lowering` and `twin_sim.dry_run` initially imported
`WorkflowDict` from `twin_core.schemas`; the alias actually lives in
`twin_core.operations`. Tests caught it on first run (4 collection
errors). Fixed by importing from the correct module — re-exporting it
from `twin_core.schemas` was rejected to keep the schemas/operations
boundary clean.

## Things that remain unknown (open questions for human)

- Does Matterix expose a synchronous `step()` or only an async one?
  Schema currently assumes sync. If async, wrap with `asyncio.run` in the
  sim backend or change the `ExecutorBackend.step` signature.
- How does Matterix report a workflow-level failure (collision, IK fail) —
  exception, return code, or observation field? Currently `dry_run` assumes
  exception.
- Is there a stable `frame_name` convention, or do per-asset configs use
  bespoke names? Affects how `FrameService.lookup` maps to USD lookups.

## End-of-PoC summary

Status at Day 10: **57/57 tests passing, 6 runnable demo examples**, all
three Demo points from the charter satisfied without a Matterix install.

What's verified by the codebase itself:
- ExecutorBackend protocol is implementable by three independent
  backends (mock, sim+fake, real-stub) with the same contract test
  suite.
- The lowering layer translates a `PickAndPlace` into 8 actions
  identically across all backends.
- The 4-class error taxonomy (`SchemaError`, `FrameNotFound`,
  `PhysicalInfeasibility`, `StateMachineViolation`) is each triggered
  by at least one structured demo case.
- Sim-first gating prevents a known-bad plan from reaching the real
  backend (verified by `test_sim_first_blocks_real_when_sim_fails`).

What requires the Matterix install before going further:
- A1, A3 (status ⏸): full validation of `matterix_sm` configs-only
  installability and `pickup_beaker` end-to-end run.
- A2, A4 (status ◐): one-time calibration of the two converter
  functions in `twin_sim.backend` and the frame registry in
  `StaticFrameService.default_for_demo()` against actual Matterix
  output.
