"""TDD spec for --autofix CLI flag integration.

When --autofix is passed, QG should generate machine-applicable diffs
for fixable findings and include them in the JSON output under an
"autofixes" key.
"""

from __future__ import annotations

import json
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── CLI Integration Tests ────────────────────────────────────────────


def test_autofix_flag_adds_fixes_to_json():
    """Running QG with autofix=True should add 'autofixes' to JSON output."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "fixable.py")
        with open(test_file, "w") as f:
            f.write("""import requests

response = requests.get(url)

try:
    risky()
except:
    pass
""")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])
        fixes = qg.generate_autofixes(result)

        assert isinstance(fixes, list)
        assert len(fixes) > 0


def test_autofix_returns_diff_strings():
    """Each autofix should have rule, file, line, diff, confidence."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "fixable.py")
        with open(test_file, "w") as f:
            f.write("""import requests
response = requests.get(url)
""")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])
        fixes = qg.generate_autofixes(result)

        timeout_fixes = [f for f in fixes if f["rule"] == "missing_requests_timeout"]
        if timeout_fixes:
            fix = timeout_fixes[0]
            assert "rule" in fix
            assert "file" in fix
            assert "line" in fix
            assert "diff" in fix
            assert "confidence" in fix
            assert "timeout" in fix["diff"]


def test_autofix_no_fixes_on_clean_file():
    """Clean file should produce empty autofixes list."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "clean.py")
        with open(test_file, "w") as f:
            f.write("x = 1\n")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])
        fixes = qg.generate_autofixes(result)

        assert isinstance(fixes, list)
        assert len(fixes) == 0


def test_autofix_json_output_includes_fixes():
    """generate_json_report with autofix=True should include 'autofixes' key."""
    from quality_gate import QualityGate

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "fixable.py")
        with open(test_file, "w") as f:
            f.write("""try:
    risky()
except:
    pass
""")

        qg = QualityGate(root_dir=tmpdir, quiet=True)
        result = qg.run(paths=[test_file])

        json_str = qg.generate_json_report(result, include_autofixes=True)
        data = json.loads(json_str)

        assert "autofixes" in data
        assert isinstance(data["autofixes"], list)


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
