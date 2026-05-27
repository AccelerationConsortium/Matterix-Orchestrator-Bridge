"""Unit tests for twin_core.workflow_parser.

Uses synthetic workflow dicts — no file I/O dependency, no Matterix.
Tests cover step classification, timing extraction, parallel phase
handling, and the to_dict() output contract.
"""

from __future__ import annotations

import pytest

from twin_core.workflow_parser import ParsedWorkflow, parse_workflow_json


# ---------------------------------------------------------------------------
# Minimal workflow fixtures
# ---------------------------------------------------------------------------

SINGLE_PHASE_SEQUENTIAL = {
    "workflow_name": "Test Sequential",
    "version": "1.0",
    "phases": [
        {
            "phase_name": "p1",
            "steps": [
                {
                    "step_id": "s1",
                    "action": "robot.move_to_well",
                    "params": {"labware": "rack", "well": "A1"},
                    "description": "move",
                },
                {
                    "step_id": "s2",
                    "action": "wait",
                    "params": {"duration_seconds": 30},
                    "description": "wait 30s",
                },
                {
                    "step_id": "s3",
                    "action": "plc.dispense_ml",
                    "params": {"pump": 1, "volume_ml": 10},
                    "description": "dispense",
                },
            ],
        }
    ],
}

PARALLEL_PHASE = {
    "workflow_name": "Test Parallel",
    "version": "1.0",
    "phases": [
        {
            "phase_name": "p1",
            "parallel_threads": [
                {
                    "thread_name": "thread_a",
                    "steps": [
                        {
                            "step_id": "a1",
                            "action": "wait",
                            "params": {"duration_seconds": 65},
                            "description": "wait A",
                        },
                        {
                            "step_id": "a2",
                            "action": "plc.dispense_ml",
                            "params": {},
                            "description": "dispense",
                        },
                    ],
                },
                {
                    "thread_name": "thread_b",
                    "steps": [
                        {
                            "step_id": "b1",
                            "action": "robot.pick_up_tip",
                            "params": {},
                            "description": "pick electrode",
                        },
                    ],
                },
            ],
        }
    ],
}

SQUIDSTAT_PHASE = {
    "workflow_name": "Test Squidstat",
    "version": "1.0",
    "phases": [
        {
            "phase_name": "p1",
            "steps": [
                {
                    "step_id": "e1",
                    "action": "squidstat.run_experiment",
                    "params": {
                        "elements": [
                            {"type": "OCV", "duration_s": 30},
                            {
                                "type": "LOOP",
                                "repeats": 5,
                                "elements": [
                                    {"type": "CP", "duration_s": 90},
                                    {"type": "OCV", "duration_s": 30},
                                ],
                            },
                            {"type": "EIS", "freq_start_hz": 10000, "freq_stop_hz": 0.1},
                            {"type": "OCV", "duration_s": 30},
                        ]
                    },
                    "description": "run squidstat",
                },
                {
                    "step_id": "e2",
                    "action": "squidstat.reset_plot",
                    "params": {},
                    "description": "reset plot",
                },
            ],
        }
    ],
}

