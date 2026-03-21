"""Phase 4 — Red Team Checks for CK.

Adversarial sanity checks that catch measurement system failures.
Similar to CtxPack's 6 RT checks. These run AFTER all policies
and flag when the measurement system itself may be broken.

RT1: Finding count dropped >50% between runs → stale cache or broken parser?
RT2: PRS avg >95 for all files → rules too lenient?
RT3: CK found 0 issues on 500+ file codebase → graph build failure?
RT4: Blast-radius for any file is >50% of codebase → god module?
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from cathedral_keeper.models import Evidence, Finding


def run_red_team_checks(
    *,
    findings: List[Finding],
    file_count: int,
    config: Dict[str, Any],
) -> List[Finding]:
    """Run all red team checks against the analysis results.

    Args:
        findings: All findings from policies and integrations.
        file_count: Total number of files analyzed.
        config: Red team config with optional keys:
            - previous_finding_count (int): Finding count from last run
            - drop_threshold_pct (float): % drop to flag (default: 50)
            - prs_high_threshold (float): PRS avg above this is suspicious (default: 95)
            - zero_finding_file_threshold (int): Min files for RT3 (default: 500)
            - blast_radius_scores (dict): File → blast radius count
            - blast_radius_pct_threshold (float): % of codebase (default: 50)

    Returns:
        List of red team findings (policy_id="CK-RED-TEAM").
    """
    results: List[Finding] = []

    results.extend(_rt1_finding_count_drop(findings, config))
    results.extend(_rt2_suspiciously_high_prs(findings, file_count, config))
    results.extend(_rt3_zero_findings_large_codebase(findings, file_count, config))
    results.extend(_rt4_god_module(file_count, config))

    return results


def _rt1_finding_count_drop(
    findings: List[Finding],
    config: Dict[str, Any],
) -> List[Finding]:
    """RT1: Finding count dropped >50% between runs."""
    previous = config.get("previous_finding_count")
    if previous is None:
        return []

    previous_count = int(previous)
    if previous_count == 0:
        return []

    current_count = len(findings)
    threshold_pct = float(config.get("drop_threshold_pct", 50.0))
    drop_pct = ((previous_count - current_count) / previous_count) * 100

    if drop_pct > threshold_pct:
        return [
            Finding(
                policy_id="CK-RED-TEAM",
                title=f"RT1: Finding count dropped {drop_pct:.0f}% ({previous_count} → {current_count})",
                severity="medium",
                confidence="low",
                why_it_matters=(
                    f"Finding count dropped from {previous_count} to {current_count} "
                    f"({drop_pct:.0f}%). This may indicate a stale graph cache, broken parser, "
                    f"disabled policies, or changed file inclusion patterns. "
                    f"Genuine improvements are usually gradual."
                ),
                evidence=[
                    Evidence(
                        file="(red team check)",
                        line=0,
                        snippet=f"Previous: {previous_count}, Current: {current_count}",
                        note="Compare configs and file lists between runs",
                    )
                ],
                fix_options=[
                    "Compare current config against previous run.",
                    "Check if file inclusion/exclusion patterns changed.",
                    "Try clearing graph cache for a fresh analysis.",
                ],
                verification=["ck analyze --root . --verbose"],
                metadata={"check": "RT1", "previous": previous_count, "current": current_count},
            )
        ]

    return []


def _rt2_suspiciously_high_prs(
    findings: List[Finding],
    file_count: int,
    config: Dict[str, Any],
) -> List[Finding]:
    """RT2: PRS avg >95 for all files → rules may be too lenient."""
    threshold = float(config.get("prs_high_threshold", 95.0))

    prs_scores = []
    for f in findings:
        prs = f.metadata.get("prs")
        if prs is not None:
            prs_scores.append(float(prs))

    if not prs_scores:
        return []

    prs_avg = sum(prs_scores) / len(prs_scores)

    if prs_avg > threshold and file_count > 10:
        return [
            Finding(
                policy_id="CK-RED-TEAM",
                title=f"RT2: PRS average is suspiciously high ({prs_avg:.1f})",
                severity="info",
                confidence="low",
                why_it_matters=(
                    f"QG PRS average across {len(prs_scores)} files is {prs_avg:.1f}, "
                    f"above the suspicious threshold of {threshold}. "
                    f"This may indicate QG rules are too lenient or important rule packs "
                    f"are disabled. High PRS across a large codebase is unusual."
                ),
                evidence=[
                    Evidence(
                        file="(red team check)",
                        line=0,
                        snippet=f"PRS avg={prs_avg:.1f} across {len(prs_scores)} files",
                        note="Review QG rule configuration for completeness",
                    )
                ],
                fix_options=[
                    "Review .quality-gate.json — are all relevant rule packs enabled?",
                    "Check if PRS error_weight and warning_weight are set correctly.",
                ],
                verification=["python quality-gate/quality_gate.py --root . --json"],
                metadata={"check": "RT2", "prs_avg": round(prs_avg, 1), "file_count": len(prs_scores)},
            )
        ]

    return []


def _rt3_zero_findings_large_codebase(
    findings: List[Finding],
    file_count: int,
    config: Dict[str, Any],
) -> List[Finding]:
    """RT3: CK found 0 issues on 500+ file codebase → graph build failure?"""
    min_files = int(config.get("zero_finding_file_threshold", 500))

    if len(findings) > 0 or file_count < min_files:
        return []

    return [
        Finding(
            policy_id="CK-RED-TEAM",
            title=f"RT3: Zero findings on {file_count}-file codebase",
            severity="medium",
            confidence="low",
            why_it_matters=(
                f"CK analyzed {file_count} files and found zero issues. "
                f"This is statistically unlikely for a codebase of this size "
                f"and may indicate a graph build failure, all policies disabled, "
                f"or file filtering excluding most code."
            ),
            evidence=[
                Evidence(
                    file="(red team check)",
                    line=0,
                    snippet=f"0 findings across {file_count} files",
                    note="Verify graph built correctly and policies are enabled",
                )
            ],
            fix_options=[
                "Run with --verbose to check graph build stats.",
                "Verify policies are enabled in .cathedral-keeper.json.",
                "Check file exclusion patterns aren't too broad.",
            ],
            verification=["ck analyze --root . --verbose"],
            metadata={"check": "RT3", "file_count": file_count},
        )
    ]


def _rt4_god_module(
    file_count: int,
    config: Dict[str, Any],
) -> List[Finding]:
    """RT4: Blast-radius for any file is >50% of codebase → god module."""
    blast_scores = config.get("blast_radius_scores") or {}
    if not blast_scores or file_count == 0:
        return []

    threshold_pct = float(config.get("blast_radius_pct_threshold", 50.0))
    results: List[Finding] = []

    for file_path, radius_count in blast_scores.items():
        radius_pct = (int(radius_count) / file_count) * 100
        if radius_pct > threshold_pct:
            results.append(
                Finding(
                    policy_id="CK-RED-TEAM",
                    title=f"RT4: God module detected — {file_path} affects {radius_pct:.0f}% of codebase",
                    severity="medium",
                    confidence="medium",
                    why_it_matters=(
                        f"{file_path} has a blast radius of {radius_count} files "
                        f"({radius_pct:.0f}% of {file_count} total files). "
                        f"This indicates extreme coupling — any change to this file "
                        f"risks breaking a majority of the codebase."
                    ),
                    evidence=[
                        Evidence(
                            file=file_path,
                            line=0,
                            snippet=f"Blast radius: {radius_count}/{file_count} files ({radius_pct:.0f}%)",
                            note="Consider splitting this module to reduce coupling",
                        )
                    ],
                    fix_options=[
                        f"Extract independent concerns from {file_path} into separate modules.",
                        "Apply Interface Segregation — dependents should only import what they need.",
                    ],
                    verification=["ck analyze --root . --blast-radius --verbose"],
                    metadata={
                        "check": "RT4",
                        "file": file_path,
                        "radius": int(radius_count),
                        "radius_pct": round(radius_pct, 1),
                    },
                )
            )

    return results
