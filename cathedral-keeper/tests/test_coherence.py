"""Phase 1 — Tests for cross-metric coherence check.

TDD: These tests define the coherence check contract.
Catches the CtxPack-style bug where two independent metrics
(word compression 8.4x vs BPE compression 1.0x) diverged 8x
without anyone noticing.

QG+CK equivalent: PRS avg 95+ but CK has 15 high-severity findings.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.models import Evidence, Finding


# ── Helper to build test data ────────────────────────────────────────


def _make_qg_findings(prs_scores: list[float]) -> list[Finding]:
    """Create mock QG integration findings with given PRS scores."""
    findings = []
    for i, score in enumerate(prs_scores):
        findings.append(
            Finding(
                policy_id="CK-INTEGRATION::quality_gate",
                title=f"PRS {score}",
                severity="high" if score < 85 else "medium",
                confidence="high",
                why_it_matters="test",
                evidence=[Evidence(file=f"file_{i}.py", line=1, snippet="test")],
                fix_options=[],
                verification=[],
                metadata={"prs": score, "errors": 0 if score >= 85 else 1, "warnings": 0},
            )
        )
    return findings


def _make_ck_findings(count: int, severity: str = "high") -> list[Finding]:
    """Create mock CK policy findings."""
    return [
        Finding(
            policy_id=f"CK-PY-CYCLES",
            title=f"Cycle {i}",
            severity=severity,
            confidence="high",
            why_it_matters="test",
            evidence=[Evidence(file=f"mod_{i}.py", line=1, snippet="test")],
            fix_options=[],
            verification=[],
            metadata={},
        )
        for i in range(count)
    ]


# ── Import the module under test ─────────────────────────────────────

from cathedral_keeper.coherence import check_coherence


# ── Tests: QG/CK Divergence ─────────────────────────────────────────


def test_coherence_flags_high_prs_with_many_ck_findings():
    """PRS avg >90 but CK has >10 high-severity findings → flag."""
    qg_findings = _make_qg_findings([95.0, 96.0, 94.0])  # avg ~95
    ck_findings = _make_ck_findings(12, severity="high")

    results = check_coherence(
        qg_findings=qg_findings,
        ck_findings=ck_findings,
        config={},
    )
    assert len(results) >= 1
    assert any("diverge" in f.title.lower() or "coherence" in f.title.lower() for f in results)


def test_coherence_passes_when_consistent():
    """Low PRS + many CK findings = consistent (both say quality is poor)."""
    qg_findings = _make_qg_findings([72.0, 68.0, 75.0])  # avg ~72
    ck_findings = _make_ck_findings(12, severity="high")

    results = check_coherence(
        qg_findings=qg_findings,
        ck_findings=ck_findings,
        config={},
    )
    # Should NOT flag divergence — metrics agree
    divergence_findings = [f for f in results if "diverge" in f.title.lower() or "coherence" in f.title.lower()]
    assert len(divergence_findings) == 0


def test_coherence_passes_high_prs_few_ck_issues():
    """High PRS + few CK findings = consistent (both say quality is good)."""
    qg_findings = _make_qg_findings([95.0, 98.0])
    ck_findings = _make_ck_findings(2, severity="high")

    results = check_coherence(
        qg_findings=qg_findings,
        ck_findings=ck_findings,
        config={},
    )
    divergence_findings = [f for f in results if "diverge" in f.title.lower() or "coherence" in f.title.lower()]
    assert len(divergence_findings) == 0


# ── Tests: Suspiciously Clean ────────────────────────────────────────


def test_coherence_flags_zero_qg_errors():
    """QG reports 0 errors across all files on a large codebase → suspicious."""
    # All PRS = 100 (zero errors, zero warnings)
    qg_findings = []  # No QG findings means all files passed clean
    ck_findings = _make_ck_findings(5, severity="medium")

    results = check_coherence(
        qg_findings=qg_findings,
        ck_findings=ck_findings,
        config={"file_count": 50},  # Large codebase
    )
    suspicious = [f for f in results if "suspicious" in f.title.lower() or "clean" in f.title.lower()]
    assert len(suspicious) >= 1


def test_coherence_no_flag_zero_errors_small_codebase():
    """Zero QG issues on a tiny codebase is normal, not suspicious."""
    results = check_coherence(
        qg_findings=[],
        ck_findings=[],
        config={"file_count": 3},
    )
    suspicious = [f for f in results if "suspicious" in f.title.lower() or "clean" in f.title.lower()]
    assert len(suspicious) == 0


# ── Tests: Finding Count Drop ────────────────────────────────────────


def test_coherence_flags_finding_count_drop():
    """Finding count dropped >50% from previous run → warn about stale cache."""
    results = check_coherence(
        qg_findings=[],
        ck_findings=_make_ck_findings(3),
        config={"previous_total_findings": 20},
    )
    drop_findings = [f for f in results if "drop" in f.title.lower()]
    assert len(drop_findings) >= 1


def test_coherence_no_flag_finding_count_stable():
    """Stable finding count should not trigger warning."""
    results = check_coherence(
        qg_findings=_make_qg_findings([80.0, 82.0]),
        ck_findings=_make_ck_findings(8),
        config={"previous_total_findings": 12},
    )
    drop_findings = [f for f in results if "drop" in f.title.lower()]
    assert len(drop_findings) == 0


# ── Tests: Configuration ─────────────────────────────────────────────


def test_coherence_custom_thresholds():
    """Custom thresholds should override defaults."""
    qg_findings = _make_qg_findings([92.0, 93.0])  # avg ~92.5
    ck_findings = _make_ck_findings(6, severity="high")

    # Default threshold for CK high count is 10 — should not trigger
    results_default = check_coherence(
        qg_findings=qg_findings, ck_findings=ck_findings, config={},
    )
    divergence_default = [f for f in results_default if "diverge" in f.title.lower() or "coherence" in f.title.lower()]

    # Custom threshold of 5 — should trigger
    results_custom = check_coherence(
        qg_findings=qg_findings, ck_findings=ck_findings,
        config={"ck_high_severity_threshold": 5},
    )
    divergence_custom = [f for f in results_custom if "diverge" in f.title.lower() or "coherence" in f.title.lower()]

    assert len(divergence_default) == 0
    assert len(divergence_custom) >= 1


# ── Tests: Policy ID ─────────────────────────────────────────────────


def test_coherence_findings_have_correct_policy_id():
    """All coherence findings should use CK-COHERENCE policy ID."""
    qg_findings = _make_qg_findings([95.0])
    ck_findings = _make_ck_findings(15, severity="high")

    results = check_coherence(
        qg_findings=qg_findings, ck_findings=ck_findings, config={},
    )
    for f in results:
        assert f.policy_id == "CK-COHERENCE"


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
