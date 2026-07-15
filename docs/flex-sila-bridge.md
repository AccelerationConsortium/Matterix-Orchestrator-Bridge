# Flex SiLA bridge

The DT side now preserves the orchestrator's existing `robot.*` workflow
contract and adapts those steps locally to the Opentrons Flex SiLA 2
connector. It does not make the orchestrator emit connector-specific gRPC
names and it does not put Flex into the Franka-oriented per-step
`ExecutorBackend`.

`ParsedStep.category` continues to describe Matterix simulation/timing
coverage; Flex routing uses the step's `device` and exact `action`. A
`pass-through` category therefore never means that a `robot.*` hardware step
may be discarded.

## Boundary

```text
orchestrator JSON (`robot.*`)
  -> ParsedStep
  -> FlexWorkflowAdapter
  -> FlexCommand + absolute millimetre position
  -> FlexSiLATransport
  -> Opentrons Flex SiLA 2 connector
```

`FlexDeckResolver` is the DT asset seam. Today,
`StaticFlexConfig` loads calibrated anchors from JSON. When the real Flex DT
asset exists, implement `FlexDeckResolver.resolve()` and
`tip_length_mm()` from that asset; the workflow adapter and SiLA transport do
not change.

`FlexInstrumentResolver` similarly maps an external pipette alias such as
`p1000_single_gen2` to `LEFT` or `RIGHT`. The mapping is explicit because
guessing a mount from a pipette name is unsafe.

An unknown `robot.*` action or a robot action whose parsed `device` conflicts
with `robot` fails during compilation. Only steps owned by a different device
are returned to the mixed-instrument scheduler.

## Supported workflow actions

- Motion: `robot.home`, `home_mount`, `move_to`, `move_to_well`,
  `move_relative`, `get_position`.
- Tip lifecycle: `robot.pick_up_tip`, `drop_tip`, `get_tip_presence`.
- Liquid primitives: `robot.prepare_for_aspirate`, `aspirate`, `dispense`,
  `blow_out`.
- Control and status: `robot.pause`, `resume`, `emergency_stop`, `set_lights`,
  `get_machine_status`, `get_attached_pipettes`.
- Gripper: `robot.grip`, `ungrip`, `home_gripper_jaw`.

Motion, tip, liquid, and gripper commands read `MachineStatus` after the SiLA
result. An error-state result raises `FlexMachineError`; a successful gRPC
return alone is not treated as proof that the hardware stayed healthy.
Responses are normalized to DT-side result models and missing, non-finite, or
wrongly typed safety fields fail closed instead of receiving defaults.

## Compile without hardware

The example is compile-only unless `--execute` is explicitly supplied:

```bash
uv run python examples/11_run_flex_sila.py
```

Edit `examples/flex_dt_config.json` to match the real deck before executing.
The coordinates in that file are illustrative, not a hardware calibration.
Hardware execution is blocked until the reviewed config explicitly sets
`"calibration_confirmed": true`.

## Connect to the simulator or robot

The runtime transport needs gRPC, SiLA envelopes, and the connector package as
the protobuf codec provider:

```bash
uv sync --extra flex --package twin-real
uv pip install -e /path/to/opentrons-flex
uv run python examples/11_run_flex_sila.py \
  --execute --host <connector-host> --port 50051 \
  --tls-ca /path/to/connector-ca.pem
```

For a connector that is intentionally plaintext on a physically trusted lab
network, replace `--tls-ca ...` with the explicit `--insecure` acknowledgement.
Plaintext is never selected implicitly by the hardware example.

The client compiles protobuf messages from the installed connector package
without starting a second gRPC server. This avoids maintaining hand-written
protobuf messages that could drift from generated SiLA FDL. A future
standalone client-codec artifact from the connector can be injected through
`FlexSiLATransport.connect(codec=...)` to remove the remaining simulator-package
dependency.

## Parallel workflows

`FlexWorkflowRunner.run()` accepts Flex-only sequential workflows. It rejects
both flattened parallel Flex steps and any non-Flex steps before touching
hardware. The mixed-device orchestrator must retain thread/device ownership
and call `execute_step()` when the Flex step is scheduled. This prevents the
bridge from silently skipping a PLC/wait step or turning a parallel phase into
a different sequential experiment.

After a timeout, connection loss, or post-command status failure, the current
command may already have affected the robot. The runner stops without issuing
the next command and preserves prior verified records. An operator or owning
scheduler must reconcile actual machine state before any retry; the bridge
never retries hardware actions automatically.

## Connector compatibility check

Run the local AST-based check whenever the connector changes:

```bash
uv run python scripts/check_flex_connector_contract.py \
  --connector-repo /path/to/opentrons-flex
```

It verifies the four feature classes, DT-used command decorators
(Observable/Unobservable/Property), package FQNs, and service names.
