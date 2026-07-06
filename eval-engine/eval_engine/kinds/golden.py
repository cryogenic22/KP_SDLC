"""Deterministic golden numeric compare.

A golden case compares an actual value against a reference within a tolerance
sourced from the metric-library contract (``expected.tolerance_metric`` ->
``metrics[<id>].tolerance``) -- the SAME number G4 reconciliation uses, so eval
and runtime-verify can never drift on "how close is close enough". No compare
bound is ever a literal in this module (the grep-gate enforces it); the value
lives only in the contract. A missing tolerance, or a non-numeric actual /
reference, fails CLOSED rather than passing by absence.
"""

from __future__ import annotations

_RELATIVE = "relative"


def _is_number(value) -> bool:
    """A real number to compare. ``bool`` is excluded: ``True`` is not a metric
    value, and admitting it would let a truthy flag masquerade as data."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _within_tolerance(actual, reference, tol_type: str, bound) -> bool:
    """True when ``actual`` matches ``reference`` within the contract ``bound``.

    ``relative`` scales the bound by the reference magnitude; when the reference
    is zero the relative bound collapses to exact equality (no division, no
    literal). ``bound`` originates in the metric contract, never here.
    """
    delta = abs(actual - reference)
    if tol_type == _RELATIVE:
        return delta <= bound * abs(reference)
    return delta <= bound


def evaluate_golden(actual, reference, tolerance) -> tuple:
    """Compare ``actual`` vs ``reference`` within the contract ``tolerance``.

    Returns ``(True, "")`` on a match, ``(False, reason)`` on a breach or a
    non-numeric operand, and ``(None, reason)`` (a loud skip) when no usable
    tolerance resolved -- every absence fails closed, never a silent pass.
    """
    if not tolerance:
        return None, "no tolerance resolved for golden compare (fail closed)"
    bound = tolerance.get("value")
    if not _is_number(bound):
        return None, "tolerance value is not numeric (fail closed)"
    if not (_is_number(actual) and _is_number(reference)):
        return False, (f"non-numeric golden operand "
                       f"(actual={actual!r}, reference={reference!r})")
    if _within_tolerance(actual, reference, str(tolerance.get("type")), bound):
        return True, ""
    return False, (f"golden breach: actual {actual} vs reference {reference} "
                   f"exceeds tolerance {tolerance.get('type')} {bound}")
