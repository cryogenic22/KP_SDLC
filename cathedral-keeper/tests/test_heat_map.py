"""S4 — Tests for risk-adjusted heat map scoring.

Team Feedback #6 + #8: Files that haven't changed in months get same
treatment as files changed yesterday. Need change-frequency heat map
and risk-adjusted scoring.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.heat_map import (
    compute_risk_scores,
    RiskScore,
    classify_risk,
)
from cathedral_keeper.models import Finding


# ── Risk Score Computation ───────────────────────────────────────────


def test_high_risk_frequently_changed_low_quality():
    """Frequently changed file with low PRS and high fan-in → high risk."""
    scores = compute_risk_scores(
        change_counts={"app/db.py": 10},
        fan_in_scores={"app/db.py": 15},
        prs_scores={"app/db.py": 40.0},
        tested_files=set(),
    )
    assert "app/db.py" in scores
    assert scores["app/db.py"].risk_score > 70


def test_low_risk_unchanged_low_quality():
    """Unchanged file with low PRS → low risk (stable debt)."""
    scores = compute_risk_scores(
        change_counts={"legacy/old.py": 0},
        fan_in_scores={"legacy/old.py": 2},
        prs_scores={"legacy/old.py": 40.0},
        tested_files=set(),
    )
    assert scores["legacy/old.py"].risk_score < 30


def test_low_risk_good_quality_tested():
    """Well-tested file with high PRS → lower risk than untested equivalent."""
    scores = compute_risk_scores(
        change_counts={"core/utils.py": 3},
        fan_in_scores={"core/utils.py": 3},
        prs_scores={"core/utils.py": 95.0},
        tested_files={"core/utils.py"},
    )
    # Good quality + tested + low fan-in + moderate changes → low-medium risk
    assert scores["core/utils.py"].risk_score < 30


def test_medium_risk_moderate_changes_no_tests():
    """Moderately changed, no tests, moderate PRS → medium risk."""
    scores = compute_risk_scores(
        change_counts={"services/auth.py": 4},
        fan_in_scores={"services/auth.py": 8},
        prs_scores={"services/auth.py": 70.0},
        tested_files=set(),
    )
    score = scores["services/auth.py"].risk_score
    assert 30 <= score <= 70


def test_tested_file_reduces_risk():
    """Having tests should reduce risk compared to untested."""
    base = {"app/x.py": 5}
    fan = {"app/x.py": 10}
    prs = {"app/x.py": 60.0}

    untested = compute_risk_scores(change_counts=base, fan_in_scores=fan, prs_scores=prs, tested_files=set())
    tested = compute_risk_scores(change_counts=base, fan_in_scores=fan, prs_scores=prs, tested_files={"app/x.py"})

    assert tested["app/x.py"].risk_score < untested["app/x.py"].risk_score


# ── Risk Classification ──────────────────────────────────────────────


def test_classify_high():
    assert classify_risk(85) == "high"


def test_classify_medium():
    assert classify_risk(50) == "medium"


def test_classify_low():
    assert classify_risk(15) == "low"


def test_classify_stable_debt():
    assert classify_risk(5) == "stable_debt"


# ── RiskScore Dataclass ──────────────────────────────────────────────


def test_risk_score_has_components():
    """RiskScore should expose individual component scores."""
    scores = compute_risk_scores(
        change_counts={"f.py": 5},
        fan_in_scores={"f.py": 10},
        prs_scores={"f.py": 60.0},
        tested_files=set(),
    )
    rs = scores["f.py"]
    assert hasattr(rs, "change_frequency")
    assert hasattr(rs, "fan_in")
    assert hasattr(rs, "prs")
    assert hasattr(rs, "has_tests")
    assert hasattr(rs, "risk_score")


def test_empty_inputs():
    """Empty inputs should return empty dict."""
    scores = compute_risk_scores(
        change_counts={},
        fan_in_scores={},
        prs_scores={},
        tested_files=set(),
    )
    assert scores == {}


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
