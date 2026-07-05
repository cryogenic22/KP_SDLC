"""Wire-up tests for the --sarif CLI flag in fix_engine.py.

Guarantee under test: `fix_engine --qg-report ... --sarif --output <path>`
writes a valid SARIF 2.1.0 document (non-empty results — no vacuous
output when the report uses fix-engine's `findings` shape), adds a
second run when --ck-report is given, and takes precedence over
--suggest.

Anti-case: without --sarif the CLI keeps emitting the summary JSON.

Run standalone:
    python fix-engine/tests/test_cli_sarif.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# Ensure the fix-engine package root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fix_engine


# ── Fixtures ──────────────────────────────────────────────────────────

# NOTE: rule id is deliberately NOT in the fix registry — _build_patches
# currently calls registered fixers with the wrong arity (fix_fn(finding,
# root) vs (finding, file_content, config)), which is a separate defect.
# These tests target the --sarif wiring only.
QG_FINDINGS_REPORT = {
    "findings": [
        {
            "rule_id": "qg_demo_rule",
            "file": "app.py",
            "line": 10,
            "severity": "warning",
            "message": "Demo finding",
        }
    ]
}

QG_ISSUES_REPORT = {
    "issues": [
        {
            "rule": "qg_demo_rule",
            "file": "app.py",
            "line": 10,
            "severity": "warning",
            "message": "Demo finding",
        }
    ]
}

CK_REPORT = {
    "findings": [
        {
            "policy_id": "CK-ARCH-CYCLES",
            "title": "Import cycle: a->b->a",
            "severity": "medium",
            "evidence": [{"file": "a.py", "line": 1, "note": "cycle start"}],
            "metadata": {},
        }
    ]
}


# ── Helpers ───────────────────────────────────────────────────────────

def _run_cli(tmp, qg_report, extra_args=(), ck_report=None) -> str:
    """Run fix_engine.main() writing to a temp --output file; return it."""
    qg_path = os.path.join(tmp, "qg.json")
    with open(qg_path, "w", encoding="utf-8") as fh:
        json.dump(qg_report, fh)

    out_path = os.path.join(tmp, "out.json")
    argv = ["--qg-report", qg_path, "--output", out_path]

    if ck_report is not None:
        ck_path = os.path.join(tmp, "ck.json")
        with open(ck_path, "w", encoding="utf-8") as fh:
            json.dump(ck_report, fh)
        argv += ["--ck-report", ck_path]

    argv += list(extra_args)
    rc = fix_engine.main(argv)
    assert rc == 0, f"CLI exited nonzero: {rc}"
    with open(out_path, "r", encoding="utf-8") as fh:
        return fh.read()


def _assert_valid_sarif(text: str) -> dict:
    data = json.loads(text)
    assert data.get("version") == "2.1.0", (
        f"not a SARIF document (version missing): {text[:200]!r}"
    )
    assert "sarif-schema-2.1.0" in data.get("$schema", ""), (
        f"$schema is not SARIF 2.1.0: {data.get('$schema')!r}"
    )
    assert isinstance(data.get("runs"), list) and data["runs"], "runs missing/empty"
    return data


# ── --sarif wire-up tests (RED before implementation) ─────────────────

def test_sarif_flag_emits_sarif():
    """--sarif writes valid SARIF with non-empty results (findings shape)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = _run_cli(tmp, QG_FINDINGS_REPORT, extra_args=["--sarif"])
        data = _assert_valid_sarif(out)
        assert len(data["runs"]) == 1
        results = data["runs"][0]["results"]
        assert results, (
            "SARIF QG run is empty — 'findings' were not mapped to "
            "'issues' (vacuous output)"
        )
        assert results[0]["ruleId"] == "qg_demo_rule"


def test_sarif_accepts_native_issues_report():
    """--sarif with QG's native {'issues': [...]} shape also yields results."""
    with tempfile.TemporaryDirectory() as tmp:
        out = _run_cli(tmp, QG_ISSUES_REPORT, extra_args=["--sarif"])
        data = _assert_valid_sarif(out)
        results = data["runs"][0]["results"]
        assert results, "SARIF QG run empty for native issues shape"
        assert results[0]["ruleId"] == "qg_demo_rule"


def test_sarif_with_ck_report_two_runs():
    """--sarif --ck-report produces two runs; CK findings stay in run[1]."""
    with tempfile.TemporaryDirectory() as tmp:
        out = _run_cli(
            tmp, QG_FINDINGS_REPORT, extra_args=["--sarif"], ck_report=CK_REPORT
        )
        data = _assert_valid_sarif(out)
        assert len(data["runs"]) == 2, f"expected 2 runs, got {len(data['runs'])}"
        assert data["runs"][1]["tool"]["driver"]["name"] == "cathedral-keeper"
        assert data["runs"][1]["results"], "CK run is empty (vacuous)"
        qg_rule_ids = [r["ruleId"] for r in data["runs"][0]["results"]]
        assert "CK-ARCH-CYCLES" not in qg_rule_ids, (
            f"CK findings leaked into the QG run: {qg_rule_ids}"
        )


def test_sarif_wins_over_suggest():
    """--sarif takes precedence over --suggest (documented precedence)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = _run_cli(
            tmp, QG_FINDINGS_REPORT, extra_args=["--sarif", "--suggest"]
        )
        # suggest mode emits markdown, which would fail JSON parsing
        _assert_valid_sarif(out)


# ── Anti-case (must be green before AND after) ───────────────────────

def test_default_output_is_not_sarif():
    """Anti-case: without --sarif the summary JSON is still emitted."""
    with tempfile.TemporaryDirectory() as tmp:
        out = _run_cli(tmp, QG_FINDINGS_REPORT)
        data = json.loads(out)
        assert "$schema" not in data, "default output hijacked by SARIF"
        assert "runs" not in data, "default output hijacked by SARIF"
        assert "total_patches" in data, f"summary shape changed: {data}"


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
