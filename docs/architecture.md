# Architecture

## One-page picture

```
                         ┌────────────────────────────────────┐
                         │   user code / SDL plan author      │
                         │   (constructs UnitOperation list)  │
                         └─────────────────┬──────────────────┘
                                           │
                                           ▼
                         ┌────────────────────────────────────┐
                         │            Arbiter                  │
                         │  mode = sim_only / real_only /      │
                         │         sim_first_then_real         │
                         │                                     │
                         │   ① preflight (schema/frame/state)  │
                         │   ② sim_dry_run  (gate, optional)   │
                         │   ③ MiniOrchestrator.run(...)       │
                         └────┬───────────────────────────┬────┘
                              │                           │
                              │ via lower_workflow()      │
                              │                           │
                              ▼                           ▼
            ┌────────────────────────┐      ┌────────────────────────┐
            │   SimBackend           │      │   RealStubBackend      │
            │   (twin-sim)           │      │   (twin-real)          │
            │                        │      │                        │
            │   wraps a              │      │   internal SM:         │
            │   MatterixEnvLike:     │      │     gripper open/close │
            │     • FakeMatterixEnv  │      │     ee_pose            │
            │     • RealMatterixEnv  │      │   simulated latency    │
            │       (gated import)   │      │   failure injection    │
            └────────────────────────┘      └────────────────────────┘
                              ▲                           ▲
                              │                           │
                              └───────────┬───────────────┘
                                          │
                                ExecutorBackend protocol
                                  (defined in twin-core)
```

The contract everyone speaks: `ExecutorBackend.{reset, step, close}`,
`Action`, `Observation`, `Pose`, `WorkflowStep`. Those five types are
the entire cross-package interface.

## Package layout & dependency direction

```
twin-core   ◀── twin-sim       (twin-sim depends on twin-core)
   ▲
   └── twin-real                (twin-real depends on twin-core)
```

`twin-core` has zero runtime imports of Matterix or Isaac, by design
(see ADR 0001). The arbitrator is in `twin-core` but receives the sim
dry-run as a `Callable` — so `twin-core` doesn't import `twin-sim`.

## Key components

| Module                           | Role                                                                    |
|----------------------------------|-------------------------------------------------------------------------|
| `twin_core.protocols`            | `ExecutorBackend`, `FrameService` Protocols                             |
| `twin_core.schemas`              | `Pose`, `Observation`, `Action`, `WorkflowStep` (Pydantic v2)           |
| `twin_core.errors`               | `ValidationError` taxonomy (4 leaf classes)                              |
| `twin_core.operations`           | `PickAndPlace`, `operation_to_workflow()` translator                    |
| `twin_core.lowering`             | `lower_workflow()` — `WorkflowStep[]` → `Action[]` via FrameService      |
| `twin_core.orchestrator`         | `MiniOrchestrator` — single backend dispatch                             |
| `twin_core.validation`           | `preflight()` — schema + frame + state-machine pre-flight gate          |
| `twin_core.arbiter`              | `Arbiter` + `Mode` — sim/real/sim-first dispatch                         |
| `twin_core.mock_backend`         | `MockBackend` — contract-test reference impl                             |
| `twin_sim.backend`               | `SimBackend`, `FakeMatterixEnv`, `make_real_env()` (gated)              |
| `twin_sim.frame_service`         | `StaticFrameService` (USD reader is the future drop-in)                  |
| `twin_sim.dry_run`               | `dry_run()` — sim-side PhysicalInfeasibility check                      |
| `twin_real.backend`              | `RealStubBackend`, `CommunicationError`                                  |

## Plan flow

```
PickAndPlace
   │  operation_to_workflow()
   ▼
[WorkflowStep(pick_object), WorkflowStep(place_at)]
   │
   ├──── preflight(workflow, frames) ───── SchemaError / FrameNotFound / StateMachineViolation
   │                                       (no backend touched)
   │
   ├──── dry_run(workflow, sim_backend, frames) ──── PhysicalInfeasibility
   │                                                  (sim only; real not touched)
   │
   ▼  lower_workflow(workflow, frames)
[Action(pre_grasp), Action(grasp), Action(close), Action(post_grasp),
 Action(pre_dropoff), Action(dropoff), Action(open), Action(retract)]
   │
   ▼  for each: backend.step(action)
Observation stream → RunRecord
```

## Calibration boundary

The points where `twin-core` schemas meet Matterix shapes are isolated:

  * `twin_sim.backend._action_to_matterix_dict` — twin Action → Matterix `action_dict`
  * `twin_sim.backend._matterix_obs_to_observation` — Matterix obs dict → twin Observation

Once `matterix_sm` is installed and a real env is running, only these two
functions need to be re-checked against the actual Matterix shape (see
findings.md A1/A2/A3). The rest of the codebase stays unchanged.
