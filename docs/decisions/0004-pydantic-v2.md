# ADR 0004 — Pydantic v2 for schemas

Date: 2026-04-30
Status: Accepted

## Context

The contract layer needs frozen data classes with validation, JSON
serialization (for cross-process plan transmission later), and clean
error messages when a backend emits an off-shape Observation. Options:
plain `@dataclass(frozen=True)`, attrs, msgspec, Pydantic v2.

## Decision

Pydantic v2 throughout `twin_core.schemas`. `model_config =
ConfigDict(frozen=True)` matches the immutability requirement;
field-level validators give us a place to enforce e.g. unit-quaternion
constraints at calibration time without changing call sites; `extras`
dicts give us a calibration escape hatch without breaking the schema.

`UnitOperation` and `PickAndPlace` stay as plain frozen dataclasses
because they are user-facing API and never round-trip JSON.

## Alternatives

- **plain dataclasses**: rejected — no validation; cross-process JSON is
  manual; no extension story for v0→v1 schema calibration.
- **msgspec**: faster, smaller, but the ecosystem is thinner and the
  team's familiarity with Pydantic v2 is higher. Performance is not a
  bottleneck for this PoC.
- **attrs + cattrs**: more flexible but less batteries-included for the
  JSON-serialization path.
