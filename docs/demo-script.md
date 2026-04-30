# 5-Minute Demo Script

Reference for the leadership walkthrough. Hits all three Demo points
from the project charter §3, in order.

## Setup (off-camera, 30s)

```bash
cd "DT-Orchestrator Bridge PoC"
uv sync
uv run pytest -q   # show 57 passed
```

The "57 passed in 0.07s" is the opening: protocol-first means every
backend is interchangeable through the same contract test suite — three
backends (mock, sim, real-stub), one suite, all green.

## Demo 1 — Same plan, two backends (90s)

> "The same `PickAndPlace` plan runs on the Matterix sim path and on
> the real-hardware-stub path. The plan source does not change."

```bash
uv run python examples/02_orchestrator_to_sim.py
uv run python examples/03_orchestrator_to_real_stub.py
```

Point out:
- The 8-action sequence (`pre_grasp → grasp → close → post_grasp →
  pre_dropoff → dropoff → open → retract`) is identical between the
  two runs.
- The orchestrator code is identical — only the backend changes.
- Lowering happens once in `twin_core.lowering`; both backends consume
  the same `Action` stream.

## Demo 2 — Safety interception (90s)

> "Sim catches three classes of unsafe ops before they reach real."

```bash
uv run python examples/04_safety_demo.py
```

Walk through the four cases:
- **WF1** — `SchemaError`: wrong frame type for `pick_object`. Caught
  by `preflight()` before any backend is touched.
- **WF2** — `FrameNotFound`: `dropoff_z9` not declared on
  `optical_table`. Caught by `frame_check`.
- **WF3** — `PhysicalInfeasibility`: dropoff inside a no-go region in
  sim. Caught by `dry_run`.
- **WF4** — clean. Passes both layers.

## Demo 3 — Arbitrator mode switch (60s)

> "A mode flag controls dispatch. In `sim_first_then_real`, a plan
> that fails sim never reaches real."

```bash
uv run python examples/05_sim_first_then_real.py
```

Point out:
- Case 1: `sim_dry_run` fails → `real_run: NOT EXECUTED`. The real
  backend never sees the bad plan.
- Case 2: `sim_dry_run` passes → `real_run: completed=True steps=8`.
  Same plan flows through to real.

## Wrap (30s)

> "Two weeks. ~1500 lines of Python. Three backends behind one
> protocol, four error classes caught structurally, three dispatch
> modes. No Matterix install needed for the contract tests — when we
> drop the real Matterix runtime in, only the wrapper functions in
> `twin_sim.backend` need to be calibrated against actual obs/action
> shapes. Phase 2 is real Franka + the SiLA backend slot."

## Q&A backstops

- **"Does sim actually run Matterix?"** — In this PoC, sim runs a
  `FakeMatterixEnv` that mimics the obs/action_dict shape. The
  `RealMatterixEnv` slot is wired up but gated on `matterix_sm`; the
  unverified A1/A2/A3 assumptions are explicitly tracked in
  `docs/findings.md`.
- **"Why not start with SiLA?"** — Charter §4 non-goals: SiLA is a
  phase-2 backend slot. Forcing SiLA into the protocol now would let
  one external standard shape an abstraction we haven't yet validated
  against any real hardware.
- **"What if Matterix changes upstream?"** — Adapter-only (ADR 0003).
  Two functions in `twin_sim.backend` are the single calibration
  surface.
