"""Unit tests for RealStubBackend — state machine + failure injection."""

from __future__ import annotations

import time

import pytest

from twin_core import Action, Pose, StateMachineViolation
from twin_real import CommunicationError, RealStubBackend


def _backend() -> RealStubBackend:
    return RealStubBackend(latency_seconds=(0.0, 0.0))


def test_double_close_raises_state_machine_violation() -> None:
    backend = _backend()
    backend.reset()
    backend.step(Action(gripper_command="close"))
    with pytest.raises(StateMachineViolation):
        backend.step(Action(gripper_command="close"))


def test_double_open_raises_state_machine_violation() -> None:
    backend = _backend()
    backend.reset()
    # Already open after reset.
    with pytest.raises(StateMachineViolation):
        backend.step(Action(gripper_command="open"))


def test_legitimate_open_close_sequence() -> None:
    backend = _backend()
    backend.reset()
    obs = backend.step(Action(gripper_command="close"))
    assert obs.gripper_closed
    obs = backend.step(Action(gripper_command="open"))
    assert not obs.gripper_closed


def test_target_pose_updates_ee_pose() -> None:
    backend = _backend()
    backend.reset()
    target = Pose(position=(0.5, 0.0, 0.3))
    obs = backend.step(Action(target_pose=target))
    assert obs.ee_pose == target


def test_failure_injection_always(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_REAL_INJECT_FAILURE", "always")
    backend = _backend()
    backend.reset()
    with pytest.raises(CommunicationError):
        backend.step(Action(target_pose=Pose(position=(0.1, 0.0, 0.5))))


def test_failure_injection_specific_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_REAL_INJECT_FAILURE", "step:2")
    backend = _backend()
    backend.reset()
    backend.step(Action(target_pose=Pose(position=(0.1, 0.0, 0.5))))
    with pytest.raises(CommunicationError):
        backend.step(Action(target_pose=Pose(position=(0.2, 0.0, 0.5))))


def test_failure_injection_gripper_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_REAL_INJECT_FAILURE", "gripper_close")
    backend = _backend()
    backend.reset()
    # Move action does NOT trigger.
    backend.step(Action(target_pose=Pose(position=(0.1, 0.0, 0.5))))
    with pytest.raises(CommunicationError):
        backend.step(Action(gripper_command="close"))


def test_latency_simulation_is_off_by_default_in_tests() -> None:
    """Sanity check that the test fixture has zero latency."""
    backend = _backend()
    start = time.perf_counter()
    backend.reset()
    backend.step(Action(gripper_command="close"))
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05  # Generous bound; should be <1ms in practice.
