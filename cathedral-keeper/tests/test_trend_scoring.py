"""S7 — Tests for ratchet-aware trend scoring.

Team Feedback #11: QG runs as point-in-time snapshot. Doesn't show
that score was 35 last month and is now 39 (improving). Transform
reports from "you're bad" to "you're improving."
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.trend import compute_trends, TrendReport


# ── Trend Computation Tests ──────────────────────────────────────────


def test_trend_improving():
    """Fewer findings than baseline → improving trend."""
    tr = compute_trends(
        current_counts={"CK-PY-CYCLES": 3, "CK-ARCH-DEAD-MODULES": 10},
        baseline_counts={"CK-PY-CYCLES": 5, "CK-ARCH-DEAD-MODULES": 15},
    )
    assert tr.total_current < tr.total_baseline
    assert tr.total_delta < 0
    assert tr.direction == "improving"


def test_trend_degrading():
    """More findings than baseline → degrading trend."""
    tr = compute_trends(
        current_counts={"CK-PY-CYCLES": 8},
        baseline_counts={"CK-PY-CYCLES": 3},
    )
    assert tr.total_delta > 0
    assert tr.direction == "degrading"


def test_trend_stable():
    """Same findings as baseline → stable trend."""
    tr = compute_trends(
        current_counts={"CK-PY-CYCLES": 5},
        baseline_counts={"CK-PY-CYCLES": 5},
    )
    assert tr.total_delta == 0
    assert tr.direction == "stable"


def test_trend_per_policy():
    """Per-policy deltas should be computed."""
    tr = compute_trends(
        current_counts={"CK-PY-CYCLES": 3, "CK-ARCH-DEAD-MODULES": 10},
        baseline_counts={"CK-PY-CYCLES": 5, "CK-ARCH-DEAD-MODULES": 8},
    )
    assert tr.per_policy["CK-PY-CYCLES"] == -2  # improved
    assert tr.per_policy["CK-ARCH-DEAD-MODULES"] == 2  # degraded


def test_trend_new_policy_in_current():
    """Policy in current but not baseline → shows as all new."""
    tr = compute_trends(
        current_counts={"CK-NEW-POLICY": 5},
        baseline_counts={},
    )
    assert tr.per_policy["CK-NEW-POLICY"] == 5


def test_trend_removed_policy_in_baseline():
    """Policy in baseline but not current → shows as removed."""
    tr = compute_trends(
        current_counts={},
        baseline_counts={"CK-OLD-POLICY": 3},
    )
    assert tr.per_policy["CK-OLD-POLICY"] == -3


def test_trend_no_baseline():
    """No baseline data → direction is 'no_baseline'."""
    tr = compute_trends(
        current_counts={"CK-PY-CYCLES": 5},
        baseline_counts=None,
    )
    assert tr.direction == "no_baseline"
    assert tr.total_baseline == 0


def test_trend_summary_string():
    """Summary string should include delta and direction."""
    tr = compute_trends(
        current_counts={"A": 10, "B": 5},
        baseline_counts={"A": 15, "B": 5},
    )
    summary = tr.summary
    assert "15" in summary or str(tr.total_current) in summary
    assert "improving" in summary.lower() or "-" in summary


def test_trend_report_has_fields():
    """TrendReport should have all expected fields."""
    tr = compute_trends(
        current_counts={"A": 5},
        baseline_counts={"A": 10},
    )
    assert hasattr(tr, "total_current")
    assert hasattr(tr, "total_baseline")
    assert hasattr(tr, "total_delta")
    assert hasattr(tr, "direction")
    assert hasattr(tr, "per_policy")
    assert hasattr(tr, "summary")


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
