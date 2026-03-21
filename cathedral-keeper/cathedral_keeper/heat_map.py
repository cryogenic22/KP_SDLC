"""S4 — Risk-Adjusted Heat Map Scoring.

Team Feedback #6 + #8: Files that haven't changed in months get same
treatment as files changed yesterday. A 1,000-line file untouched for
6 months is low-risk debt. A 1,000-line file modified 10 times this
week is high-risk.

Risk score = f(change_frequency, fan_in, prs_score, has_tests)

High risk = frequently changed + low PRS + high fan-in + no tests
Low risk = rarely changed + any PRS (stable debt)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True, slots=True)
class RiskScore:
    """Risk assessment for a single file."""

    file: str
    change_frequency: int   # commits in lookback period
    fan_in: int             # number of files importing this one
    prs: float              # QG PRS score (0-100)
    has_tests: bool         # whether any test imports this file
    risk_score: float       # composite risk score (0-100)


def compute_risk_scores(
    *,
    change_counts: Dict[str, int],
    fan_in_scores: Dict[str, int],
    prs_scores: Dict[str, float],
    tested_files: Set[str],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, RiskScore]:
    """Compute risk scores for all files that appear in any input.

    Args:
        change_counts: file → number of commits in lookback period.
        fan_in_scores: file → number of importing files.
        prs_scores: file → QG PRS score (0-100).
        tested_files: set of files that have test coverage.
        weights: optional override for component weights.

    Returns:
        Dict mapping file path → RiskScore.
    """
    w = weights or {
        "change_frequency": 0.40,
        "quality_deficit": 0.25,
        "fan_in": 0.15,
        "no_tests": 0.20,
    }

    # Collect all files from any input source
    all_files = set(change_counts.keys()) | set(fan_in_scores.keys()) | set(prs_scores.keys())
    if not all_files:
        return {}

    # Normalize using absolute caps so scores are stable regardless of
    # how many files are analyzed. A file changed 10+ times in 30 days
    # is "hot" in any codebase. Fan-in of 20+ is high coupling anywhere.
    max_changes = max(max(change_counts.values(), default=1), 10)
    max_fan_in = max(max(fan_in_scores.values(), default=1), 20)

    results: Dict[str, RiskScore] = {}

    for file_path in all_files:
        changes = change_counts.get(file_path, 0)
        fan_in = fan_in_scores.get(file_path, 0)
        prs = prs_scores.get(file_path, 100.0)
        has_tests = file_path in tested_files

        # Component scores (each 0-100)
        change_score = (changes / max_changes) * 100
        quality_deficit = 100.0 - prs  # low PRS = high deficit
        fan_in_score = (fan_in / max_fan_in) * 100
        no_test_score = 100.0 if not has_tests else 0.0

        # Key insight from team feedback: quality deficit only matters
        # for actively changed files. Unchanged low-PRS files are
        # "stable debt" — address when touched, not urgently.
        # Scale quality_deficit by change activity (0 changes = 0 deficit risk).
        activity_factor = min(change_score / 100.0 * 2, 1.0)  # ramps up to 1.0 at 50% activity
        adjusted_deficit = quality_deficit * activity_factor

        # Weighted composite
        risk = (
            w["change_frequency"] * change_score
            + w["quality_deficit"] * adjusted_deficit
            + w["fan_in"] * fan_in_score
            + w["no_tests"] * no_test_score
        )
        risk = max(0.0, min(100.0, risk))

        results[file_path] = RiskScore(
            file=file_path,
            change_frequency=changes,
            fan_in=fan_in,
            prs=prs,
            has_tests=has_tests,
            risk_score=round(risk, 1),
        )

    return results


def classify_risk(score: float) -> str:
    """Classify a risk score into a human-readable category."""
    if score >= 70:
        return "high"
    if score >= 30:
        return "medium"
    if score >= 10:
        return "low"
    return "stable_debt"


def get_change_counts(
    *,
    root: Path,
    files: List[str],
    since_days: int = 30,
) -> Dict[str, int]:
    """Get commit counts per file from git log.

    Args:
        root: Repository root.
        files: Relative file paths to check.
        since_days: Lookback period in days.

    Returns:
        Dict mapping file → commit count in the period.
    """
    counts: Dict[str, int] = {}
    try:
        result = subprocess.run(
            [
                "git", "-C", str(root), "log",
                f"--since={since_days} days ago",
                "--format=", "--name-only",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip().replace("\\", "/")
                if line:
                    counts[line] = counts.get(line, 0) + 1
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return counts
