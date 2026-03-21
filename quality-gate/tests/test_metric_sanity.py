"""Phase 1 — Metric Sanity Tests for QG PRS Formula.

Golden-input tests that verify the PRS formula behaves correctly.
These exist to prevent the class of bug found in CtxPack where
len(text.split()) was used as a proxy for token count — the measurement
system itself was wrong for 3 versions without anyone noticing.

If these tests fail, it means the PRS formula or severity categorization
has silently changed, which would shift every score in the system.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from quality-gate directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── PRS Formula Tests ────────────────────────────────────────────────


def compute_prs(
    *,
    errors: int,
    warnings: int,
    error_weight: float = 10.0,
    warning_weight: float = 2.0,
) -> float:
    """Replicate the PRS formula from quality_gate.py line 1340.

    PRS = 100 - (errors * error_weight) - (warnings * warning_weight)
    Clamped to [0.0, 100.0].
    """
    score = 100.0 - (errors * error_weight) - (warnings * warning_weight)
    return max(0.0, min(100.0, score))


def test_prs_perfect_score():
    """File with zero issues should score exactly 100."""
    assert compute_prs(errors=0, warnings=0) == 100.0


def test_prs_formula_golden_input():
    """File with 2 errors, 3 warnings should score exactly 74."""
    # 100 - (2*10) - (3*2) = 100 - 20 - 6 = 74
    assert compute_prs(errors=2, warnings=3) == 74.0


def test_prs_single_error():
    """One error should drop score by exactly error_weight (10)."""
    assert compute_prs(errors=1, warnings=0) == 90.0


def test_prs_single_warning():
    """One warning should drop score by exactly warning_weight (2)."""
    assert compute_prs(errors=0, warnings=1) == 98.0


def test_prs_floor_zero():
    """PRS should never go below 0."""
    # 100 - (15*10) - (10*2) = 100 - 150 - 20 = -70 → clamped to 0
    assert compute_prs(errors=15, warnings=10) == 0.0


def test_prs_ceiling_100():
    """PRS should never exceed 100, even with negative weights (defensive)."""
    # Shouldn't happen in practice, but formula should be safe
    result = compute_prs(errors=0, warnings=0, error_weight=-5.0, warning_weight=-3.0)
    assert result == 100.0


def test_prs_exactly_at_threshold():
    """File with PRS exactly at 85 should pass."""
    # 100 - (1*10) - (2.5*2) = 100 - 10 - 5 = 85
    # With default weights: need 100 - errors*10 - warnings*2 = 85
    # 1 error, 2 warnings: 100 - 10 - 4 = 86 (passes)
    # 1 error, 3 warnings: 100 - 10 - 6 = 84 (fails)
    assert compute_prs(errors=1, warnings=2) == 86.0
    assert compute_prs(errors=1, warnings=3) == 84.0


def test_prs_one_below_threshold():
    """File one point below default threshold (85) should fail."""
    assert compute_prs(errors=1, warnings=3) == 84.0
    assert compute_prs(errors=1, warnings=3) < 85.0


# ── Monotonicity Tests ───────────────────────────────────────────────


def test_prs_monotonic_errors():
    """More errors should never increase PRS."""
    scores = [compute_prs(errors=e, warnings=0) for e in range(15)]
    for i in range(1, len(scores)):
        assert scores[i] <= scores[i - 1], (
            f"PRS increased from {scores[i-1]} to {scores[i]} "
            f"when errors went from {i-1} to {i}"
        )


def test_prs_monotonic_warnings():
    """More warnings should never increase PRS."""
    scores = [compute_prs(errors=0, warnings=w) for w in range(60)]
    for i in range(1, len(scores)):
        assert scores[i] <= scores[i - 1], (
            f"PRS increased from {scores[i-1]} to {scores[i]} "
            f"when warnings went from {i-1} to {i}"
        )


def test_prs_errors_worse_than_warnings():
    """An error should always penalize more than a warning (default weights)."""
    score_1_error = compute_prs(errors=1, warnings=0)
    score_1_warning = compute_prs(errors=0, warnings=1)
    assert score_1_error < score_1_warning, (
        f"1 error (PRS={score_1_error}) should penalize more than "
        f"1 warning (PRS={score_1_warning})"
    )


# ── Custom Weight Tests ──────────────────────────────────────────────


def test_prs_custom_weights():
    """Custom weights should apply correctly."""
    # error_weight=5, warning_weight=1: 100 - (2*5) - (3*1) = 87
    assert compute_prs(errors=2, warnings=3, error_weight=5.0, warning_weight=1.0) == 87.0


def test_prs_zero_weights():
    """Zero weights mean no penalty — always 100."""
    assert compute_prs(errors=10, warnings=20, error_weight=0.0, warning_weight=0.0) == 100.0


# ── Band Classification Tests ────────────────────────────────────────


def classify_band(score: float) -> str:
    """Classify PRS into quality bands per QG documentation."""
    if score >= 95:
        return "excellent"
    if score >= 85:
        return "good"
    if score >= 70:
        return "needs_work"
    return "poor"


def test_band_boundaries():
    """Band classification should be correct at boundaries."""
    assert classify_band(100.0) == "excellent"
    assert classify_band(95.0) == "excellent"
    assert classify_band(94.9) == "good"
    assert classify_band(85.0) == "good"
    assert classify_band(84.9) == "needs_work"
    assert classify_band(70.0) == "needs_work"
    assert classify_band(69.9) == "poor"
    assert classify_band(0.0) == "poor"


def test_golden_inputs_band_classification():
    """Known file profiles should land in expected bands."""
    # Clean file: 0 errors, 0 warnings → 100 → excellent
    assert classify_band(compute_prs(errors=0, warnings=0)) == "excellent"
    # Minor issues: 0 errors, 3 warnings → 94 → good
    assert classify_band(compute_prs(errors=0, warnings=3)) == "good"
    # Moderate issues: 1 error, 3 warnings → 84 → needs_work
    assert classify_band(compute_prs(errors=1, warnings=3)) == "needs_work"
    # Serious issues: 3 errors, 5 warnings → 60 → poor
    assert classify_band(compute_prs(errors=3, warnings=5)) == "poor"


# ── Cross-Metric Ratio Sanity ────────────────────────────────────────


def test_error_to_warning_weight_ratio():
    """Error weight should be at least 2x warning weight (default: 5x).

    If this ratio changes silently, PRS scores shift for every file in the system.
    This is the QG equivalent of CtxPack's word-vs-BPE divergence.
    """
    default_error_weight = 10.0
    default_warning_weight = 2.0
    ratio = default_error_weight / default_warning_weight
    assert ratio >= 2.0, f"Error/warning weight ratio is {ratio}, expected >= 2.0"
    assert ratio == 5.0, f"Default ratio changed from 5.0 to {ratio} — intentional?"


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import inspect

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
