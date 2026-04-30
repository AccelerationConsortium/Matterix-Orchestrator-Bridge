"""Contract tests — every ExecutorBackend implementation must pass these.

Day 0: MockBackend. Day 2: + SimBackend (FakeMatterixEnv). Day 4-5: + real-stub.
"""

from __future__ import annotations

import pytest

from twin_core import Action, ExecutorBackend
from twin_core.mock_backend import MockBackend
from twin_real import RealStubBackend
from twin_sim import FakeMatterixEnv, SimBackend


@pytest.fixture(params=["mock", "sim_fake", "real_stub"])
def backend(request) -> ExecutorBackend:
    if request.param == "mock":
        return MockBackend()
    if request.param == "sim_fake":
        return SimBackend(FakeMatterixEnv())
    if request.param == "real_stub":
        # Tests must run fast — disable simulated latency.
        return RealStubBackend(latency_seconds=(0.0, 0.0))
    raise ValueError(request.param)


def test_reset_returns_observation(backend: ExecutorBackend) -> None:
    obs = backend.reset()
    assert obs.ee_pose is not None


def test_step_after_reset(backend: ExecutorBackend) -> None:
    backend.reset()
    obs = backend.step(Action(gripper_command="close"))
    assert obs.gripper_closed is True


def test_close_does_not_raise(backend: ExecutorBackend) -> None:
    backend.reset()
    backend.close()


def test_implements_protocol(backend: ExecutorBackend) -> None:
    assert isinstance(backend, ExecutorBackend)