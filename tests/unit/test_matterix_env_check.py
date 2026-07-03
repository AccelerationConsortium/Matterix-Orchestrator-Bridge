"""Tests for the Matterix environment diagnostic script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_matterix_env.py"


def test_env_check_json_reports_checks_without_strict_failure() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", "--task", "Fake-Task-v0"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    names = {check["name"] for check in payload["checks"]}

    assert payload["task"] == "Fake-Task-v0"
    assert "twin_core" in names
    assert "twin_sim" in names
    assert "isaaclab.app.AppLauncher" in names
    assert "Matterix gym task registration" in names


def test_env_check_strict_fails_for_fake_task() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--strict", "--task", "Fake-Task-v0"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Summary: real Matterix run is not ready." in result.stdout