SETUP_PHASE = {
    "workflow_name": "Test Setup",
    "version": "1.0",
    "phases": [
        {
            "phase_name": "setup",
            "steps": [
                {
                    "step_id": "u1",
                    "action": "robot.load_pipettes",
                    "params": {},
                    "description": "load pipettes",
                },
                {
                    "step_id": "u2",
                    "action": "robot.load_labware",
                    "params": {},
                    "description": "load labware",
                },
                {
                    "step_id": "u3",
                    "action": "ssh.start_stream",
                    "params": {},
                    "description": "stream",
                },
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# Step classification
# ---------------------------------------------------------------------------


class TestStepClassification:
    def test_move_to_well_is_sim(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        step = next(s for s in wf.steps if s.action == "robot.move_to_well")
        assert step.category == "sim"

    def test_pick_up_tip_is_sim(self) -> None:
        wf = parse_workflow_json(PARALLEL_PHASE)
        step = next(s for s in wf.steps if s.action == "robot.pick_up_tip")
        assert step.category == "sim"

    def test_wait_is_timed(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        step = next(s for s in wf.steps if s.action == "wait")
        assert step.category == "timed"

    def test_plc_is_pass_through(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        step = next(s for s in wf.steps if s.action == "plc.dispense_ml")
        assert step.category == "pass-through"

    def test_squidstat_run_is_timed(self) -> None:
        wf = parse_workflow_json(SQUIDSTAT_PHASE)
        step = next(s for s in wf.steps if s.action == "squidstat.run_experiment")
        assert step.category == "timed"

    def test_squidstat_reset_is_pass_through(self) -> None:
        wf = parse_workflow_json(SQUIDSTAT_PHASE)
        step = next(s for s in wf.steps if s.action == "squidstat.reset_plot")
        assert step.category == "pass-through"

    def test_setup_actions_are_pass_through(self) -> None:
        wf = parse_workflow_json(SETUP_PHASE)
        for step in wf.steps:
            assert step.category == "pass-through"


# ---------------------------------------------------------------------------
# Timing extraction — wait
# ---------------------------------------------------------------------------


class TestWaitTiming:
    def test_wait_duration_extracted(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        step = next(s for s in wf.steps if s.action == "wait")
        assert step.estimated_duration_s == pytest.approx(30.0)

    def test_wait_no_timing_note(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        step = next(s for s in wf.steps if s.action == "wait")
        assert step.timing_note is None


# ---------------------------------------------------------------------------
# Timing extraction — squidstat
# ---------------------------------------------------------------------------


class TestSquidstatTiming:
    def test_ocv_duration_counted(self) -> None:
        # 2 × OCV(30) + LOOP 5 × (CP90 + OCV30) = 60 + 5*120 = 660
        wf = parse_workflow_json(SQUIDSTAT_PHASE)
        step = next(s for s in wf.steps if s.action == "squidstat.run_experiment")
        assert step.estimated_duration_s == pytest.approx(660.0)

    def test_eis_excluded_and_noted(self) -> None:
        wf = parse_workflow_json(SQUIDSTAT_PHASE)
        step = next(s for s in wf.steps if s.action == "squidstat.run_experiment")
        assert step.timing_note is not None
        assert "EIS" in step.timing_note

    def test_loop_expansion(self) -> None:
        wf = parse_workflow_json({
            "workflow_name": "loop test",
            "version": "1.0",
            "phases": [{"phase_name": "p", "steps": [{
                "step_id": "x",
                "action": "squidstat.run_experiment",
                "params": {"elements": [
                    {"type": "LOOP", "repeats": 20,
                     "elements": [{"type": "CP", "duration_s": 90},
                                  {"type": "OCV", "duration_s": 30}]}
                ]},
                "description": "",
            }]}],
        })
        step = wf.steps[0]
        assert step.estimated_duration_s == pytest.approx(20 * 120.0)
        assert step.timing_note is None  # no EIS

    def test_eis_inside_loop_propagates_none(self) -> None:
        wf = parse_workflow_json({
            "workflow_name": "eis in loop",
            "version": "1.0",
            "phases": [{"phase_name": "p", "steps": [{
                "step_id": "x",
                "action": "squidstat.run_experiment",
                "params": {"elements": [
                    {"type": "LOOP", "repeats": 3,
                     "elements": [{"type": "EIS"}]}
                ]},
                "description": "",
            }]}],
        })
        # LOOP containing EIS → whole loop unknown → total = 0 (from known elements only)
        step = wf.steps[0]
        assert step.timing_note is not None  # EIS noted

    def test_pass_through_step_has_no_duration(self) -> None:
        wf = parse_workflow_json(SQUIDSTAT_PHASE)
        step = next(s for s in wf.steps if s.action == "squidstat.reset_plot")
        assert step.estimated_duration_s is None


# ---------------------------------------------------------------------------
# Parallel phase handling
# ---------------------------------------------------------------------------


class TestParallelPhases:
    def test_has_parallel_phases_detected(self) -> None:
        wf = parse_workflow_json(PARALLEL_PHASE)
        assert wf.has_parallel_phases is True

    def test_sequential_has_no_parallel(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert wf.has_parallel_phases is False

    def test_thread_name_set_on_parallel_steps(self) -> None:
        wf = parse_workflow_json(PARALLEL_PHASE)
        parallel_steps = [s for s in wf.steps if s.is_parallel]
        assert all(s.thread_name is not None for s in parallel_steps)

    def test_thread_names_correct(self) -> None:
        wf = parse_workflow_json(PARALLEL_PHASE)
        names = {s.thread_name for s in wf.steps if s.is_parallel}
        assert names == {"thread_a", "thread_b"}

    def test_sequential_steps_have_no_thread(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        for step in wf.steps:
            assert step.thread_name is None
            assert step.is_parallel is False


# ---------------------------------------------------------------------------
# ParsedWorkflow summary stats
# ---------------------------------------------------------------------------


class TestWorkflowStats:
    def test_sim_count(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert wf.sim_step_count == 1  # move_to_well

    def test_timed_only_count(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert wf.timed_only_count == 1  # wait

    def test_pass_through_count(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert wf.pass_through_count == 1  # plc

    def test_timed_duration_sums_known(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert wf.timed_duration_s == pytest.approx(30.0)

    def test_timing_coverage(self) -> None:
        # 3 steps, 1 timed → 1/3
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert wf.timing_coverage == pytest.approx(1 / 3)

    def test_unknown_timing_actions_listed(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert "robot.move_to_well" in wf.unknown_timing_actions
        assert "plc.dispense_ml" in wf.unknown_timing_actions

    def test_workflow_name_and_version(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        assert wf.name == "Test Sequential"
        assert wf.version == "1.0"


# ---------------------------------------------------------------------------
# to_dict contract
# ---------------------------------------------------------------------------


class TestToDict:
    def test_to_dict_keys(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        d = wf.to_dict()
        for key in ("name", "version", "timed_duration_s", "timing_coverage",
                    "has_parallel_phases", "sim_step_count", "timed_only_count",
                    "pass_through_count", "unknown_timing_actions", "steps"):
            assert key in d

    def test_step_to_dict_keys(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        s = wf.steps[0].to_dict()
        for key in ("step_id", "action", "device", "category",
                    "estimated_duration_s", "timing_note",
                    "thread_name", "is_parallel", "description"):
            assert key in s

    def test_device_field_extracted(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        step = next(s for s in wf.steps if s.action == "plc.dispense_ml")
        assert step.device == "plc"

    def test_wait_device_is_wait(self) -> None:
        wf = parse_workflow_json(SINGLE_PHASE_SEQUENTIAL)
        step = next(s for s in wf.steps if s.action == "wait")
        assert step.device == "wait"


# ---------------------------------------------------------------------------
# Integration: zinc_deposition_workflow.json (if available)
# ---------------------------------------------------------------------------


def test_zinc_deposition_smoke(tmp_path) -> None:
    """Smoke-test against the real zinc_deposition JSON if present."""
    import json
    from pathlib import Path

    src = Path("/Users/sissifeng/refactored_battery/workflows/zinc_deposition_workflow.json")
    if not src.exists():
        pytest.skip("zinc_deposition_workflow.json not found")

    wf = parse_workflow_json(src)
    assert wf.name != ""
    assert len(wf.steps) == 72
    assert wf.sim_step_count > 0
    assert wf.timed_duration_s > 5000   # squidstat dominates
    assert wf.has_parallel_phases is True
    assert "squidstat.run_experiment" not in wf.unknown_timing_actions  # it has timing
    print("\n" + wf.summary())
