"""Phase 1 — Cross-Metric Coherence Check.

Detects when QG and CK metrics diverge in ways that indicate a measurement
system failure. Inspired by the CtxPack bug where word compression was 8.4x
but BPE compression was 1.0x — two independent measures of "compression"
diverged 8x without anyone noticing.

QG+CK equivalent: a repo could have PRS avg 95+ (QG says "great") while CK
has 15 high-severity findings ("architecture is degrading"). No cross-check
existed. This module adds that cross-check.
"""

from __future__ import annotations

from typing import Any, Dict, List

from cathedral_keeper.models import Evidence, Finding


def check_coherence(
    *,
    qg_findings: List[Finding],
    ck_findings: List[Finding],
    config: Dict[str, Any],
) -> List[Finding]:
    """Check that QG and CK metrics don't diverge suspiciously.

    Args:
        qg_findings: Findings from QG integration (policy_id contains "quality_gate").
        ck_findings: Findings from CK policies (non-QG findings).
        config: Coherence check configuration with optional keys:
            - prs_high_threshold (float): PRS avg above this is "high" (default: 90)
            - ck_high_severity_threshold (int): CK high-severity count above this is "many" (default: 10)
            - file_count (int): Total files in codebase (for suspiciously-clean check)
            - suspiciously_clean_file_threshold (int): Min files for zero-error flag (default: 20)
            - previous_total_findings (int): Finding count from last run (for drop detection)
            - finding_drop_pct (float): % drop threshold to warn (default: 50.0)

    Returns:
        List of coherence findings (policy_id="CK-COHERENCE").
    """
    results: List[Finding] = []

    results.extend(_check_prs_ck_divergence(qg_findings, ck_findings, config))
    results.extend(_check_suspiciously_clean(qg_findings, ck_findings, config))
    results.extend(_check_finding_count_drop(qg_findings, ck_findings, config))

    return results


def _check_prs_ck_divergence(
    qg_findings: List[Finding],
    ck_findings: List[Finding],
    config: Dict[str, Any],
) -> List[Finding]:
    """Flag when QG says code is great but CK says architecture is bad."""
    prs_threshold = float(config.get("prs_high_threshold", 90.0))
    ck_threshold = int(config.get("ck_high_severity_threshold", 10))

    # Extract PRS scores from QG findings metadata
    prs_scores = []
    for f in qg_findings:
        prs = f.metadata.get("prs")
        if prs is not None:
            prs_scores.append(float(prs))

    if not prs_scores:
        return []

    prs_avg = sum(prs_scores) / len(prs_scores)

    # Count high-severity CK findings
    ck_high_count = sum(1 for f in ck_findings if f.severity in ("high", "blocker"))

    if prs_avg > prs_threshold and ck_high_count > ck_threshold:
        return [
            Finding(
                policy_id="CK-COHERENCE",
                title=f"QG/CK metric coherence divergence detected",
                severity="medium",
                confidence="medium",
                why_it_matters=(
                    f"QG PRS average is {prs_avg:.1f} (above {prs_threshold}) suggesting good code quality, "
                    f"but CK has {ck_high_count} high-severity findings (above {ck_threshold}) suggesting "
                    f"architectural problems. These metrics should generally move together. "
                    f"Either QG rules are too lenient, CK policies are too strict, or the codebase has "
                    f"well-written code in a poorly-designed architecture."
                ),
                evidence=[
                    Evidence(
                        file="(cross-metric check)",
                        line=0,
                        snippet=f"PRS avg={prs_avg:.1f}, CK high-severity={ck_high_count}",
                        note="QG says good, CK says bad — investigate which is right",
                    )
                ],
                fix_options=[
                    "Review CK high-severity findings — are they real architectural issues?",
                    "Review QG rule configuration — are important patterns missing?",
                    "If CK findings are valid, the code is well-formatted but architecturally unsound.",
                ],
                verification=["ck analyze --root . --verbose"],
                metadata={
                    "prs_avg": round(prs_avg, 1),
                    "ck_high_severity_count": ck_high_count,
                    "check": "prs_ck_divergence",
                },
            )
        ]

    return []


def _check_suspiciously_clean(
    qg_findings: List[Finding],
    ck_findings: List[Finding],
    config: Dict[str, Any],
) -> List[Finding]:
    """Flag when QG reports zero issues on a large codebase."""
    file_count = int(config.get("file_count", 0))
    min_files = int(config.get("suspiciously_clean_file_threshold", 20))

    if file_count < min_files:
        return []

    # If there are NO QG findings at all on a large codebase, something may be wrong
    qg_integration_findings = [
        f for f in qg_findings
        if "quality_gate" in f.policy_id
    ]

    if len(qg_integration_findings) == 0:
        return [
            Finding(
                policy_id="CK-COHERENCE",
                title=f"Suspiciously clean QG results for {file_count}-file codebase",
                severity="info",
                confidence="low",
                why_it_matters=(
                    f"Quality Gate reported zero issues across {file_count} files. "
                    f"This is unusual for a codebase of this size and may indicate "
                    f"that QG rules are misconfigured, disabled, or that the QG integration "
                    f"silently failed."
                ),
                evidence=[
                    Evidence(
                        file="(cross-metric check)",
                        line=0,
                        snippet=f"0 QG findings across {file_count} files",
                        note="Verify QG is running with expected rule configuration",
                    )
                ],
                fix_options=[
                    "Run quality-gate standalone and verify it produces expected findings.",
                    "Check .quality-gate.json to ensure rules are enabled.",
                ],
                verification=["python quality-gate/quality_gate.py --root . --json"],
                metadata={"file_count": file_count, "qg_finding_count": 0, "check": "suspiciously_clean"},
            )
        ]

    return []


def _check_finding_count_drop(
    qg_findings: List[Finding],
    ck_findings: List[Finding],
    config: Dict[str, Any],
) -> List[Finding]:
    """Flag when total finding count drops significantly from previous run."""
    previous = config.get("previous_total_findings")
    if previous is None:
        return []

    previous_count = int(previous)
    if previous_count == 0:
        return []

    current_count = len(qg_findings) + len(ck_findings)
    drop_threshold_pct = float(config.get("finding_drop_pct", 50.0))

    drop_pct = ((previous_count - current_count) / previous_count) * 100

    if drop_pct > drop_threshold_pct:
        return [
            Finding(
                policy_id="CK-COHERENCE",
                title=f"Finding count drop: {previous_count} → {current_count} ({drop_pct:.0f}% decrease)",
                severity="medium",
                confidence="low",
                why_it_matters=(
                    f"Total findings dropped from {previous_count} to {current_count} "
                    f"({drop_pct:.0f}% decrease). This may indicate a stale graph cache, "
                    f"broken parser, disabled policies, or changes to file inclusion patterns. "
                    f"Genuine quality improvements are usually gradual, not sudden."
                ),
                evidence=[
                    Evidence(
                        file="(cross-metric check)",
                        line=0,
                        snippet=f"Previous: {previous_count}, Current: {current_count}, Drop: {drop_pct:.0f}%",
                        note="Verify analysis ran against the same files with the same config",
                    )
                ],
                fix_options=[
                    "Compare current config against previous run — did policies change?",
                    "Check if file inclusion/exclusion patterns changed.",
                    "If using graph cache, try `--no-cache` for a fresh analysis.",
                ],
                verification=["ck analyze --root . --verbose"],
                metadata={
                    "previous_count": previous_count,
                    "current_count": current_count,
                    "drop_pct": round(drop_pct, 1),
                    "check": "finding_count_drop",
                },
            )
        ]

    return []
