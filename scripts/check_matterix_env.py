"""Diagnose whether the current Python env can run real Matterix examples.

This script is intentionally import-safe: it checks modules without launching
Isaac Sim or constructing a Matterix environment. By default it prints a
diagnostic report and exits 0. Use --strict when a missing requirement should
fail the command.
"""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_TASK = "Matterix-Test-Semantics-Heat-Transfer-Franka-v1"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True
    remedy: str | None = None

    @property
    def status(self) -> str:
        return "OK" if self.ok else "MISSING"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status
        return payload


def check_import(
    name: str,
    module: str,
    *,
    attr: str | None = None,
    required: bool = True,
    remedy: str | None = None,
) -> Check:
    """Check that a module and optional dotted attribute are importable."""
    try:
        imported = importlib.import_module(module)
        current: Any = imported
        if attr:
            for part in attr.split("."):
                current = getattr(current, part)
        location = getattr(imported, "__file__", None) or "built-in"
        return Check(name=name, ok=True, detail=str(location), required=required)
    except Exception as exc:  # noqa: BLE001 - diagnostics should report any failure
        return Check(
            name=name,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            required=required,
            remedy=remedy,
        )


def check_matterix_task(task: str) -> Check:
    """Check whether importing matterix_tasks registers the target gym task."""
    try:
        gym = importlib.import_module("gymnasium")
        importlib.import_module("matterix_tasks")
    except Exception as exc:  # noqa: BLE001 - diagnostics should report any failure
        return Check(
            name="Matterix gym task registration",
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            remedy=(
                "Install Matterix task packages in the active Isaac Lab Python "
                "env, e.g. python -m pip install -e /path/to/Matterix/source/*"
            ),
        )

    try:
        gym.spec(task)
    except Exception as exc:  # noqa: BLE001 - gym raises custom registry errors
        return Check(
            name="Matterix gym task registration",
            ok=False,
            detail=f"{task!r} not registered: {type(exc).__name__}: {exc}",
            remedy=(
                "Confirm the task id and that matterix_tasks import side effects "
                "registered the task."
            ),
        )
    return Check(
        name="Matterix gym task registration",
        ok=True,
        detail=f"{task!r} is registered",
    )


def build_checks(task: str) -> list[Check]:
    return [
        check_import(
            "twin_core",
            "twin_core",
            remedy=(
                "Run from this repo with uv run, or install with "
                "python -m pip install -e packages/twin-core"
            ),
        ),
        check_import(
            "twin_sim",
            "twin_sim",
            remedy=(
                "Run from this repo with uv run, or install with "
                "python -m pip install -e packages/twin-sim"
            ),
        ),
        check_import("pydantic", "pydantic"),
        check_import(
            "isaaclab.app.AppLauncher",
            "isaaclab.app",
            attr="AppLauncher",
            remedy=(
                "Activate the Isaac Lab Python environment before running real "
                "Matterix examples."
            ),
        ),
        check_import(
            "matterix_sm",
            "matterix_sm",
            remedy=(
                "Install Matterix state-machine package in the active Python env."
            ),
        ),
        check_import(
            "matterix_tasks",
            "matterix_tasks",
            remedy=(
                "Install Matterix task packages, usually from "
                "/path/to/Matterix/source/*."
            ),
        ),
        check_import(
            "gymnasium",
            "gymnasium",
            remedy="Install the Isaac Lab/Matterix Python environment.",
        ),
        check_matterix_task(task),
    ]


def format_report(checks: list[Check], task: str) -> str:
    lines = [
        "Matterix environment check",
        f"Python: {sys.executable}",
        f"Version: {platform.python_version()} ({platform.platform()})",
        f"Task: {task}",
        "",
    ]
    for check in checks:
        lines.append(f"[{check.status}] {check.name}: {check.detail}")
        if not check.ok and check.remedy:
            lines.append(f"  fix: {check.remedy}")

    missing_required = [check.name for check in checks if check.required and not check.ok]
    lines.append("")
    if missing_required:
        lines.append("Summary: real Matterix run is not ready.")
        lines.append("Missing: " + ", ".join(missing_required))
    else:
        lines.append("Summary: real Matterix imports and task registration look ready.")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether this Python env can run real Matterix examples."
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="Matterix gym task id to verify is registered.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a text report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when any required check is missing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks = build_checks(args.task)
    ready = all(check.ok for check in checks if check.required)

    if args.json:
        print(
            json.dumps(
                {
                    "ready": ready,
                    "python": {
                        "executable": sys.executable,
                        "version": platform.python_version(),
                        "platform": platform.platform(),
                    },
                    "task": args.task,
                    "checks": [check.to_dict() for check in checks],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(format_report(checks, args.task))

    return 0 if ready or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
