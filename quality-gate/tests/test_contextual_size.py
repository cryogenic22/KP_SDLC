"""S2 — Tests for language/context-specific function size limits.

Team Feedback: A 60-line React component with JSX is fundamentally
different from a 60-line Python business logic function. The flat
50-line limit penalizes UI components unfairly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_size import (
    _function_size_limit,
    _function_size_warning_limit,
    _detect_function_context,
)


# ── Context Detection Tests ──────────────────────────────────────────


def test_detect_context_python_normal():
    """Regular Python file → 'python' context."""
    assert _detect_function_context(
        language="python", extension=".py", is_test=False, file_path="app/services/auth.py"
    ) == "python"


def test_detect_context_python_test():
    """Python test file → 'test' context."""
    assert _detect_function_context(
        language="python", extension=".py", is_test=True, file_path="tests/test_auth.py"
    ) == "test"


def test_detect_context_tsx_component():
    """TSX file → 'react' context."""
    assert _detect_function_context(
        language="typescript", extension=".tsx", is_test=False, file_path="components/Button.tsx"
    ) == "react"


def test_detect_context_jsx_component():
    """JSX file → 'react' context."""
    assert _detect_function_context(
        language="javascript", extension=".jsx", is_test=False, file_path="components/Button.jsx"
    ) == "react"


def test_detect_context_ts_test():
    """TS test file → 'test' context."""
    assert _detect_function_context(
        language="typescript", extension=".ts", is_test=True, file_path="tests/auth.test.ts"
    ) == "test"


def test_detect_context_ts_normal():
    """Regular TS file → 'typescript' context."""
    assert _detect_function_context(
        language="typescript", extension=".ts", is_test=False, file_path="lib/api.ts"
    ) == "typescript"


def test_detect_context_migration():
    """Alembic/migration file → 'migration' context."""
    assert _detect_function_context(
        language="python", extension=".py", is_test=False, file_path="alembic/versions/001_init.py"
    ) == "migration"


def test_detect_context_seed():
    """Seed file → 'migration' context."""
    assert _detect_function_context(
        language="python", extension=".py", is_test=False, file_path="seeds/populate_data.py"
    ) == "migration"


# ── Limit Tests ──────────────────────────────────────────────────────


_BASE_CONFIG = {
    "rules": {
        "function_size": {
            "enabled": True,
            "max_lines": 50,
            "warning_lines": 30,
            "context_limits": {
                "python": {"max_lines": 50, "warning_lines": 30},
                "react": {"max_lines": 80, "warning_lines": 50},
                "test": {"max_lines": 100, "warning_lines": 60},
                "migration": {"max_lines": 200, "warning_lines": 150},
                "typescript": {"max_lines": 50, "warning_lines": 30},
            },
        }
    }
}


def test_limit_python_default():
    """Python functions: 50 lines max."""
    assert _function_size_limit(config=_BASE_CONFIG, language="python", extension=".py", context="python") == 50


def test_limit_react_component():
    """React components: 80 lines max."""
    assert _function_size_limit(config=_BASE_CONFIG, language="typescript", extension=".tsx", context="react") == 80


def test_limit_test_function():
    """Test functions: 100 lines max."""
    assert _function_size_limit(config=_BASE_CONFIG, language="python", extension=".py", context="test") == 100


def test_limit_migration():
    """Migration/seed scripts: 200 lines max."""
    assert _function_size_limit(config=_BASE_CONFIG, language="python", extension=".py", context="migration") == 200


def test_warning_limit_python():
    """Python warning threshold: 30 lines."""
    assert _function_size_warning_limit(config=_BASE_CONFIG, language="python", extension=".py", context="python") == 30


def test_warning_limit_react():
    """React warning threshold: 50 lines."""
    assert _function_size_warning_limit(config=_BASE_CONFIG, language="typescript", extension=".tsx", context="react") == 50


def test_warning_limit_test():
    """Test warning threshold: 60 lines."""
    assert _function_size_warning_limit(config=_BASE_CONFIG, language="python", extension=".py", context="test") == 60


def test_fallback_when_no_context_limits():
    """Without context_limits config, fall back to global max_lines."""
    config = {"rules": {"function_size": {"enabled": True, "max_lines": 50, "warning_lines": 30}}}
    assert _function_size_limit(config=config, language="typescript", extension=".tsx", context="react") == 50


# ── Practical Scenarios ──────────────────────────────────────────────


def test_70_line_react_not_error():
    """70-line React component should NOT exceed 80-line max."""
    limit = _function_size_limit(config=_BASE_CONFIG, language="typescript", extension=".tsx", context="react")
    assert 70 <= limit  # 70 < 80, no error


def test_70_line_python_is_error():
    """70-line Python function SHOULD exceed 50-line max."""
    limit = _function_size_limit(config=_BASE_CONFIG, language="python", extension=".py", context="python")
    assert 70 > limit  # 70 > 50, error


def test_90_line_test_not_error():
    """90-line test function should NOT exceed 100-line max."""
    limit = _function_size_limit(config=_BASE_CONFIG, language="python", extension=".py", context="test")
    assert 90 <= limit  # 90 < 100, no error


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
