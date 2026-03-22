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


# ── bare_except → except Exception: ──────────────────────────────────


def test_fix_bare_except():
    """except: → except Exception:."""
    lines = [
        "try:",
        "    risky()",
        "except:",
        "    handle()",
    ]
    fix = generate_fix(rule="bare_except", file="app.py", line=3, lines=lines, context_start=0)
    assert fix is not None
    assert "except Exception:" in fix.fixed
    assert fix.confidence == "high"
    # original should still have bare except
    assert "except:" in fix.original


# ── no_debug_statements → line removed ───────────────────────────────


def test_fix_no_debug_breakpoint():
    """breakpoint() line should be removed."""
    lines = [
        "x = compute()",
        "breakpoint()",
        "return x",
    ]
    fix = generate_fix(rule="no_debug_statements", file="app.py", line=2, lines=lines, context_start=0)
    assert fix is not None
    assert fix.fixed == ""
    assert "breakpoint" in fix.original
    assert fix.confidence == "high"


def test_fix_no_debug_print_debug():
    """print(f"DEBUG ...") line should be removed."""
    lines = [
        "x = 1",
        'print(f"DEBUG value is {x}")',
        "return x",
    ]
    fix = generate_fix(rule="no_debug_statements", file="app.py", line=2, lines=lines, context_start=0)
    assert fix is not None
    assert fix.fixed == ""


def test_fix_no_debug_print_arrows():
    """print(">>> ...") line should be removed."""
    lines = [
        "x = 1",
        'print(">>> entering func")',
        "return x",
    ]
    fix = generate_fix(rule="no_debug_statements", file="app.py", line=2, lines=lines, context_start=0)
    assert fix is not None
    assert fix.fixed == ""


# ── mutable_default → None guard ─────────────────────────────────────


def test_fix_mutable_default_list():
    """def f(x=[]) → def f(x=None) + if x is None: x = []."""
    lines = [
        "def f(x=[]):",
        "    return x",
    ]
    fix = generate_fix(rule="mutable_default", file="app.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert "x=None" in fix.fixed
    assert "if x is None:" in fix.fixed
    assert "x = []" in fix.fixed
    assert fix.confidence == "high"


def test_fix_mutable_default_dict():
    """def f(x={}) → def f(x=None) + if x is None: x = {}."""
    lines = [
        "def process(data={}):",
        "    return data",
    ]
    fix = generate_fix(rule="mutable_default", file="app.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert "data=None" in fix.fixed
    assert "if data is None:" in fix.fixed
    assert "data = {}" in fix.fixed
    assert fix.confidence == "high"


# ── regex_compile_in_loop → hoist above loop ─────────────────────────


def test_fix_regex_compile_in_loop():
    """re.compile inside loop body should be hoisted above the loop."""
    lines = [
        "for item in items:",
        "    pat = re.compile(r'\\d+')",
        "    m = pat.match(item)",
    ]
    fix = generate_fix(rule="regex_compile_in_loop", file="app.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert fix.confidence == "medium"
    # The fixed output should have re.compile BEFORE the for line
    fixed_lines = fix.fixed.split("\n")
    compile_idx = None
    loop_idx = None
    for idx, ln in enumerate(fixed_lines):
        if "re.compile" in ln:
            compile_idx = idx
        if ln.strip().startswith("for "):
            loop_idx = idx
    assert compile_idx is not None and loop_idx is not None
    assert compile_idx < loop_idx, "re.compile should appear before the loop"


# ── string_concat_in_loop → list append + join ───────────────────────


def test_fix_string_concat_in_loop():
    """+= string in loop → _parts.append + join."""
    lines = [
        "for word in words:",
        "    result += word",
    ]
    fix = generate_fix(rule="string_concat_in_loop", file="app.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert fix.confidence == "medium"
    assert "_parts.append(word)" in fix.fixed
    assert '".join(_parts)' in fix.fixed or "\".join(_parts)" in fix.fixed


def test_fix_string_concat_reassign_in_loop():
    """result = result + expr in loop → _parts.append + join."""
    lines = [
        "for c in chars:",
        "    out = out + c",
    ]
    fix = generate_fix(rule="string_concat_in_loop", file="app.py", line=1, lines=lines, context_start=0)
    assert fix is not None
    assert "_parts.append(c)" in fix.fixed
    assert "out" in fix.fixed


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
