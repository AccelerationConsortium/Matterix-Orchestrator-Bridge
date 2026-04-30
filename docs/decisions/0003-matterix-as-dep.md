# ADR 0003 — Matterix as dependency, not fork

Date: 2026-04-30
Status: Accepted

## Context

The bridge could either fork Matterix and modify it to expose an
ExecutorBackend directly, or treat Matterix as an upstream dependency and
write a thin adapter in `twin-sim`.

## Decision

Adapter-only. `twin_sim.backend` wraps a Matterix env via a gated
`matterix_sm` import. Zero patches to Matterix source. The cost of an
extra wrapper layer is paid for by: (a) the PoC stays usable when
Matterix changes upstream — adapter rev only; (b) other Matterix users
can adopt the bridge without forking; (c) the contract-first architecture
(ADR 0001) gets a clean test: the adapter is the place where Matterix-
shaped data becomes contract-shaped data.

## Alternatives

- **Fork Matterix**: rejected — phase-2 maintenance cost, and signals the
  wrong dependency direction (Matterix is general-purpose, the bridge is
  specific to one orchestration use case).
- **Vendor Matterix into the repo**: rejected — same maintenance cost
  without the licensing complications of a fork.
