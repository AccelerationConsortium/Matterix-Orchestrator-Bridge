# Workflow JSON to Matterix Mapping

This repo now has a concrete JSON entry point for the Matterix demo:

```text
examples/workflows/matterix_heat_workflow.json
```

The mapping chain is:

```text
workflow JSON
  -> twin_core.workflow_loader.load_operations_json()
  -> UnitOperation objects
  -> operation_to_workflow()
  -> WorkflowStep primitives
  -> twin_sim.real_runner._build_matterix_cfgs()
  -> matterix_sm StateMachine.set_action_sequence(cfgs)
```

The UO layer is intentionally flexible and case-by-case. The stable bridge
boundary to Matterix is `WorkflowStep -> matterix_sm Cfg`.

Current JSON operations:

| JSON operation | Bridge primitive(s) | Matterix cfg mapping |
|---|---|---|
| `pick_and_place` | `pick_object`, `place_at` | `PickObjectCfg`, `PlaceObjectCfg` |
| `heat` | `heat` | `TurnOnHeaterCfg(on)`, `WaitCfg`, `TurnOnHeaterCfg(off)` |

Run the fake-sim version:

```bash
uv run python examples/07_heat_workflow.py
```

Run the real Matterix version on a Linux machine with Isaac Lab and Matterix
installed:

```bash
python -m pip install -e packages/twin-core -e packages/twin-sim
python examples/08_run_real_matterix_heat.py --headless
```

Use a different workflow JSON:

```bash
python examples/08_run_real_matterix_heat.py \
  --workflow_json examples/workflows/matterix_heat_workflow.json \
  --headless
```
