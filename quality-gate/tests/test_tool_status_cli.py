"""TDD spec for tool_status integration in JSON output.

Every QG run should include a top-level 'tool_status' key in the JSON
output with status, heartbeat result, and component health.
"""

from __future__ import annotations

import json
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── JSON Output Integration Tests ────────────────────────────────────


def test_json_output_includes_tool_status():
    """JSON report should have top-level 'tool_status' key."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("x = 1\n")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])
        json_str = qg.generate_json_report(result)
        data = json.loads(json_str)

        assert "tool_status" in data


def test_tool_status_has_required_fields():
    """tool_status must have status, heartbeat_passed, components_run, run_id, timestamp."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("x = 1\n")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])
        json_str = qg.generate_json_report(result)
        data = json.loads(json_str)

        ts = data["tool_status"]
        assert "status" in ts
        assert "heartbeat_passed" in ts
        assert "components_run" in ts
        assert "run_id" in ts
        assert "timestamp" in ts


def test_tool_status_ok_on_healthy_run():
    """Normal run should produce status='ok' with heartbeat_passed=True."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("x = 1\n")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])
        json_str = qg.generate_json_report(result)
        data = json.loads(json_str)

        ts = data["tool_status"]
        assert ts["status"] == "ok"
        assert ts["heartbeat_passed"] is True


def test_tool_status_includes_qg_component():
    """components_run should include 'quality-gate'."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("x = 1\n")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])
        json_str = qg.generate_json_report(result)
        data = json.loads(json_str)

        assert "quality-gate" in data["tool_status"]["components_run"]


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
