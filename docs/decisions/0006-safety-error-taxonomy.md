# ADR 0006 — Safety error taxonomy (4 classes)

Date: 2026-04-30
Status: Accepted

## Context

The safety layer needs to fail in distinct, attributable ways. A single
`SafetyError` would let the demo say "something went wrong" but not
"this specific failure mode was caught". The pre-flight gate is the
project's primary value claim, so the taxonomy is part of the value
claim.

## Decision

Four leaf error classes under a `ValidationError` base:

  * `SchemaError` — the workflow itself violates a structural or
    policy constraint (e.g., `pick_object` with a target_frame outside
    `PICK_OBJECT_ALLOWED_FRAMES`). Caught by `schema_check` without
    touching any backend.
  * `FrameNotFound` — workflow references an `(asset_id, frame_name)`
    pair the FrameService cannot resolve. Caught by `frame_check`.
    Carries `asset_id` and `frame_name` attributes for structured
    logging.
  * `StateMachineViolation` — the workflow violates the abstract
    gripper state machine (e.g., place_at while empty, pick_object
    while already holding). Carries `current_state` and
    `attempted_action`.
  * `PhysicalInfeasibility` — sim dry-run determines the workflow is
    not physically executable (collision, unreachable). Carries
    `reason` and `step_index`.

Each demo workflow in `examples/04_safety_demo.py` triggers exactly one
class. The structured `CheckResult` (or `DryRunResult`) carries
`error_class`, `reason`, `step_index`, and `plan_segment` so logs are
parseable downstream.

## Alternatives

- **Single `SafetyError`**: rejected. Demo 2 requires distinguishable
  catches; one class makes "the gate caught three different problems"
  unprovable.
- **Codes-as-strings instead of classes**: rejected. Python error
  classes get isinstance dispatch for free; downstream alerting can
  match on class without parsing strings.
- **Five+ classes (split PhysicalInfeasibility into Collision /
  Unreachable / RateOfChange)**: rejected. Sim doesn't currently
  distinguish them in the PoC, and adding error classes the system
  cannot actually emit is dead inventory. Add when the second
  PhysicalInfeasibility cause appears.
