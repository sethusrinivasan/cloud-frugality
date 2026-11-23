"""
Test runner for TLA+ Engine Switching & URL Resolution Model Check.
"""
from __future__ import annotations

import os
import subprocess
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_tla_engine_switch_specification():
    """
    Executes TLC model checker on formal_spec/EngineSwitch.tla
    and verifies that all safety invariants hold:
    - TypeOK
    - NoLocalhostOnRemote
    - ValidRemoteResolution
    - LocalDevDefault
    """
    script_path = os.path.join(REPO_ROOT, "scripts", "verify_tla.sh")
    assert os.path.isfile(script_path), f"verify_tla.sh not found: {script_path}"

    res = subprocess.run([script_path], capture_output=True, text=True, check=False)
    print("\n--- TLC Output ---")
    print(res.stdout)
    if res.stderr:
        print(res.stderr)
    print("------------------")

    assert res.returncode == 0, f"TLC model checker failed with code {res.returncode}:\n{res.stdout}\n{res.stderr}"
    assert "Model checking completed. No error has been found." in res.stdout
    assert "Zero localhost leakage on remote deployments!" in res.stdout
