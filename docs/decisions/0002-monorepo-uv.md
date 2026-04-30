# ADR 0002 — Monorepo + uv workspace

Date: 2026-04-30
Status: Accepted

## Context

Three packages share schemas (`twin-core`) and need to evolve in lock-step
across the PoC: `twin-sim`, `twin-real`, and the orchestrator/arbitrator
modules in `twin-core`. Splitting them into separate repos would require
publishing `twin-core` to a private index for every contract change.

## Decision

Single repo, `packages/*` workspace via `uv`. Each package has its own
`pyproject.toml` and is installed editable into the workspace venv. Root
`pyproject.toml` declares the three packages as `dependencies` so a single
`uv sync` and `uv run pytest` run the whole suite.

## Alternatives

- **Three separate repos**: rejected — overkill for a 10-day PoC, and the
  protocol-first approach (ADR 0001) explicitly co-evolves all three.
- **One package with sub-modules**: rejected — `twin-sim`'s gated Matterix
  runtime import would force the whole codebase to carry that conditional
  weight; separating packages keeps `twin-core` runtime-clean.
