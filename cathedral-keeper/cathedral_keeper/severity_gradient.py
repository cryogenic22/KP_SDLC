"""FEAT-014 — Architecture Severity Gradient.

Replaces the uniform "low" severity on all CK findings with a
context-aware gradient based on blast-radius, PRS, and test coverage.

| Severity | Criteria |
|----------|----------|
| HIGH     | blast-radius > 10 on file with PRS < 70, untested with fan-in >= 10 |
| MEDIUM   | blast-radius 5-10, dead modules with dependents, untested fan-in 5-9 |
| LOW      | dead code with 0 dependents, test gaps in non-critical modules |
"""

from __future__ import annotations

from typing import Optional


def compute_finding_severity(
    *,
    policy: str,
    fan_in: int = 0,
    prs: Optional[float] = None,
    has_tests: bool = False,
) -> str:
    """Compute severity for a CK finding based on architectural context.

    Args:
        policy: CK policy ID (e.g., "CK-ARCH-DEAD-MODULES").
        fan_in: Number of files that import this file.
        prs: QG PRS score for this file (None if unknown).
        has_tests: Whether any test file imports this file.

    Returns:
        Severity string: "high", "medium", or "low".
    """
    if policy == "CK-ARCH-DEAD-MODULES":
        return _dead_module_severity(fan_in=fan_in)

    if policy == "CK-ARCH-TEST-COVERAGE":
        return _test_coverage_severity(fan_in=fan_in)

    if policy == "CK-BLAST-RADIUS":
        return _blast_radius_severity(fan_in=fan_in, prs=prs, has_tests=has_tests)

    if policy == "CK-ARCH-TEST-ALIGNMENT":
        return _test_alignment_severity(fan_in=fan_in)

    return "low"


def _dead_module_severity(*, fan_in: int) -> str:
    """Dead modules with dependents are more concerning."""
    if fan_in > 0:
        return "medium"  # Something imports it but CK thinks it's dead — investigate
    return "low"


def _test_coverage_severity(*, fan_in: int) -> str:
    """Untested files with high fan-in are high risk."""
    if fan_in >= 10:
        return "high"
    if fan_in >= 5:
        return "medium"
    return "low"


def _blast_radius_severity(
    *,
    fan_in: int,
    prs: Optional[float],
    has_tests: bool,
) -> str:
    """High fan-in + low PRS + untested = highest risk."""
    prs_val = prs if prs is not None else 100.0

    if fan_in >= 10 and prs_val < 70:
        return "high"
    if fan_in >= 10:
        return "medium"
    if fan_in >= 5 and prs_val < 70:
        return "medium"
    return "low"


def _test_alignment_severity(*, fan_in: int) -> str:
    """Missing test files for high fan-in modules are more critical."""
    if fan_in >= 8:
        return "medium"
    return "low"
