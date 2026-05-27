"""Workflow JSON parser — orchestrator format → annotated bridge steps.

Reads the SDL orchestrator's workflow JSON (e.g. zinc_deposition_workflow.json)
and produces a ParsedWorkflow with per-step classification and timing estimates.

Step categories
---------------
sim           Robot arm actions routed to Matterix for physics simulation.
              estimated_duration_s is None — timing comes from sim step_count.
timed         Actions whose duration is fully specified in the JSON params
              (wait, squidstat.run_experiment). Duration extracted statically.
pass-through  Actions with no Matterix asset and no deterministic timing
              (plc, ssh, sample, squidstat plot helpers). Logged but not sent
              to the DT. Duration is None.

Timing coverage
---------------
timed_duration_s  Sum of all steps with known duration — lower bound for
                  total experiment wall-clock time. Robot and plc times are
                  excluded; EIS sweep duration is excluded (frequency-dependent).
timing_coverage   Fraction of steps whose duration is known (0.0–1.0).

Usage
-----
    from twin_core.workflow_parser import parse_workflow_json

    workflow = parse_workflow_json("zinc_deposition_workflow.json")
    print(f"Known duration: {workflow.timed_duration_s / 60:.1f} min")
    for step in workflow.steps:
        print(step.action, step.category, step.estimated_duration_s)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

StepCategory = Literal["sim", "timed", "pass-through"]

# Robot arm actions that Matterix can simulate (physics timing from sim)
_SIM_ACTIONS: frozenset[str] = frozenset(
    {
        "robot.move_to_well",
        "robot.pick_up_tip",
        "robot.drop_tip",
        "robot.home",
    }
)

# Setup-only actions: no runtime DT equivalent, no timing — skip silently
_SETUP_ACTIONS: frozenset[str] = frozenset(
    {
        "robot.load_labware",
        "robot.load_custom_labware",
        "robot.load_pipettes",
        "robot.set_lights",
        "ssh.start_stream",
    }
)


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ParsedStep:
    """One action from the workflow JSON, classified and timing-annotated."""

    step_id: str
    action: str
    device: str  # prefix before the first dot (e.g. "robot", "squidstat", "wait")
    params: dict[str, Any]
    description: str
    category: StepCategory
    estimated_duration_s: float | None
    timing_note: str | None = None   # explains why duration is partial or absent
    thread_name: str | None = None   # set when the step comes from a parallel thread
    is_parallel: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "device": self.device,
            "category": self.category,
            "estimated_duration_s": self.estimated_duration_s,
            "timing_note": self.timing_note,
            "thread_name": self.thread_name,
            "is_parallel": self.is_parallel,
            "description": self.description,
        }


@dataclass
class ParsedWorkflow:
    """Flattened, annotated representation of an orchestrator workflow JSON."""

    name: str
    version: str
    steps: list[ParsedStep]

    # Timing summary
    timed_duration_s: float        # sum of steps with known duration (lower bound)
    timing_coverage: float         # fraction of steps with known duration (0–1)
    has_parallel_phases: bool

    # Step counts by category
    sim_step_count: int
    timed_only_count: int          # timed but no sim (wait, squidstat)
    pass_through_count: int

    # Actions whose timing is missing (for reporting to scheduler)
    unknown_timing_actions: list[str]

    def summary(self) -> str:
        lines = [
            f"Workflow: {self.name} v{self.version}",
            f"Steps: {len(self.steps)} total  "
            f"(sim={self.sim_step_count}, timed={self.timed_only_count}, "
            f"pass-through={self.pass_through_count})",
            f"Known duration: {self.timed_duration_s / 60:.1f} min  "
            f"(coverage {self.timing_coverage:.0%})",
        ]
        if self.unknown_timing_actions:
            lines.append(
                "No timing for: "
                + ", ".join(sorted(set(self.unknown_timing_actions)))
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "timed_duration_s": self.timed_duration_s,
            "timing_coverage": round(self.timing_coverage, 4),
            "has_parallel_phases": self.has_parallel_phases,
            "sim_step_count": self.sim_step_count,
            "timed_only_count": self.timed_only_count,
            "pass_through_count": self.pass_through_count,
            "unknown_timing_actions": sorted(set(self.unknown_timing_actions)),
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# Internal helpers — classification and timing
# ---------------------------------------------------------------------------


def _device(action: str) -> str:
    """Extract device prefix from action string (e.g. 'robot.move_to_well' → 'robot')."""
    return action.split(".")[0]


def _classify(action: str) -> StepCategory:
    if action in _SIM_ACTIONS:
        return "sim"
    if action in _SETUP_ACTIONS:
        return "pass-through"
    if action == "wait":
        return "timed"
    if action == "squidstat.run_experiment":
        return "timed"
    return "pass-through"


def _squidstat_element_duration(elem: dict[str, Any]) -> float | None:
    """Recursively compute duration of one squidstat experiment element.

    Returns None for EIS (duration depends on frequency sweep at runtime).
    LOOP is expanded: total = repeats × per-cycle sum (EIS inside LOOP → None).
    """
    etype = elem.get("type", "")
    if etype == "EIS":
        return None
    if etype == "LOOP":
        repeats = int(elem.get("repeats", 1))
        per_cycle = 0.0
        for child in elem.get("elements", []):
            d = _squidstat_element_duration(child)
            if d is None:
                return None  # unknown inside loop → whole loop unknown
            per_cycle += d
        return repeats * per_cycle
    return elem.get("duration_s")


def _squidstat_run_duration(
    params: dict[str, Any],
) -> tuple[float, str | None]:
    """Sum known element durations for squidstat.run_experiment.

    Returns (total_s, timing_note).
    timing_note is set when some elements (EIS) contribute no duration.
    """
    total = 0.0
    skipped: list[str] = []
    for elem in params.get("elements", []):
        d = _squidstat_element_duration(elem)
        if d is None:
            skipped.append(elem.get("type", "?"))
        else:
            total += d
    note = (
        f"EIS excluded ({len(skipped)} sweep(s) — duration frequency-dependent)"
        if skipped
        else None
    )
    return total, note


def _estimate_duration(
    action: str,
    params: dict[str, Any],
) -> tuple[float | None, str | None]:
    """Return (estimated_duration_s, timing_note) for a single step."""
    if action == "wait":
        return float(params.get("duration_seconds", 0.0)), None
    if action == "squidstat.run_experiment":
        return _squidstat_run_duration(params)
    return None, None


# ---------------------------------------------------------------------------
# Step and phase parsing
# ---------------------------------------------------------------------------


def _parse_step(
    raw: dict[str, Any],
    *,
    thread_name: str | None = None,
    is_parallel: bool = False,
) -> ParsedStep:
    action = raw.get("action", "")
    params = raw.get("params", {})
    category = _classify(action)
    duration, note = _estimate_duration(action, params)

    return ParsedStep(
        step_id=raw.get("step_id", ""),
        action=action,
        device=_device(action),
        params=params,
        description=raw.get("description", ""),
        category=category,
        estimated_duration_s=duration,
        timing_note=note,
        thread_name=thread_name,
        is_parallel=is_parallel,
    )


def _flatten_phase(phase: dict[str, Any]) -> list[ParsedStep]:
    """Flatten one phase (sequential or parallel_threads) into a step list."""
    steps: list[ParsedStep] = []
    if "steps" in phase:
        for raw in phase["steps"]:
            steps.append(_parse_step(raw))
    for thread in phase.get("parallel_threads", []):
        name = thread.get("thread_name")
        for raw in thread.get("steps", []):
            steps.append(_parse_step(raw, thread_name=name, is_parallel=True))
    return steps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_workflow_json(source: str | Path | dict[str, Any]) -> ParsedWorkflow:
    """Parse an orchestrator workflow JSON into a ParsedWorkflow.

    Args:
        source: file path (str or Path) or already-loaded dict.

    Returns:
        ParsedWorkflow with per-step classification and timing annotation.
    """
    if isinstance(source, dict):
        data = source
    else:
        data = json.loads(Path(source).read_text())

    steps: list[ParsedStep] = []
    has_parallel = False

    for phase in data.get("phases", []):
        if "parallel_threads" in phase:
            has_parallel = True
        steps.extend(_flatten_phase(phase))

    # Timing summary
    timed_s = sum(s.estimated_duration_s for s in steps if s.estimated_duration_s is not None)
    timed_count = sum(1 for s in steps if s.estimated_duration_s is not None)
    coverage = timed_count / len(steps) if steps else 0.0

    sim_count = sum(1 for s in steps if s.category == "sim")
    timed_only = sum(1 for s in steps if s.category == "timed")
    passthrough = sum(1 for s in steps if s.category == "pass-through")

    unknown_actions = [s.action for s in steps if s.estimated_duration_s is None]

    return ParsedWorkflow(
        name=data.get("workflow_name", ""),
        version=str(data.get("version", "1.0")),
        steps=steps,
        timed_duration_s=timed_s,
        timing_coverage=coverage,
        has_parallel_phases=has_parallel,
        sim_step_count=sim_count,
        timed_only_count=timed_only,
        pass_through_count=passthrough,
        unknown_timing_actions=unknown_actions,
    )
