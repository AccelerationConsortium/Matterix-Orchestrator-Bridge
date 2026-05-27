"""Safety signals emitted by the Matterix DT for consumption by an orchestrator.

SafetySignal is the typed event the bridge produces after analysing a batch
run. The orchestrator consumes these to decide whether to proceed, add
monitoring, or abort the real experiment.

Level semantics:
  info      → noteworthy but no action required; log and continue
  warning   → flag for human review or tighten monitoring before proceeding
  critical  → orchestrator should pause or abort the real experiment
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class SafetySignal:
    """A structured safety event produced by the DT analysis layer.

    source: what generated the signal.
      "failure_rate"  — fraction of parallel envs failed overall or at a step
      "temperature"   — semantic temperature exceeded a bound (post-calibration)
      "contact"       — unexpected contact / no-contact (post-calibration)
      (others added as semantic_events schema is calibrated)
    """

    level: Literal["info", "warning", "critical"]
    step_index: int   # physics step where condition was observed; -1 = overall
    source: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
