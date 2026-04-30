# Lab Machine Quickstart

For the first run on the Linux lab machine. Goal: clone, set up, and
verify that all 57 tests pass plus the real-Matterix smoke test runs.

## Prerequisites

- Linux x86_64 (Mac is not supported by Matterix per their README badges)
- Python 3.11
- conda (recommended for Isaac Lab)
- NVIDIA GPU + drivers + CUDA 12.x (Isaac Sim 5.0 requirement)

## Step 1 — Clone & verify the bridge runs without Matterix

```bash
# wherever you clone:
git clone <bridge-repo-url> dt-orchestrator-bridge
cd dt-orchestrator-bridge

# uv if missing
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync
uv run pytest -q             # expect: 57 passed
uv run python examples/00_hello_mock.py
uv run python examples/02_orchestrator_to_sim.py
uv run python examples/03_orchestrator_to_real_stub.py
uv run python examples/04_safety_demo.py     # 3 caught, 1 passes
uv run python examples/05_sim_first_then_real.py
```

If all 57 tests pass and the 5 examples print expected output, the
bridge code is healthy on this machine. **None of the above touches
Matterix.**

## Step 2 — Install Matterix runtime

Per `AccelerationConsortium/Matterix` README:

```bash
# Create the Isaac Lab conda env
conda create -n isaaclab python=3.11
conda activate isaaclab
pip install --upgrade pip
pip install -U torch==2.7.0 torchvision==0.22.0 \
    --index-url https://download.pytorch.org/whl/cu128
pip install isaaclab[isaacsim,all]==2.3.0 \
    --extra-index-url https://pypi.nvidia.com

# Clone Matterix (separately from this bridge repo)
cd ..
git lfs install
git clone --recurse-submodules https://github.com/ac-rad/Matterix.git
cd Matterix
git submodule foreach 'git lfs pull'
python -m pip install -e source/*  # installs matterix_sm, _assets, _tasks, matterix
```

## Step 3 — Smoke-test the real Matterix path

From the bridge repo, with the `isaaclab` conda env active:

```bash
cd dt-orchestrator-bridge

# uv inherits the active conda env when no .venv is preferred:
uv run --no-sync python examples/06_run_real_matterix.py --headless

# Alternative: use Matterix's launcher script (preserves Isaac env vars):
/path/to/Matterix/matterix.sh -p examples/06_run_real_matterix.py --headless
```

Expected (rough):

```
[smoke] launching task='Matterix-Test-Beaker-Lift-Franka-v1' num_envs=1
[smoke] env ready: num_envs=1 step_dt=... device=cuda:0
[smoke] running workflow (1 step(s))...
[smoke] completed=True success=True failure=False step_count=...
[smoke] final ee=(x, y, z) gripper_closed=True gripper_width=...
```

If `success=True`: **A1 + A3 verified ✅**. The bridge can drive real
Matterix end-to-end. Update `docs/findings.md` accordingly.

## Step 4 — Likely calibration touch-ups

These are the four locations to update if behavior diverges from
expected. Each is documented inline in the code.

| Symptom | File / function | What to adjust |
|---------|-----------------|----------------|
| `[smoke] WARNING: could not translate final obs` | `packages/twin-sim/src/twin_sim/real_runner.py` → `MatterixWorkflowRunner._obs_to_twin` | Update key names to match the task's `ObservationManagerCfg`. Task config is in the Matterix repo under `source/matterix_tasks/`. |
| `agent_assets="robot"` doesn't match task's articulation name | `_step_to_matterix_cfg` in same file | Pass the right `robot_asset` when constructing `MatterixWorkflowRunner`. |
| Frame-existence check fails for actual asset | `packages/twin-sim/src/twin_sim/frame_service.py` → `StaticFrameService.default_for_demo` | Replace static registry with a USD reader, OR update the registry to mirror the asset's actual frames. |
| Action space tensor shape mismatch | `_step_to_matterix_cfg` — `FRANKA_IK_ACTION_SPACE` | Use the action-space constant matching your robot. Per Matterix, this is on `matterix_sm.robot_action_spaces`. |

## Step 5 — Push verified state

After the smoke test passes, the bridge has demonstrated end-to-end
operation against real Matterix. Suggested next:

1. Commit `docs/findings.md` updates marking A1/A3 verified.
2. Open a phase-2 issue: lift `execute_workflow` into the
   `ExecutorBackend` protocol so the Arbiter can transparently drive
   the workflow-level path (currently bypassed via
   `MatterixWorkflowRunner`).
3. Add a `place_at` smoke test once a task with dropoff frames exists
   (the stock beaker-lift task only has `pickup_beaker`).

## Troubleshooting

- **`AppLauncher` import error**: Isaac Lab not installed in the active
  env. Re-check Step 2.
- **`No module named matterix_tasks`**: Matterix `pip install -e source/*`
  step missed. Re-run from the Matterix repo with the conda env active.
- **`Workflow 'pickup_beaker' not found`**: the task name is wrong or
  not registered. Run `python /path/to/Matterix/scripts/list_workflows.py
  --task Matterix-Test-Beaker-Lift-Franka-v1` to confirm registration.
- **CUDA OOM / GPU not found**: pass `--device cpu` to the example, but
  note Matterix is GPU-optimized — expect very slow simulation.
