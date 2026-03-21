"""S1 — Tests for cross-stack duplicate exemption.

Team Feedback: QG flags backend+frontend type mirrors as duplicates
(e.g., ApprovalOut in schemas.py and approval.ts). These are intentional.
Also: Alembic upgrade/downgrade and enum values/label are always flagged.

TDD: Tests first, then implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_duplicates import (
    check_duplicate_helpers,
    _collect_function_sigs,
    _should_skip_cross_stack,
    _ALEMBIC_SKIP_NAMES,
    _ENUM_SKIP_NAMES,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_files(file_map: dict[str, str]) -> dict[Path, tuple[str, list[str], str, bool]]:
    """Build the all_files dict from {filename: content} map."""
    result = {}
    for name, content in file_map.items():
        path = Path(name)
        lines = content.splitlines()
        ext = path.suffix.lower()
        if ext == ".py":
            lang = "python"
        elif ext in (".ts", ".tsx"):
            lang = "typescript"
        elif ext in (".js", ".jsx"):
            lang = "javascript"
        else:
            lang = "unknown"
        is_test = "test_" in name or "/tests/" in name
        result[path] = (content, lines, lang, is_test)
    return result


def _run_duplicate_check(file_map: dict[str, str], config: dict = None) -> list[dict]:
    """Run duplicate detection and collect all issues."""
    issues = []
    all_files = _make_files(file_map)

    def add_issue_for_path(path):
        def add_issue(*, line, rule, severity, message, suggestion="", **kwargs):
            issues.append({"file": str(path), "line": line, "rule": rule, "message": message})
        return add_issue

    check_duplicate_helpers(
        all_files=all_files,
        config=config or {"rules": {"no_duplicate_code": {"enabled": True, "severity": "warning"}}},
        is_test_path=lambda p: "test_" in p.name,
        add_issue_for_path=add_issue_for_path,
    )
    return issues


# ── Cross-Stack Exemption Tests ──────────────────────────────────────


def test_cross_stack_exemption_helper():
    """_should_skip_cross_stack returns True for py+ts pair."""
    locations = [
        (Path("app/schemas.py"), 10, "ApprovalOut"),
        (Path("web/approval.ts"), 5, "ApprovalOut"),
    ]
    assert _should_skip_cross_stack(locations) is True


def test_cross_stack_same_language_not_exempt():
    """Same-language duplicates should NOT be exempt."""
    locations = [
        (Path("app/schemas.py"), 10, "ApprovalOut"),
        (Path("app/models.py"), 5, "ApprovalOut"),
    ]
    assert _should_skip_cross_stack(locations) is False


def test_cross_stack_three_files_mixed():
    """If duplicate spans >2 files and not all cross-stack, still flag."""
    locations = [
        (Path("app/schemas.py"), 10, "process"),
        (Path("app/utils.py"), 5, "process"),
        (Path("web/utils.ts"), 20, "process"),
    ]
    # Two Python files have the same function — not purely cross-stack
    assert _should_skip_cross_stack(locations) is False


def test_cross_stack_ts_tsx_pair():
    """TypeScript .tsx and Python .py should be exempt."""
    locations = [
        (Path("backend/models.py"), 1, "UserSchema"),
        (Path("frontend/components/user.tsx"), 1, "UserSchema"),
    ]
    assert _should_skip_cross_stack(locations) is True


# ── Alembic Skip List Tests ──────────────────────────────────────────


def test_alembic_upgrade_in_skip_list():
    """Alembic upgrade function should be in skip list."""
    assert "upgrade" in _ALEMBIC_SKIP_NAMES


def test_alembic_downgrade_in_skip_list():
    """Alembic downgrade function should be in skip list."""
    assert "downgrade" in _ALEMBIC_SKIP_NAMES


# ── Enum Skip List Tests ─────────────────────────────────────────────


def test_enum_values_in_skip_list():
    """Enum values method should be in skip list."""
    assert "values" in _ENUM_SKIP_NAMES


def test_enum_label_in_skip_list():
    """Enum label method should be in skip list."""
    assert "label" in _ENUM_SKIP_NAMES


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
