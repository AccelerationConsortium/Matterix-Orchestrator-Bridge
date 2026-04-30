# ADR 0005 — Real-stub vs. real hardware in PoC scope

Date: 2026-04-30
Status: Accepted

## Context

The PoC needs a "real" side to demonstrate Demo 1 (same plan, two
backends) and Demo 3 (sim-first gating prevents real from seeing a bad
plan). Two options: a real Franka behind the bridge, or a stateful
in-process stub.

## Decision

Stub. `RealStubBackend` implements `ExecutorBackend` with: gripper +
ee-pose state machine, simulated 0.5–2s per-action latency, env-var
failure injection (`TWIN_REAL_INJECT_FAILURE=always|step:N|gripper_*`),
and a strict gripper protocol (`StateMachineViolation` on double-open
/ double-close). Latency is parameterised so contract tests pass
zero-latency.

The stub passes the same contract test suite as `MockBackend` and
`SimBackend(FakeMatterixEnv())`, so the protocol is the only thing the
orchestrator and arbiter depend on — swapping in a real Franka in
phase 2 is "implement `ExecutorBackend` against the real driver".

## Alternatives

- **Real Franka in PoC**: rejected. Charter §4 non-goal. The risk
  budget for a 10-day PoC cannot accommodate hardware integration in
  parallel with protocol design. Phase 2.
- **No real side at all (sim-only PoC)**: rejected. Demo 3 requires
  showing the gate prevents real from seeing a bad plan. With no real
  side, "the gate works" is unfalsifiable.
- **Skip state-machine strictness on the stub**: rejected. The point
  of the stub is to surface protocol violations early — making it
  permissive would hide the same class of bugs that real hardware
  would expose with worse error messages.
