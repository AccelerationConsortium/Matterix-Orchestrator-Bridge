# ADR 0007 — Arbitrator modes

Date: 2026-04-30
Status: Accepted

## Context

Demo 3 requires showing a runtime mode switch between sim, real, and
"sim-first-then-real". The mode set could be larger (shadow mode,
canary, replay-on-divergence), but each additional mode is a code path
that has to be tested and demoed.

## Decision

Three modes only:

  * `sim_only` — run on sim, never touch real. Useful for plan
    validation in CI without hardware booked.
  * `real_only` — run on real, never consult sim. Useful when sim is
    known to diverge (e.g., a sim-only asset is missing) but the plan
    is already trusted.
  * `sim_first_then_real` — sim dry-run as a hard gate. On gate fail,
    real is never touched and the structured failure is propagated.

The arbitrator always runs `preflight()` first regardless of mode —
preflight is cheap (in-memory) and catches schema/frame/state errors
that would be wasteful to send to either backend.

`shadow` mode (parallel sim + real with divergence detection) was
explicitly listed as a stretch goal in the project plan and is left
out per charter §4.

## Alternatives

- **Boolean `gate_with_sim` flag**: rejected. Loses the ability to do
  sim-only or real-only without code changes; demo would have to wire
  flags through every layer.
- **Strategy-pattern with pluggable arbitrator implementations**:
  rejected. Three modes don't justify the indirection. If a fourth
  mode is needed (shadow), a `Mode.SHADOW` variant is one branch in
  `Arbiter.run` plus a divergence detector.
- **Make `dry_run_fn` optional even in `sim_first_then_real`**:
  rejected. Silently degrading to "no gate" would defeat the mode's
  purpose; better to raise `ValueError` at run time so the
  misconfiguration is loud.
