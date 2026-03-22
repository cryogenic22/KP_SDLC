"""TDD spec for reporting module tests.

The reporting module (health_score, grade, prs_grade, generate_html)
is the user-facing output and currently has ZERO tests. This is the
least-tested component despite being the most visible.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from __init__ import health_score, health_color, grade, prs_grade, esc


# ── health_score ─────────────────────────────────────────────────────


def test_health_score_perfect():
    """No errors, no warnings, no CK findings → 100."""
    qg = {"stats": {"files_checked": 10, "prs_files_failed": 0, "error": 0, "warning": 0}, "issues": []}
    ck = {"findings": []}
    assert health_score(qg, ck) == 100


def test_health_score_only_qg_errors():
    """QG errors should deduct from score."""
    qg = {"stats": {"files_checked": 10, "prs_files_failed": 0, "error": 50, "warning": 0}, "issues": []}
    ck = {"findings": []}
    s = health_score(qg, ck)
    assert 90 > s > 70  # 50 * 0.15 = 7.5 deducted


def test_health_score_excludes_prs_score_errors():
    """prs_score errors should NOT count toward error deductions."""
    qg_with_prs = {
        "stats": {"files_checked": 10, "prs_files_failed": 2, "error": 12, "warning": 0},
        "issues": [{"rule": "prs_score", "severity": "error"}] * 10 + [{"rule": "function_size", "severity": "error"}] * 2,
    }
    qg_without_prs = {
        "stats": {"files_checked": 10, "prs_files_failed": 2, "error": 2, "warning": 0},
        "issues": [{"rule": "function_size", "severity": "error"}] * 2,
    }
    # Both should give same error deduction (only 2 real errors)
    s1 = health_score(qg_with_prs, {"findings": []})
    s2 = health_score(qg_without_prs, {"findings": []})
    assert s1 == s2


def test_health_score_ck_high_findings():
    """CK high-severity findings should deduct from score."""
    qg = {"stats": {"files_checked": 10, "prs_files_failed": 0, "error": 0, "warning": 0}, "issues": []}
    ck = {"findings": [
        {"policy_id": "CK-ARCH-DEAD-MODULES", "severity": "high", "evidence": [{"file": f"f{i}.py"}]}
        for i in range(5)
    ]}
    s = health_score(qg, ck)
    assert s < 100  # 5 high * 2 = 10 pts deducted
    assert s >= 85


def test_health_score_excludes_qg_integration_from_ck():
    """CK-INTEGRATION::quality_gate findings should NOT count in CK deductions."""
    qg = {"stats": {"files_checked": 10, "prs_files_failed": 0, "error": 0, "warning": 0}, "issues": []}
    ck_with_qg = {"findings": [
        {"policy_id": "CK-INTEGRATION::quality_gate", "severity": "high", "evidence": [{"file": "x.py"}]}
        for _ in range(20)
    ]}
    ck_without = {"findings": []}
    assert health_score(qg, ck_with_qg) == health_score(qg, ck_without)


def test_health_score_capped_at_zero():
    """Score should never go below 0."""
    qg = {"stats": {"files_checked": 1, "prs_files_failed": 1, "error": 500, "warning": 2000}, "issues": []}
    ck = {"findings": [
        {"policy_id": "CK-X", "severity": "high", "evidence": [{"file": "x.py"}]}
        for _ in range(50)
    ]}
    assert health_score(qg, ck) >= 0


def test_health_score_capped_at_100():
    """Score should never exceed 100."""
    qg = {"stats": {"files_checked": 100, "prs_files_failed": 0, "error": 0, "warning": 0}, "issues": []}
    ck = {"findings": []}
    assert health_score(qg, ck) <= 100


def test_health_score_none_inputs():
    """None QG or CK data should not crash."""
    assert health_score(None, None) == 100
    assert health_score(None, {"findings": []}) == 100
    assert isinstance(health_score({"stats": {}, "issues": []}, None), int)


# ── health_color ─────────────────────────────────────────────────────


def test_health_color_green_above_80():
    assert health_color(85) == "#16a34a"


def test_health_color_yellow_60_to_80():
    assert health_color(70) == "#d97706"


def test_health_color_orange_40_to_60():
    assert health_color(50) == "#ea580c"


def test_health_color_red_below_40():
    assert health_color(20) == "#dc2626"


# ── grade ────────────────────────────────────────────────────────────


def test_grade_a():
    assert grade(95) == "A"
    assert grade(100) == "A"


def test_grade_b():
    assert grade(85) == "B"
    assert grade(94) == "B"


def test_grade_c():
    assert grade(70) == "C"


def test_grade_d():
    assert grade(55) == "D"


def test_grade_f():
    assert grade(30) == "F"
    assert grade(0) == "F"


# ── prs_grade ────────────────────────────────────────────────────────


def test_prs_grade_returns_tuple():
    """prs_grade should return (letter, hex_color)."""
    g, c = prs_grade(95)
    assert isinstance(g, str)
    assert isinstance(c, str)
    assert c.startswith("#")


def test_prs_grade_a():
    g, _ = prs_grade(95)
    assert g == "A"


def test_prs_grade_f():
    g, _ = prs_grade(30)
    assert g == "F"


# ── esc (HTML escaping) ─────────────────────────────────────────────


def test_esc_escapes_html():
    assert "&lt;" in esc("<script>")
    assert "&amp;" in esc("a & b")


def test_esc_handles_none():
    result = esc(None)
    assert isinstance(result, str)


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
