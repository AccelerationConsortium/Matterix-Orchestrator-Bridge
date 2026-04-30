# ADR 0001 — Protocol-first architecture

Date: 2026-04-30
Status: Accepted

## Context

The PoC has two ends — a sim backend (Matterix) and a real-stub backend.
Either could be built first, and the obvious traps are: (a) building sim
first lets sim shape the abstraction, so the real-stub ends up modelling
sim's quirks rather than real hardware's; (b) building real-stub first
gives a clean abstraction but no validation that Matterix can actually
implement it; the first sim integration discovers the abstraction is wrong.

A third option: write the protocol first, before either implementation
exists. Both ends are then implementations against the same contract,
calibrated to a v1 schema after the Day 1 spike inspects real Matterix
shapes.

## Decision

Protocol-first. `ExecutorBackend`, `FrameService`, `Observation`, `Action`,
and the `ValidationError` taxonomy are written in `twin-core` in Day 0,
before sim or real-stub exists. A `MockBackend` in `twin-core` validates
the contract end-to-end without depending on Matterix or the stub.

After Day 1's spike against real Matterix, the schemas are calibrated
(`refactor(schemas): calibrate v1 against real Matterix shapes`) — the
contract tests must still pass after calibration. Both sim and real-stub
implement the same protocol and both pass the same contract test suite.

## Alternatives

- **Sim-first**: rejected — risk that the contract leaks Matterix
  abstractions, making future SiLA / real hardware backends a rewrite.
- **Real-stub-first**: rejected — no early signal that Matterix can satisfy
  the contract. By the time sim integration lands the abstraction may need
  rework.
- **No protocol layer (direct dispatch)**: rejected — kills Demo 3
  (arbitrator switching between backends transparently) and makes the
  safety layer's pre-flight gate impossible to test.
