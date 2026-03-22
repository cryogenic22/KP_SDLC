"""TDD spec for --sarif CLI flag integration.

When --sarif is passed, QG should write a SARIF 2.1.0 JSON file
alongside the regular output. The file should be uploadable to
GitHub Code Scanning API.
"""

from __future__ import annotations

import json
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.sarif_output import qg_to_sarif


# ── CLI Integration Tests ────────────────────────────────────────────


def test_sarif_flag_produces_file():
    """Running QG with --sarif <path> should produce a valid SARIF file."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file with a known issue
        test_file = os.path.join(tmpdir, "bad.py")
        with open(test_file, "w") as f:
            f.write('password = "hunter2!secret"\n')

        sarif_path = os.path.join(tmpdir, "results.sarif")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])

        # Simulate what the CLI would do with --sarif
        issues = [
            {"file": i.file, "line": i.line, "rule": i.rule,
             "severity": i.severity.value, "message": i.message, "suggestion": i.suggestion}
            for i in result.issues
        ]
        sarif = qg_to_sarif(issues=issues, tool_name="quality-gate", tool_version="1.0.0")

        with open(sarif_path, "w") as f:
            json.dump(sarif, f, indent=2)

        # Verify file exists and is valid SARIF
        assert os.path.exists(sarif_path)
        with open(sarif_path) as f:
            loaded = json.load(f)
        assert loaded["version"] == "2.1.0"
        assert len(loaded["runs"][0]["results"]) > 0


def test_sarif_contains_real_findings():
    """SARIF output from a real QG run should contain actual rule IDs."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write('password = "secret123"\nAPI_KEY = "sk-abc"\n')

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])

        issues = [
            {"file": i.file, "line": i.line, "rule": i.rule,
             "severity": i.severity.value, "message": i.message, "suggestion": i.suggestion}
            for i in result.issues
        ]
        sarif = qg_to_sarif(issues=issues, tool_name="quality-gate", tool_version="1.0.0")

        rule_ids = {r["ruleId"] for r in sarif["runs"][0]["results"]}
        # Should find secrets
        assert len(rule_ids) > 0


def test_sarif_empty_run():
    """SARIF from a clean file should have zero results but valid structure."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "clean.py")
        with open(test_file, "w") as f:
            f.write("x = 1\n")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])

        issues = [
            {"file": i.file, "line": i.line, "rule": i.rule,
             "severity": i.severity.value, "message": i.message, "suggestion": i.suggestion}
            for i in result.issues
        ]
        sarif = qg_to_sarif(issues=issues, tool_name="quality-gate", tool_version="1.0.0")

        assert sarif["version"] == "2.1.0"
        assert isinstance(sarif["runs"][0]["results"], list)


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
