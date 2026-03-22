"""TDD spec for additional fixers to reach 35+ PRD target.

These are the P0 "Additional Rules" from the PRD section 6.2.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fe.registry import get_fix


def _apply(rule_id, code, line):
    fix_fn = get_fix(rule_id)
    if fix_fn is None:
        return None
    finding = {"rule": rule_id, "file": "test.py", "line": line, "message": "", "severity": "warning"}
    return fix_fn(finding, code, {})


# ── dict_get_default ─────────────────────────────────────────────────

def test_fix_dict_get_default():
    """d[k] if k in d else v → d.get(k, v)."""
    code = 'x = d[k] if k in d else default_val'
    patch = _apply("dict_get_default", code, 1)
    assert patch is not None
    assert ".get(" in patch.replacement
    assert patch.confidence >= 0.9
    assert patch.category == "safe"


# ── f_string_upgrade ─────────────────────────────────────────────────

def test_fix_format_to_fstring():
    """'{}'.format(x) → f'{x}'."""
    code = 'msg = "Hello {}".format(name)'
    patch = _apply("f_string_upgrade", code, 1)
    assert patch is not None
    assert "f'" in patch.replacement or 'f"' in patch.replacement
    assert patch.category == "safe"


def test_fix_percent_to_fstring():
    """'%s' % x → f'{x}'."""
    code = 'msg = "Hello %s" % name'
    patch = _apply("f_string_upgrade", code, 1)
    assert patch is not None
    assert "f'" in patch.replacement or 'f"' in patch.replacement


# ── missing_docstring ────────────────────────────────────────────────

def test_fix_missing_docstring():
    """Function without docstring → add placeholder."""
    code = 'def process(data):\n    return data'
    patch = _apply("missing_docstring", code, 1)
    assert patch is not None
    assert '"""' in patch.replacement
    assert patch.category == "safe"


# ── no_magic_numbers ─────────────────────────────────────────────────

def test_fix_magic_number():
    """Magic number → extract to named constant."""
    code = '    if retries > 5:'
    patch = _apply("no_magic_numbers", code, 1)
    assert patch is not None
    assert patch.category == "review"
    assert patch.confidence >= 0.7


# ── missing_error_type ───────────────────────────────────────────────

def test_fix_generic_exception():
    """raise Exception(...) → raise ValueError(...)."""
    code = '    raise Exception("invalid input")'
    patch = _apply("missing_error_type", code, 1)
    assert patch is not None
    assert "ValueError" in patch.replacement or "RuntimeError" in patch.replacement
    assert patch.category == "review"


# ── global_variable ──────────────────────────────────────────────────

def test_fix_global_mutable():
    """items = [] at module level → ITEMS: list = [] (UPPER_SNAKE)."""
    code = 'items = []\n\ndef process():\n    items.append(1)'
    patch = _apply("global_variable", code, 1)
    assert patch is not None
    assert patch.category == "review"


# ── hardcoded_model ──────────────────────────────────────────────────

def test_fix_hardcoded_model():
    """model="gpt-4" → MODEL_NAME = "gpt-4" (extract constant)."""
    code = '    response = client.chat.completions.create(model="gpt-4", messages=msgs)'
    patch = _apply("hardcoded_model", code, 1)
    assert patch is not None
    assert patch.category == "review"


# ── missing_response_model ───────────────────────────────────────────

def test_fix_missing_response_model():
    """FastAPI route without response_model → add placeholder."""
    code = '@app.get("/users")\ndef get_users():\n    return []'
    patch = _apply("missing_response_model", code, 1)
    assert patch is not None
    assert "response_model" in patch.replacement
    assert patch.category == "review"


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
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
