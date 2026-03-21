"""FEAT-014 — Tests for architecture severity gradient.

PRD: All CK findings currently rated "low" — no gradient.
Dead modules with blast-radius > 0 should be MEDIUM.
Untested files with high fan-in should be HIGH.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.severity_gradient import compute_finding_severity


# ── Dead Module Severity ─────────────────────────────────────────────


def test_dead_module_no_dependents_is_low():
    """Dead module with 0 fan-in → LOW."""
    sev = compute_finding_severity(
        policy="CK-ARCH-DEAD-MODULES",
        fan_in=0,
        prs=None,
        has_tests=False,
    )
    assert sev == "low"


def test_dead_module_with_dependents_is_medium():
    """Dead module with fan-in > 0 → MEDIUM (something imports it but CK thinks it's dead)."""
    sev = compute_finding_severity(
        policy="CK-ARCH-DEAD-MODULES",
        fan_in=3,
        prs=None,
        has_tests=False,
    )
    assert sev == "medium"


# ── Test Coverage Severity ───────────────────────────────────────────


def test_untested_high_fan_in_is_high():
    """Untested file with fan-in >= 10 → HIGH."""
    sev = compute_finding_severity(
        policy="CK-ARCH-TEST-COVERAGE",
        fan_in=12,
        prs=None,
        has_tests=False,
    )
    assert sev == "high"


def test_untested_low_fan_in_is_low():
    """Untested file with fan-in < 5 → LOW."""
    sev = compute_finding_severity(
        policy="CK-ARCH-TEST-COVERAGE",
        fan_in=2,
        prs=None,
        has_tests=False,
    )
    assert sev == "low"


def test_untested_medium_fan_in_is_medium():
    """Untested file with fan-in 5-9 → MEDIUM."""
    sev = compute_finding_severity(
        policy="CK-ARCH-TEST-COVERAGE",
        fan_in=7,
        prs=None,
        has_tests=False,
    )
    assert sev == "medium"


# ── Blast Radius Severity ───────────────────────────────────────────


def test_blast_radius_high_fan_in_low_prs_is_high():
    """Blast-radius file with high fan-in + low PRS → HIGH."""
    sev = compute_finding_severity(
        policy="CK-BLAST-RADIUS",
        fan_in=15,
        prs=40.0,
        has_tests=False,
    )
    assert sev == "high"


def test_blast_radius_high_fan_in_good_prs_is_medium():
    """Blast-radius file with high fan-in but good PRS → MEDIUM."""
    sev = compute_finding_severity(
        policy="CK-BLAST-RADIUS",
        fan_in=15,
        prs=90.0,
        has_tests=True,
    )
    assert sev == "medium"


# ── Default / Unknown Policy ────────────────────────────────────────


def test_unknown_policy_returns_low():
    """Unknown policy should return low as default."""
    sev = compute_finding_severity(
        policy="CK-UNKNOWN",
        fan_in=0,
        prs=None,
        has_tests=False,
    )
    assert sev == "low"


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
