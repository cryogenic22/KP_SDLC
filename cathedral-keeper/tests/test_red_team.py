"""Phase 4 — Tests for red team checks.

TDD: Adversarial sanity checks that catch measurement system failures.
Similar to CtxPack's 6 RT checks. These run AFTER all policies and
flag when the measurement system itself may be broken.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.models import Evidence, Finding


def _make_findings(count: int, severity: str = "medium") -> list[Finding]:
    """Create mock findings."""
    return [
        Finding(
            policy_id="CK-PY-CYCLES",
            title=f"Finding {i}",
            severity=severity,
            confidence="high",
            why_it_matters="test",
            evidence=[Evidence(file=f"file_{i}.py", line=1, snippet="test")],
            fix_options=[],
            verification=[],
            metadata={},
        )
        for i in range(count)
    ]


# ── Import module under test ─────────────────────────────────────────

from cathedral_keeper.red_team import run_red_team_checks


# ── RT1: Finding Count Drop ──────────────────────────────────────────


def test_rt1_flags_finding_count_drop():
    """RT1: Finding count dropped >50% from previous run."""
    results = run_red_team_checks(
        findings=_make_findings(5),
        file_count=100,
        config={"previous_finding_count": 20},
    )
    rt1 = [f for f in results if "RT1" in f.metadata.get("check", "")]
    assert len(rt1) >= 1


def test_rt1_no_flag_stable_count():
    """RT1: Stable finding count should not trigger."""
    results = run_red_team_checks(
        findings=_make_findings(18),
        file_count=100,
        config={"previous_finding_count": 20},
    )
    rt1 = [f for f in results if "RT1" in f.metadata.get("check", "")]
    assert len(rt1) == 0


def test_rt1_no_flag_no_previous():
    """RT1: No previous count available — skip check."""
    results = run_red_team_checks(
        findings=_make_findings(5),
        file_count=100,
        config={},
    )
    rt1 = [f for f in results if "RT1" in f.metadata.get("check", "")]
    assert len(rt1) == 0


# ── RT2: Suspiciously High PRS ───────────────────────────────────────


def test_rt2_flags_all_prs_above_95():
    """RT2: PRS avg >95 for all files suggests lenient rules."""
    # Create QG findings with high PRS
    qg_findings = [
        Finding(
            policy_id="CK-INTEGRATION::quality_gate",
            title="PRS 98",
            severity="medium",
            confidence="high",
            why_it_matters="test",
            evidence=[Evidence(file="a.py", line=1, snippet="test")],
            fix_options=[],
            verification=[],
            metadata={"prs": 98.0},
        ),
        Finding(
            policy_id="CK-INTEGRATION::quality_gate",
            title="PRS 97",
            severity="medium",
            confidence="high",
            why_it_matters="test",
            evidence=[Evidence(file="b.py", line=1, snippet="test")],
            fix_options=[],
            verification=[],
            metadata={"prs": 97.0},
        ),
    ]
    results = run_red_team_checks(
        findings=qg_findings,
        file_count=50,
        config={},
    )
    rt2 = [f for f in results if "RT2" in f.metadata.get("check", "")]
    assert len(rt2) >= 1


def test_rt2_no_flag_mixed_prs():
    """RT2: Mixed PRS scores should not trigger."""
    qg_findings = [
        Finding(
            policy_id="CK-INTEGRATION::quality_gate",
            title="PRS 72",
            severity="high",
            confidence="high",
            why_it_matters="test",
            evidence=[Evidence(file="a.py", line=1, snippet="test")],
            fix_options=[],
            verification=[],
            metadata={"prs": 72.0},
        ),
    ]
    results = run_red_team_checks(
        findings=qg_findings,
        file_count=50,
        config={},
    )
    rt2 = [f for f in results if "RT2" in f.metadata.get("check", "")]
    assert len(rt2) == 0


# ── RT3: Zero Issues on Large Codebase ───────────────────────────────


def test_rt3_flags_zero_findings_large_codebase():
    """RT3: CK found 0 issues on 500+ file codebase → warn."""
    results = run_red_team_checks(
        findings=[],
        file_count=500,
        config={},
    )
    rt3 = [f for f in results if "RT3" in f.metadata.get("check", "")]
    assert len(rt3) >= 1


def test_rt3_no_flag_zero_findings_small_codebase():
    """RT3: Zero findings on small codebase is normal."""
    results = run_red_team_checks(
        findings=[],
        file_count=10,
        config={},
    )
    rt3 = [f for f in results if "RT3" in f.metadata.get("check", "")]
    assert len(rt3) == 0


def test_rt3_no_flag_has_findings():
    """RT3: Having findings on a large codebase is normal."""
    results = run_red_team_checks(
        findings=_make_findings(10),
        file_count=500,
        config={},
    )
    rt3 = [f for f in results if "RT3" in f.metadata.get("check", "")]
    assert len(rt3) == 0


# ── RT4: God Module Detection ────────────────────────────────────────


def test_rt4_flags_god_module():
    """RT4: File with blast-radius >50% of codebase → warn."""
    results = run_red_team_checks(
        findings=_make_findings(5),
        file_count=100,
        config={"blast_radius_scores": {"core/db.py": 60}},  # 60% of 100 files
    )
    rt4 = [f for f in results if "RT4" in f.metadata.get("check", "")]
    assert len(rt4) >= 1


def test_rt4_no_flag_normal_fan_in():
    """RT4: Normal blast radius should not trigger."""
    results = run_red_team_checks(
        findings=_make_findings(5),
        file_count=100,
        config={"blast_radius_scores": {"core/db.py": 10}},  # 10% fine
    )
    rt4 = [f for f in results if "RT4" in f.metadata.get("check", "")]
    assert len(rt4) == 0


# ── Policy ID ────────────────────────────────────────────────────────


def test_red_team_findings_have_correct_policy_id():
    """All red team findings should use CK-RED-TEAM policy ID."""
    results = run_red_team_checks(
        findings=[],
        file_count=500,
        config={},
    )
    for f in results:
        assert f.policy_id == "CK-RED-TEAM"


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
