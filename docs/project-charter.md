# Project Charter — DT-Orchestrator Bridge PoC

## 1. One-line positioning

Prove that the Matterix digital twin can be integrated with an SDL
orchestrator, and that this integration delivers measurable safety value
before plans reach real hardware.

## 2. Project purpose

The current SDL orchestrator (unit-operation framework) and the digital
twin (Matterix) live in two disconnected worlds — the orchestrator pushes
plans straight to real hardware, and the digital twin only runs inside its
own simulation environment. This split causes two problems:

- Plans reach hardware without any dynamics-level validation. Schema checks
  cannot tell you "this trajectory will hit the optical table".
- The twin's physics capabilities (IK, collision detection, state machines)
  are invisible to the orchestrator and therefore not reused.

This project introduces a thin contract layer that connects the two worlds.
The same unit-operation plan runs both inside Matterix sim and against a
real-hardware interface (a stub here), and sim is positioned as the
pre-flight gate for the latter.

This is an **operational digital twin** PoC. It simulates the physical
executability of workflows, not chemical outputs.

## 3. Definition of success

Within two weeks, deliverable in a 5-minute leadership demo:

**Demo 1 — same plan, two backends.** A `PickAndPlace` unit operation is
emitted by the mini-orchestrator, executed first in Matterix sim (visible
Franka picks beaker), then the same plan against the real-stub (consistent
action sequence; stub state advances correctly). The plan source does not
change between runs.

**Demo 2 — safety interception.** Four deliberately-constructed workflows;
at least three are caught by sim before reaching real, each with an explicit
error class and reason:

- `SchemaError`: references a frame type the schema disallows
- `FrameNotFound`: asset does not declare this frame
- `PhysicalInfeasibility`: sim dry-run finds collision or unreachable target
- A fourth workflow passes all checks and runs cleanly

**Demo 3 — arbitrator mode switch.** A mode flag controls dispatch:
`sim_only` / `real_only` / `sim_first_then_real`. In the third mode, plans
that fail sim never reach real.

## 4. Non-goals

These are explicitly out of scope. They are recorded so scope creep is
deliberate, not accidental.

- No real hardware — replaced by `twin-real` stub. If the PoC succeeds, a
  Franka comes in phase 2.
- No zinc battery / electrochemistry. Demo uses only stock Matterix assets.
- No chemical-output simulation — operational twin only.
- No USD asset authoring. 100% reuse of `beaker_500ml` + Franka + Robotiq85
  + optical table.
- No refactoring of existing SDL orchestrator code. A standalone
  `MiniOrchestrator` is written here, depending on no SDL project.
- No SiLA / UniteLabs integration. The architecture leaves a slot for it
  (a SiLA `ExecutorBackend` is a phase-2 add), but the PoC does not
  implement one.
- No shadow mode / divergence detection. Stretch goal — skipped if Day 6-8
  ran long.

## 5. Critical assumptions

The project succeeds only if these hold. If any is falsified, scope must
be re-discussed.

- **A1**: `matterix_sm` configs-only mode can be installed and used
  independently of Isaac Sim — `PickObjectCfg`, `MoveCfg`, etc. importable
  on a CPU-only machine.
- **A2**: Matterix's observation/action abstraction (`action_dict` +
  observation manager) can be wrapped in a thin shim that satisfies the
  generic `ExecutorBackend` protocol.
- **A3**: Matterix's stock pick-and-place workflow (`pickup_beaker`) runs
  end-to-end on Day 1 — the existential gate. If it does not, re-evaluate.
- **A4**: The frames defined in Matterix asset configs (`pre_grasp`,
  `grasp`, `post_grasp`, ...) are sufficient to express a `PickAndPlace`
  unit operation. The orchestrator side does not need to introduce new
  spatial primitives.

A1/A2 verified during Day 0-1 spike. A3 during Day 1. A4 during Day 2-3.

## 6. Functional requirements

Reproduced verbatim from the planning discussion. See `plan.md` for
day-by-day execution.

### 6.1 Contract layer (twin-core)

- FR-1.1: `ExecutorBackend` protocol — `reset() / step(action) / close()`
- FR-1.2: `Observation` and `Action` schemas matching Matterix shapes
- FR-1.3: `FrameService` protocol — `lookup(asset_id, frame_name) -> Pose`
- FR-1.4: `PickAndPlace` dataclass + `operation_to_workflow()` translator
- FR-1.5: `ValidationError` hierarchy (`SchemaError`, `FrameNotFound`,
  `PhysicalInfeasibility`, `StateMachineViolation`)

### 6.2 Sim backend (twin-sim)

- FR-2.1: configs-only mode — works without Isaac runtime, used for
  schema/frame lint
- FR-2.2: full sim mode — wraps Matterix env, runs `pickup_beaker`
- FR-2.3: sim dry-run — fast-forward a plan, return ok/fail + reason

### 6.3 Real-stub backend (twin-real)

- FR-3.1: implements `ExecutorBackend`, identical interface to sim
- FR-3.2: internal state (gripper, ee pose); raises `StateMachineViolation`
- FR-3.3: simulated latency 0.5–2s per action
- FR-3.4: configurable failure injection via env var

### 6.4 Mini-orchestrator

- FR-4.1: accepts `list[UnitOperation]`, dispatches via backend
- FR-4.2: single-step interruptible / inspectable

### 6.5 Arbitrator

- FR-5.1: modes `sim_only` / `real_only` / `sim_first_then_real`
- FR-5.2: in third mode, sim failure halts dispatch and propagates error

### 6.6 Safety layer

- FR-6.1: pre-flight schema check
- FR-6.2: frame existence check via `FrameService`
- FR-6.3: sim dry-run check (FR-2.3)
- FR-6.4: each interception emits a structured log (error class, location,
  plan segment)

## 7. Sequencing

Protocol-first. Both ends are implementations of the same protocol; the
protocol is written first, both ends are calibrated to it.
