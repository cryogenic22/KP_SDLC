"""S7 — Ratchet-Aware Trend Scoring.

Team Feedback #11: Transform reports from "you're bad" to "you're improving."
If a baseline exists, show trend indicators:
  "Findings: 1769 (↓231 from baseline)"
  "CK-PY-CYCLES: 3 (↓2 from baseline)"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class TrendReport:
    """Trend comparison between current and baseline analysis."""

    total_current: int
    total_baseline: int
    total_delta: int         # negative = improvement
    direction: str           # "improving", "degrading", "stable", "no_baseline"
    per_policy: Dict[str, int]  # policy_id → delta (negative = improvement)

    @property
    def summary(self) -> str:
        """Human-readable trend summary."""
        if self.direction == "no_baseline":
            return f"Findings: {self.total_current} (no baseline for comparison)"

        if self.total_delta == 0:
            return f"Findings: {self.total_current} (stable, same as baseline)"

        arrow = "down" if self.total_delta < 0 else "up"
        abs_delta = abs(self.total_delta)
        verb = "improving" if self.total_delta < 0 else "degrading"

        return (
            f"Findings: {self.total_current} "
            f"({arrow} {abs_delta} from baseline {self.total_baseline}, {verb})"
        )


def compute_trends(
    *,
    current_counts: Dict[str, int],
    baseline_counts: Optional[Dict[str, int]],
) -> TrendReport:
    """Compute trend deltas between current and baseline finding counts.

    Args:
        current_counts: Dict mapping policy_id → finding count for current run.
        baseline_counts: Dict mapping policy_id → finding count from baseline.
            None if no baseline exists.

    Returns:
        TrendReport with total and per-policy deltas.
    """
    if baseline_counts is None:
        total_current = sum(current_counts.values())
        return TrendReport(
            total_current=total_current,
            total_baseline=0,
            total_delta=0,
            direction="no_baseline",
            per_policy={},
        )

    # Compute per-policy deltas
    all_policies = set(current_counts.keys()) | set(baseline_counts.keys())
    per_policy: Dict[str, int] = {}

    for policy in all_policies:
        current = current_counts.get(policy, 0)
        baseline = baseline_counts.get(policy, 0)
        delta = current - baseline
        if delta != 0:
            per_policy[policy] = delta

    total_current = sum(current_counts.values())
    total_baseline = sum(baseline_counts.values())
    total_delta = total_current - total_baseline

    if total_delta < 0:
        direction = "improving"
    elif total_delta > 0:
        direction = "degrading"
    else:
        direction = "stable"

    return TrendReport(
        total_current=total_current,
        total_baseline=total_baseline,
        total_delta=total_delta,
        direction=direction,
        per_policy=per_policy,
    )
