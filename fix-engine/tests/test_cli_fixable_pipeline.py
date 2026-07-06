"""End-to-end pipeline tests for REGISTERED fixable findings.

Guarantee under test: a QG report containing a finding whose rule_id is
in the fix registry flows through the whole CLI without crashing —
_build_patches must call fixers with their real signature
``(finding, file_content, config)``, not ``(finding, root)``.

Regression (adversarial review, major): fix_engine.py crashed with
``TypeError: fix_bare_except() missing 1 required positional argument:
'config'`` before any output was written, so --sarif (and every other
mode) only worked when all findings were unfixable.

Anti-cases: a finding pointing at a missing file is skipped, not a
crash; the built patch actually applies on disk under --fix.

Run standalone:
    python fix-engine/tests/test_cli_fixable_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# Ensure the fix-engine package root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fix_engine


BARE_EXCEPT_SOURCE = "try:\n    x = 1\nexcept:\n    pass\n"


# ── Helpers ───────────────────────────────────────────────────────────

def _write_report(tmp: str, findings) -> str:
    qg_path = os.path.join(tmp, "qg.json")
    with open(qg_path, "w", encoding="utf-8") as fh:
        json.dump({"findings": findings}, fh)
    return qg_path


def _write_target(tmp: str, name: str, text: str) -> str:
    target = os.path.join(tmp, name)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return target


def _bare_except_finding(target: str) -> dict:
    return {
        "rule_id": "bare_except",
        "file": target,
        "line": 3,
        "severity": "warning",
        "message": "bare except clause",
    }


def _run_cli(tmp: str, argv_tail) -> str:
    out_path = os.path.join(tmp, "out.json")
    rc = fix_engine.main(list(argv_tail) + ["--output", out_path])
    assert rc == 0, f"CLI exited nonzero: {rc}"
    with open(out_path, "r", encoding="utf-8") as fh:
        return fh.read()


# ── Regression tests (RED before fix: TypeError arity crash) ─────────

def test_sarif_with_registered_fixable_finding():
    """--sarif on a report with a registered fixable rule must not crash."""
    with tempfile.TemporaryDirectory() as tmp:
        target = _write_target(tmp, "victim.py", BARE_EXCEPT_SOURCE)
        qg_path = _write_report(tmp, [_bare_except_finding(target)])

        out = _run_cli(tmp, ["--qg-report", qg_path, "--sarif"])

        data = json.loads(out)
        assert data.get("version") == "2.1.0", f"not SARIF: {out[:200]!r}"
        assert "sarif-schema-2.1.0" in data.get("$schema", "")
        results = data["runs"][0]["results"]
        assert results and results[0]["ruleId"] == "bare_except", (
            f"fixable finding missing from SARIF results: {results}"
        )


def test_fix_applies_registered_fixer_end_to_end():
    """--fix must rewrite the target file via the registered fixer."""
    with tempfile.TemporaryDirectory() as tmp:
        target = _write_target(tmp, "victim.py", BARE_EXCEPT_SOURCE)
        qg_path = _write_report(tmp, [_bare_except_finding(target)])

        out = _run_cli(tmp, ["--qg-report", qg_path, "--fix", "--no-backup"])

        summary = json.loads(out)
        assert summary["total_patches"] == 1, f"no patch built: {summary}"
        assert summary["applied"] == 1, f"patch not applied: {summary}"
        with open(target, "r", encoding="utf-8", newline="") as fh:
            fixed = fh.read()
        assert fixed == "try:\n    x = 1\nexcept Exception:\n    pass\n", (
            f"file not fixed correctly: {fixed!r}"
        )


def test_relative_finding_path_resolves_against_root():
    """A relative finding path must be read relative to --root."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_target(tmp, "victim.py", BARE_EXCEPT_SOURCE)
        finding = _bare_except_finding("victim.py")
        qg_path = _write_report(tmp, [finding])

        out = _run_cli(
            tmp, ["--qg-report", qg_path, "--root", tmp, "--sarif"]
        )

        data = json.loads(out)
        results = data["runs"][0]["results"]
        assert results and results[0]["ruleId"] == "bare_except", (
            f"relative-path finding produced no SARIF result: {results}"
        )


# ── Anti-cases ────────────────────────────────────────────────────────

def test_missing_target_file_is_skipped_not_crash():
    """A fixable finding for a nonexistent file yields no patch, no crash."""
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "does_not_exist.py")
        qg_path = _write_report(tmp, [_bare_except_finding(missing)])

        out = _run_cli(tmp, ["--qg-report", qg_path])

        summary = json.loads(out)
        assert summary["total_patches"] == 0, (
            f"patch built for a missing file: {summary}"
        )


def test_unregistered_rule_still_ignored():
    """Anti-case: unregistered rule ids keep producing zero patches."""
    with tempfile.TemporaryDirectory() as tmp:
        target = _write_target(tmp, "victim.py", BARE_EXCEPT_SOURCE)
        finding = dict(_bare_except_finding(target), rule_id="not_a_rule")
        qg_path = _write_report(tmp, [finding])

        out = _run_cli(tmp, ["--qg-report", qg_path])

        summary = json.loads(out)
        assert summary["total_patches"] == 0, f"phantom patch: {summary}"


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
