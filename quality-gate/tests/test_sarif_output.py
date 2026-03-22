"""TDD spec for SARIF 2.1.0 output module.

SARIF (Static Analysis Results Interchange Format) is the standard
for uploading findings to GitHub Code Scanning, GitLab SAST, etc.

Spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.sarif_output import qg_to_sarif, ck_to_sarif, validate_sarif_schema


# ── Fixtures ─────────────────────────────────────────────────────────

def _sample_qg_issues():
    return [
        {"file": "app.py", "line": 10, "rule": "function_size", "severity": "error",
         "message": "Function too long (80 lines, max 50).", "suggestion": "Split into smaller functions."},
        {"file": "app.py", "line": 25, "rule": "no_hardcoded_secrets", "severity": "error",
         "message": "Hardcoded secret detected.", "suggestion": "Use environment variables."},
        {"file": "utils.py", "line": 5, "rule": "dead_variable", "severity": "warning",
         "message": "Variable 'x' is assigned but never used.", "suggestion": "Remove unused variable."},
        {"file": "config.py", "line": 1, "rule": "missing_structured_logging", "severity": "info",
         "message": "No structured logging.", "suggestion": "Use structured logging."},
    ]


def _sample_ck_findings():
    return [
        {
            "policy_id": "CK-ARCH-DEAD-MODULES", "title": "Dead module: old_utils.py",
            "severity": "low", "confidence": "medium",
            "why_it_matters": "Never imported.", "evidence": [{"file": "old_utils.py", "line": 1, "snippet": "(no imports)", "note": "dead"}],
            "fix_options": ["Delete it."], "verification": ["grep import old_utils"], "metadata": {},
        },
        {
            "policy_id": "CK-BLAST-RADIUS", "title": "High fan-in: models.py",
            "severity": "medium", "confidence": "high",
            "why_it_matters": "16 files import this.", "evidence": [{"file": "models.py", "line": 1, "snippet": "fan-in=16", "note": "hotspot"}],
            "fix_options": ["Split module."], "verification": ["ck analyze"], "metadata": {"fan_in": 16},
        },
    ]


# ── Structure Tests ──────────────────────────────────────────────────


def test_sarif_has_required_top_level_keys():
    """SARIF output must have $schema, version, runs."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="quality-gate", tool_version="1.0.0")
    assert "$schema" in sarif
    assert sarif["version"] == "2.1.0"
    assert "runs" in sarif
    assert len(sarif["runs"]) == 1


def test_sarif_run_has_tool_and_results():
    """Each run must have tool (with driver) and results."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="quality-gate", tool_version="1.0.0")
    run = sarif["runs"][0]
    assert "tool" in run
    assert "driver" in run["tool"]
    assert run["tool"]["driver"]["name"] == "quality-gate"
    assert "results" in run


def test_sarif_result_count_matches_issues():
    """Number of SARIF results should match number of input issues."""
    issues = _sample_qg_issues()
    sarif = qg_to_sarif(issues=issues, tool_name="quality-gate", tool_version="1.0.0")
    assert len(sarif["runs"][0]["results"]) == len(issues)


# ── Severity Mapping ─────────────────────────────────────────────────


def test_sarif_severity_mapping():
    """error→error, warning→warning, info→note, critical→error."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="qg", tool_version="1.0")
    results = sarif["runs"][0]["results"]
    levels = {r["message"]["text"][:20]: r["level"] for r in results}
    # error issues → "error"
    assert any(r["level"] == "error" for r in results if "too long" in r["message"]["text"])
    # warning issues → "warning"
    assert any(r["level"] == "warning" for r in results if "never used" in r["message"]["text"])
    # info issues → "note"
    assert any(r["level"] == "note" for r in results if "structured logging" in r["message"]["text"])


# ── Location Data ────────────────────────────────────────────────────


def test_sarif_results_have_locations():
    """Each result must have at least one location with file and line."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="qg", tool_version="1.0")
    for result in sarif["runs"][0]["results"]:
        assert len(result["locations"]) >= 1
        loc = result["locations"][0]
        assert "physicalLocation" in loc
        assert "artifactLocation" in loc["physicalLocation"]
        assert "uri" in loc["physicalLocation"]["artifactLocation"]
        assert "region" in loc["physicalLocation"]
        assert "startLine" in loc["physicalLocation"]["region"]


def test_sarif_file_paths_are_relative():
    """File paths in SARIF should be relative URIs, not absolute."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="qg", tool_version="1.0")
    for result in sarif["runs"][0]["results"]:
        uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert not uri.startswith("/")
        assert not uri.startswith("C:")


# ── Rule Metadata ────────────────────────────────────────────────────


def test_sarif_driver_has_rules():
    """Driver should list all unique rule IDs with descriptions."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="qg", tool_version="1.0")
    driver = sarif["runs"][0]["tool"]["driver"]
    assert "rules" in driver
    rule_ids = {r["id"] for r in driver["rules"]}
    assert "function_size" in rule_ids
    assert "no_hardcoded_secrets" in rule_ids
    assert "dead_variable" in rule_ids


def test_sarif_results_reference_rule_id():
    """Each result must reference its rule via ruleId."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="qg", tool_version="1.0")
    for result in sarif["runs"][0]["results"]:
        assert "ruleId" in result
        assert len(result["ruleId"]) > 0


# ── CK to SARIF ─────────────────────────────────────────────────────


def test_ck_to_sarif_produces_valid_structure():
    """CK findings should also produce valid SARIF."""
    sarif = ck_to_sarif(findings=_sample_ck_findings(), tool_name="cathedral-keeper", tool_version="1.0.0")
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"][0]["results"]) == 2


def test_ck_sarif_uses_policy_id_as_rule():
    """CK SARIF should use policy_id as the ruleId."""
    sarif = ck_to_sarif(findings=_sample_ck_findings(), tool_name="cathedral-keeper", tool_version="1.0.0")
    rule_ids = {r["ruleId"] for r in sarif["runs"][0]["results"]}
    assert "CK-ARCH-DEAD-MODULES" in rule_ids
    assert "CK-BLAST-RADIUS" in rule_ids


def test_ck_sarif_includes_why_it_matters():
    """CK SARIF message should include the why_it_matters field."""
    sarif = ck_to_sarif(findings=_sample_ck_findings(), tool_name="cathedral-keeper", tool_version="1.0.0")
    messages = [r["message"]["text"] for r in sarif["runs"][0]["results"]]
    assert any("Never imported" in m for m in messages)


# ── JSON Serialization ───────────────────────────────────────────────


def test_sarif_is_json_serializable():
    """SARIF output must be JSON-serializable."""
    sarif = qg_to_sarif(issues=_sample_qg_issues(), tool_name="qg", tool_version="1.0")
    json_str = json.dumps(sarif)
    assert len(json_str) > 100
    parsed = json.loads(json_str)
    assert parsed["version"] == "2.1.0"


# ── Empty Input ──────────────────────────────────────────────────────


def test_sarif_empty_issues():
    """Empty issue list should produce valid SARIF with empty results."""
    sarif = qg_to_sarif(issues=[], tool_name="qg", tool_version="1.0")
    assert sarif["runs"][0]["results"] == []
    assert len(sarif["runs"][0]["tool"]["driver"]["rules"]) == 0


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
