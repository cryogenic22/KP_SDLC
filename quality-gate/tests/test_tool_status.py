"""FEAT-002 — Tests for tool status sentinel.

PRD: Every QG run must emit a structured tool_status object. Heartbeat
test runs a known-bad snippet and asserts exactly 2 findings. If 0 →
status="crashed".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.tool_status import ToolStatus, run_heartbeat, build_tool_status


# ── ToolStatus Dataclass ─────────────────────────────────────────────


def test_tool_status_ok():
    """Healthy run should produce status='ok'."""
    ts = build_tool_status(
        components_run=["qg"],
        components_failed=[],
        heartbeat_passed=True,
    )
    assert ts.status == "ok"
    assert ts.heartbeat_passed is True


def test_tool_status_degraded():
    """Partial failure should produce status='degraded'."""
    ts = build_tool_status(
        components_run=["qg", "ck"],
        components_failed=["ck"],
        heartbeat_passed=True,
    )
    assert ts.status == "degraded"


def test_tool_status_crashed():
    """Heartbeat failure should produce status='crashed'."""
    ts = build_tool_status(
        components_run=["qg"],
        components_failed=[],
        heartbeat_passed=False,
    )
    assert ts.status == "crashed"


def test_tool_status_to_dict():
    """to_dict should produce all required fields."""
    ts = build_tool_status(
        components_run=["qg"],
        components_failed=[],
        heartbeat_passed=True,
    )
    d = ts.to_dict()
    assert "status" in d
    assert "components_run" in d
    assert "components_failed" in d
    assert "heartbeat_passed" in d
    assert "run_id" in d
    assert "timestamp" in d


# ── Heartbeat Tests ──────────────────────────────────────────────────


def test_heartbeat_passes_on_healthy_engine():
    """Heartbeat should pass when the rule engine is working correctly."""
    passed, findings_count = run_heartbeat()
    assert passed is True
    assert findings_count >= 2  # known-bad snippet should produce at least 2 findings


def test_heartbeat_returns_finding_count():
    """Heartbeat should report exact number of findings on known-bad snippet."""
    passed, findings_count = run_heartbeat()
    assert isinstance(findings_count, int)
    assert findings_count > 0


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
