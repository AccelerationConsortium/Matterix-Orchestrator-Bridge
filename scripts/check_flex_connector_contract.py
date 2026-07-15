"""Check that the DT Flex client still matches a local connector checkout."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from twin_real import FLEX_FEATURE_ENDPOINTS, FlexExecutionMode, FlexFeature


@dataclass(frozen=True)
class ExpectedMethod:
    mode: FlexExecutionMode
    parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedFeature:
    feature: FlexFeature
    source_file: str
    class_name: str
    methods: dict[str, ExpectedMethod]


OBSERVABLE = FlexExecutionMode.OBSERVABLE
UNOBSERVABLE = FlexExecutionMode.UNOBSERVABLE
PROPERTY = FlexExecutionMode.PROPERTY

EXPECTED_FEATURES = (
    ExpectedFeature(
        FlexFeature.MOTION_CONTROL,
        "motion_control.py",
        "MotionControlFeature",
        {
            "home": ExpectedMethod(OBSERVABLE),
            "home_mount": ExpectedMethod(OBSERVABLE, ("mount",)),
            "move_to": ExpectedMethod(OBSERVABLE, ("mount", "x", "y", "z", "speed")),
            "move_relative": ExpectedMethod(
                OBSERVABLE,
                ("mount", "delta_x", "delta_y", "delta_z", "speed"),
            ),
            "get_position": ExpectedMethod(OBSERVABLE, ("mount",)),
            "prepare_for_aspirate": ExpectedMethod(OBSERVABLE, ("mount",)),
            "aspirate": ExpectedMethod(OBSERVABLE, ("mount", "volume", "rate")),
            "dispense": ExpectedMethod(
                OBSERVABLE, ("mount", "volume", "rate", "push_out")
            ),
            "blow_out": ExpectedMethod(OBSERVABLE, ("mount",)),
            "emergency_stop": ExpectedMethod(OBSERVABLE),
            "pause": ExpectedMethod(OBSERVABLE),
            "resume": ExpectedMethod(OBSERVABLE),
            "set_lights": ExpectedMethod(OBSERVABLE, ("button", "rails")),
            "machine_status": ExpectedMethod(PROPERTY),
        },
    ),
    ExpectedFeature(
        FlexFeature.TIP_CONTROLLER,
        "tip_controller.py",
        "TipController",
        {
            "pick_up_tip": ExpectedMethod(
                OBSERVABLE,
                ("mount", "location", "tip_length", "prep_after"),
            ),
            "drop_tip": ExpectedMethod(OBSERVABLE, ("mount", "location", "home_after")),
            "get_tip_presence": ExpectedMethod(UNOBSERVABLE, ("mount",)),
        },
    ),
    ExpectedFeature(
        FlexFeature.GRIPPER,
        "gripper.py",
        "GripperFeature",
        {
            "grip": ExpectedMethod(OBSERVABLE, ("force",)),
            "ungrip": ExpectedMethod(OBSERVABLE),
            "home_jaw": ExpectedMethod(OBSERVABLE),
        },
    ),
    ExpectedFeature(
        FlexFeature.PIPETTE,
        "pipette.py",
        "PipetteFeature",
        {"get_attached_pipettes": ExpectedMethod(OBSERVABLE)},
    ),
)


DECORATOR_MODES = {
    "sila.ObservableCommand": OBSERVABLE,
    "sila.UnobservableCommand": UNOBSERVABLE,
    "sila.UnobservableProperty": PROPERTY,
}


def check_contract(connector_repo: Path) -> list[str]:
    """Return human-readable mismatches; an empty list means compatible."""
    feature_dir = connector_repo / "src/unitelabs/opentrons_flex/features"
    errors: list[str] = []
    for expected in EXPECTED_FEATURES:
        source = feature_dir / expected.source_file
        if not source.is_file():
            errors.append(f"missing connector feature file: {source}")
            continue
        tree = ast.parse(source.read_text(), filename=str(source))
        feature_class = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == expected.class_name
            ),
            None,
        )
        if feature_class is None:
            errors.append(f"{source}: missing class {expected.class_name}")
            continue

        actual_methods = _sila_methods(feature_class)
        for method, method_spec in expected.methods.items():
            actual = actual_methods.get(method)
            if actual is None:
                errors.append(f"{expected.class_name}.{method}: missing SiLA decorator")
                continue
            actual_mode, actual_parameters = actual
            if actual_mode is not method_spec.mode:
                errors.append(
                    f"{expected.class_name}.{method}: expected {method_spec.mode.value}, "
                    f"connector declares {actual_mode.value}"
                )
            if actual_parameters != method_spec.parameters:
                errors.append(
                    f"{expected.class_name}.{method}: expected parameters "
                    f"{method_spec.parameters}, connector declares {actual_parameters}"
                )

        endpoint = FLEX_FEATURE_ENDPOINTS[expected.feature]
        metadata = _feature_metadata(feature_class)
        expected_package = (
            f"sila2.{metadata['originator']}.{metadata['category']}."
            f"{expected.class_name.lower()}.v{metadata['version'].split('.')[0]}"
        )
        if endpoint.package != expected_package:
            errors.append(
                f"{expected.feature.value}: client package {endpoint.package!r} "
                f"does not match connector package {expected_package!r}"
            )
        if endpoint.service != expected.class_name:
            errors.append(
                f"{expected.feature.value}: client service {endpoint.service!r} "
                f"does not match {expected.class_name!r}"
            )
    return errors


def _sila_methods(
    feature_class: ast.ClassDef,
) -> dict[str, tuple[FlexExecutionMode, tuple[str, ...]]]:
    methods: dict[str, tuple[FlexExecutionMode, tuple[str, ...]]] = {}
    for node in feature_class.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            mode = DECORATOR_MODES.get(ast.unparse(target))
            if mode is None:
                continue
            parameters = tuple(
                argument.arg
                for argument in (*node.args.args, *node.args.kwonlyargs)
                if argument.arg not in {"self", "status", "intermediate"}
            )
            methods[node.name] = (mode, parameters)
    return methods


def _feature_metadata(feature_class: ast.ClassDef) -> dict[str, str]:
    metadata = {"originator": "", "category": "", "version": "1.0"}
    initializer = next(
        (
            node
            for node in feature_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__init__"
        ),
        None,
    )
    if initializer is None:
        return metadata
    for call in (node for node in ast.walk(initializer) if isinstance(node, ast.Call)):
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "__init__":
            continue
        if ast.unparse(call.func.value) != "super()":
            continue
        for keyword in call.keywords:
            if keyword.arg in metadata and isinstance(keyword.value, ast.Constant):
                metadata[keyword.arg] = str(keyword.value.value)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--connector-repo",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "opentrons-flex",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    errors = check_contract(args.connector_repo.resolve())
    report = {
        "connector_repo": str(args.connector_repo.resolve()),
        "compatible": not errors,
        "errors": errors,
        "features": [
            {
                **asdict(feature),
                "feature": feature.feature.value,
                "methods": {
                    name: {
                        "mode": method.mode.value,
                        "parameters": list(method.parameters),
                    }
                    for name, method in feature.methods.items()
                },
            }
            for feature in EXPECTED_FEATURES
        ],
    }
    if args.json:
        print(json.dumps(report, indent=2))
    elif errors:
        print("Flex connector contract: incompatible")
        for error in errors:
            print(f"- {error}")
    else:
        print("Flex connector contract: compatible")
        print(f"Checked: {args.connector_repo.resolve()}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
