"""FEAT-003 — PRS Engine with Severity Veto and Blast-Weighted PRS.

Extends the PRS formula with:
1. Hard veto: CRITICAL findings or security rule matches → PRS: VETOED
2. B-PRS: Blast-weighted PRS that factors in fan-in count

The veto is not a numeric deduction — it's a categorical override that
communicates "this file cannot pass regardless of other scores."
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Set


@dataclass(frozen=True, slots=True)
class PrsResult:
    """Result of PRS computation for a single file."""

    score: float           # 0-100 (or 0 if vetoed)
    errors: int
    warnings: int
    vetoed: bool           # True if hard-vetoed by CRITICAL or security rule

    @property
    def display_score(self) -> str:
        """Human-readable score: 'VETOED' or numeric."""
        if self.vetoed:
            return "VETOED"
        return f"{self.score}"


# Default rules that trigger hard veto (security + critical agentic)
DEFAULT_VETO_RULES: Set[str] = {
    "sql_injection",
    "sql_string_interpolation",
    "command_injection",
    "no_hardcoded_secrets",
    "LLM-PY-DIRECT-EVAL",
    "PROMPT-PY-INJECTION-VECTOR",
    "LOOP-PY-WHILE-TRUE-LLM",
}


def should_veto(
    *,
    rule_severities: Optional[List[str]] = None,
    rule_names: Optional[List[str]] = None,
    veto_rules: Optional[Set[str]] = None,
) -> bool:
    """Determine if a file should be hard-vetoed.

    Args:
        rule_severities: List of severity strings from findings on this file.
        rule_names: List of rule IDs from findings on this file.
        veto_rules: Set of rule IDs that trigger veto (defaults to security rules).

    Returns:
        True if the file should be vetoed.
    """
    # Check for CRITICAL severity
    if rule_severities:
        for sev in rule_severities:
            if str(sev).lower() == "critical":
                return True

    # Check for veto rules
    if rule_names:
        check_rules = veto_rules or DEFAULT_VETO_RULES
        for rule in rule_names:
            if rule in check_rules:
                return True

    return False


def compute_prs(
    *,
    errors: int,
    warnings: int,
    error_weight: float = 10.0,
    warning_weight: float = 2.0,
    vetoed: bool = False,
) -> PrsResult:
    """Compute PRS for a file.

    If vetoed, score is set to 0 (for sorting) but display shows 'VETOED'.
    """
    if vetoed:
        return PrsResult(score=0.0, errors=errors, warnings=warnings, vetoed=True)

    score = 100.0 - (errors * error_weight) - (warnings * warning_weight)
    score = max(0.0, min(100.0, score))

    return PrsResult(score=round(score, 1), errors=errors, warnings=warnings, vetoed=False)


def compute_bprs(
    *,
    raw_prs: float,
    fan_in: int,
    multiplier: float = 0.5,
) -> float:
    """Compute blast-weighted PRS.

    B-PRS = raw_PRS - (fan_in * multiplier * (100 - raw_PRS) / 100)

    The penalty scales with both fan-in AND how bad the raw score is.
    A file with PRS 90 and fan-in 20 gets a small penalty.
    A file with PRS 50 and fan-in 20 gets a large penalty.

    Args:
        raw_prs: The standard PRS score (0-100).
        fan_in: Number of files that import this one.
        multiplier: Scaling factor (default 0.5).

    Returns:
        Blast-weighted PRS, clamped to [0, 100].
    """
    if fan_in == 0:
        return raw_prs

    deficit = 100.0 - raw_prs  # How bad the file is
    penalty = fan_in * multiplier * (deficit / 100.0)
    bprs = raw_prs - penalty

    return max(0.0, min(100.0, round(bprs, 1)))
