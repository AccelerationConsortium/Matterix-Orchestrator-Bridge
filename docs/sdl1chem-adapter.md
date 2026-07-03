# SDL1Chem Adapter

SDL1Chem owns its fixed Uoroboros workflow and UO format. The bridge should not
ask SDL1Chem to change that format. Instead, this repo adds an adapter layer:

```text
SDL1Chem workflow JSON
  -> blocks[*].uo_path
  -> mapping table in twin_core.sdl1chem_adapter
  -> UnitOperation
  -> WorkflowStep
  -> backend-specific lowering, including Matterix Cfgs
```

The first adapter maps only SDL1Chem robot transfer UOs that resemble Matterix
pick/place semantics:

| SDL1Chem UO path | Bridge operation | Bridge primitive(s) |
|---|---|---|
| `echem-uos:flush_tool_transfer` | `PickAndPlace` | `pick_object`, `place_at` |
| `echem-uos:insert_electrode` | `PickAndPlace` | `pick_object`, `place_at` |
| `echem-uos:remove_electrode` | `PickAndPlace` | `pick_object`, `place_at` |

Other SDL1Chem UOs remain visible as unsupported blocks in the adapter report.
That is intentional: the source workflow can be broader than what Matterix can
simulate today.

Dry-inspect the bundled excerpt:

```bash
uv run python examples/inspect_sdl1chem_adapter.py
```

Inspect a real SDL1Chem workflow checkout:

```bash
uv run python examples/inspect_sdl1chem_adapter.py \
  /Users/sissifeng/sdl1chem/scripts/robot_loop_workflow.json
```
