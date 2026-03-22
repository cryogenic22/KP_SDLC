"""TDD spec for Auto-Fix Diff Engine.

Generates machine-applicable unified diffs for findings. The "silent
teaching" approach — developers learn patterns through corrections,
not documentation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.autofix import generate_fix, AutoFix


# ── AutoFix Structure ────────────────────────────────────────────────


def test_autofix_has_required_fields():
    """AutoFix should have rule, file, line, original, fixed, diff, confidence."""
    fix = generate_fix(
        rule="no_silent_catch",
        file="app.py",
        line=10,
        lines=["try:", "    risky()", "except:", "    pass"],
        context_start=0,
    )
    assert fix is not None
    assert hasattr(fix, "rule")
    assert hasattr(fix, "file")
    assert hasattr(fix, "line")
    assert hasattr(fix, "original")
    assert hasattr(fix, "fixed")
    assert hasattr(fix, "diff")
    assert hasattr(fix, "confidence")


# ── no_silent_catch → add logging ────────────────────────────────────


def test_fix_silent_catch_adds_logging():
    """except: pass → except Exception as e: logger.warning(...)."""
    lines = [
        "try:",
        "    risky_operation()",
        "except:",
        "    pass",
    ]
    fix = generate_fix(rule="no_silent_catch", file="app.py", line=3, lines=lines, context_start=0)
    assert fix is not None
    assert "pass" not in fix.fixed
    assert "except" in fix.fixed
    assert "log" in fix.fixed.lower() or "warning" in fix.fixed.lower() or "logger" in fix.fixed.lower()


def test_fix_silent_catch_except_exception_pass():
    """except Exception: pass → except Exception as e: logger.warning(...)."""
    lines = [
        "try:",
        "    do_something()",
        "except Exception:",
        "    pass",
    ]
    fix = generate_fix(rule="no_silent_catch", file="app.py", line=3, lines=lines, context_start=0)
    assert fix is not None
    assert "pass" not in fix.fixed


# ── missing_requests_timeout → add timeout ───────────────────────────


def test_fix_missing_timeout():
    """requests.get(url) → requests.get(url, timeout=30)."""
    lines = [
        "response = requests.get(url)",
    ]
    fix = generate_fix(rule="missing_requests_timeout", file="api.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert "timeout" in fix.fixed
    assert "30" in fix.fixed


def test_fix_missing_timeout_post():
    """requests.post(url, json=data) → requests.post(url, json=data, timeout=30)."""
    lines = [
        "response = requests.post(url, json=data)",
    ]
    fix = generate_fix(rule="missing_requests_timeout", file="api.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert "timeout" in fix.fixed


# ── Diff Format ──────────────────────────────────────────────────────


def test_fix_diff_is_unified_format():
    """Generated diff should be in unified diff format."""
    lines = [
        "try:",
        "    risky()",
        "except:",
        "    pass",
    ]
    fix = generate_fix(rule="no_silent_catch", file="app.py", line=3, lines=lines, context_start=0)
    assert fix is not None
    assert fix.diff.startswith("---") or fix.diff.startswith("@@")
    assert "+" in fix.diff or "-" in fix.diff


# ── Confidence Levels ────────────────────────────────────────────────


def test_fix_confidence_is_valid():
    """Confidence should be 'high', 'medium', or 'low'."""
    lines = ["response = requests.get(url)"]
    fix = generate_fix(rule="missing_requests_timeout", file="a.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert fix.confidence in ("high", "medium", "low")


# ── Unknown Rules ────────────────────────────────────────────────────


def test_unknown_rule_returns_none():
    """Rules without auto-fix support should return None."""
    fix = generate_fix(rule="some_unknown_rule_xyz", file="x.py", line=1, lines=["x = 1"], context_start=0)
    assert fix is None


# ── Multiple Fixes ───────────────────────────────────────────────────


def test_fix_does_not_modify_input():
    """Original lines list should not be mutated."""
    lines = ["response = requests.get(url)"]
    original = list(lines)
    generate_fix(rule="missing_requests_timeout", file="a.py", line=1, lines=lines, context_start=0)
    assert lines == original


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
