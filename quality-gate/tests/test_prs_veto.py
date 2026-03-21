"""FEAT-003 — Tests for PRS severity veto and blast-weighted PRS.

PRD: Files with CRITICAL findings show PRS: VETOED, not a number.
B-PRS = raw_PRS - (fan_in * severity_penalty_multiplier).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.prs_engine import (
    compute_prs,
    compute_bprs,
    should_veto,
    PrsResult,
)


# ── Veto Tests ───────────────────────────────────────────────────────


def test_veto_on_critical_finding():
    """File with a CRITICAL finding should be vetoed."""
    assert should_veto(rule_severities=["warning", "critical", "error"]) is True


def test_no_veto_without_critical():
    """File without CRITICAL findings should NOT be vetoed."""
    assert should_veto(rule_severities=["error", "warning", "warning"]) is False


def test_veto_on_security_rules():
    """Security rules (sql_injection, command_injection) should trigger veto."""
    veto_rules = {"sql_injection", "command_injection", "no_hardcoded_secrets"}
    assert should_veto(rule_names=["sql_injection"], veto_rules=veto_rules) is True


def test_no_veto_on_non_security_rules():
    """Non-security rules should NOT trigger veto."""
    veto_rules = {"sql_injection", "command_injection"}
    assert should_veto(rule_names=["function_size"], veto_rules=veto_rules) is False


def test_no_veto_on_heuristic_rules():
    """Heuristic rules (sql_string_interpolation, no_hardcoded_secrets) should NOT veto by default."""
    assert should_veto(rule_names=["sql_string_interpolation"]) is False
    assert should_veto(rule_names=["no_hardcoded_secrets"]) is False


def test_veto_result_shows_vetoed():
    """Vetoed file should show score='VETOED', not a number."""
    result = compute_prs(errors=1, warnings=0, vetoed=True)
    assert result.vetoed is True
    assert result.display_score == "VETOED"


def test_non_veto_result_shows_number():
    """Non-vetoed file should show numeric score."""
    result = compute_prs(errors=1, warnings=2)
    assert result.vetoed is False
    assert result.display_score == "86.0"


# ── PRS Computation ──────────────────────────────────────────────────


def test_prs_formula_unchanged():
    """Standard PRS formula should still work: 100 - E*10 - W*2."""
    result = compute_prs(errors=2, warnings=3)
    assert result.score == 74.0


def test_prs_vetoed_score_zero():
    """Vetoed files have numeric score 0 for sorting purposes."""
    result = compute_prs(errors=0, warnings=0, vetoed=True)
    assert result.score == 0.0


# ── Blast-Weighted PRS ───────────────────────────────────────────────


def test_bprs_reduces_score_with_fan_in():
    """B-PRS should be lower than raw PRS for files with high fan-in."""
    raw = compute_prs(errors=1, warnings=2)  # PRS = 86
    bprs = compute_bprs(raw_prs=raw.score, fan_in=10)
    assert bprs < raw.score


def test_bprs_no_change_zero_fan_in():
    """B-PRS equals raw PRS when fan-in is 0."""
    raw = compute_prs(errors=1, warnings=2)  # PRS = 86
    bprs = compute_bprs(raw_prs=raw.score, fan_in=0)
    assert bprs == raw.score


def test_bprs_floor_zero():
    """B-PRS should never go below 0."""
    bprs = compute_bprs(raw_prs=50.0, fan_in=100)
    assert bprs >= 0.0


def test_bprs_higher_fan_in_lower_score():
    """Higher fan-in should produce lower B-PRS."""
    bprs_low = compute_bprs(raw_prs=80.0, fan_in=5)
    bprs_high = compute_bprs(raw_prs=80.0, fan_in=20)
    assert bprs_high < bprs_low


# ── PrsResult Dataclass ──────────────────────────────────────────────


def test_prs_result_has_fields():
    result = compute_prs(errors=1, warnings=1)
    assert hasattr(result, "score")
    assert hasattr(result, "errors")
    assert hasattr(result, "warnings")
    assert hasattr(result, "vetoed")
    assert hasattr(result, "display_score")


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
