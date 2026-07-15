"""Tests that the local Flex connector drift checker detects FDL changes."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

from twin_real import FlexExecutionMode, FlexFeature


ROOT = Path(__file__).resolve().parents[2]
CHECKER_SCRIPT = ROOT / "scripts" / "check_flex_connector_contract.py"


def _load_checker_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "flex_contract_checker", CHECKER_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker_module()


def _motion_feature_source(
    *,
    decorator: str = "ObservableCommand",
    parameters: str = "",
) -> str:
    return f"""\
class MotionControlFeature:
    def __init__(self):
        super().__init__(
            originator="ca.accelerationconsortium",
            category="robots",
            version="1.1",
        )

    @sila.{decorator}()
    async def home(self, *, status, intermediate{parameters}):
        pass
"""


def _write_motion_feature(connector_repo: Path, source: str) -> None:
    feature_dir = connector_repo / "src/unitelabs/opentrons_flex/features"
    feature_dir.mkdir(parents=True)
    (feature_dir / "motion_control.py").write_text(source)


@pytest.fixture
def motion_only_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        checker,
        "EXPECTED_FEATURES",
        (
            checker.ExpectedFeature(
                feature=FlexFeature.MOTION_CONTROL,
                source_file="motion_control.py",
                class_name="MotionControlFeature",
                methods={"home": checker.ExpectedMethod(FlexExecutionMode.OBSERVABLE)},
            ),
        ),
    )


def test_contract_checker_accepts_matching_feature_source(
    tmp_path: Path,
    motion_only_contract: None,
) -> None:
    _write_motion_feature(tmp_path, _motion_feature_source())

    assert checker.check_contract(tmp_path) == []


@pytest.mark.parametrize(
    ("source", "expected_error"),
    [
        (
            _motion_feature_source(decorator="UnobservableCommand"),
            "expected observable, connector declares unobservable",
        ),
        (
            _motion_feature_source(parameters=", mount"),
            "expected parameters (), connector declares ('mount',)",
        ),
    ],
)
def test_contract_checker_reports_execution_or_parameter_drift(
    tmp_path: Path,
    motion_only_contract: None,
    source: str,
    expected_error: str,
) -> None:
    _write_motion_feature(tmp_path, source)

    errors = checker.check_contract(tmp_path)

    assert any(expected_error in error for error in errors)
