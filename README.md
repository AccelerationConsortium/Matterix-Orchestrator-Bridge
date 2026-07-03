# DT-Orchestrator Bridge — PoC

Bridges a mini SDL orchestrator with the Matterix digital twin.
Same `PickAndPlace` plan runs on both sim and a real-stub; sim acts as a
pre-flight gate that catches unsafe ops before they reach real hardware.

> Stock Matterix assets only (Franka + Robotiq85 + beaker_500ml). No zinc
> battery. No real hardware. No USD authoring. See `plan.md` for the full
> 10-day execution checklist and `docs/project-charter.md` for the charter.

## Quick start

```bash
# Install uv if missing: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run pytest
uv run python examples/00_hello_mock.py
```

## Orchestrator JSON → Matterix demo

The real-Matterix heat-transfer demo now reads a workflow JSON instead of
hard-coding UnitOperations in Python:

```bash
uv run python examples/07_heat_workflow.py
# On a Linux lab machine with Isaac Lab + Matterix installed:
python -m pip install -e packages/twin-core -e packages/twin-sim
python examples/08_run_real_matterix_heat.py --headless
```

Example JSON: `examples/workflows/matterix_heat_workflow.json`.

Mapping chain:

```text
workflow JSON → UnitOperation → WorkflowStep → matterix_sm Cfg → StateMachine
```

Diagnose whether the active Python environment can run the real Matterix path:

```bash
uv run python scripts/check_matterix_env.py
# Use --strict when missing requirements should fail the command.
```

See `docs/workflow-json-mapping.md` for file-level pointers.

## Layout

```
packages/
  twin-core/    # protocols, schemas, errors, mock backend, mini-orchestrator
  twin-sim/     # Matterix-backed sim ExecutorBackend (gated runtime)
  twin-real/    # state-machine real-stub ExecutorBackend
examples/       # numbered, runnable demo scripts (00 → 05)
tests/
  unit/         # per-package unit tests
  contract/     # tests every backend implementation must pass
docs/
  project-charter.md
  findings.md   # living log of verified / falsified assumptions
  decisions/    # ADRs
```

## Status

- Day 0: scaffolding ✅
- Day 1+: see `plan.md`

## Note on Matterix install

`matterix_sm` and Isaac Sim are NOT installed by `uv sync`. The configs-only
path (schema/frame validation) and all backends except `twin_sim.runtime`
work without them. To enable the full Matterix sim path, install per the
Matterix README — gated import means the rest of the codebase stays usable.
Run `uv run python scripts/check_matterix_env.py` first when debugging a lab
machine setup.
