"""S1 — Tests for duplicate-check exemptions.

Team Feedback: backend+frontend type mirrors (e.g. ApprovalOut in
schemas.py and approval.ts) must never be flagged — guaranteed by
construction since E13.0a: Python signatures hash the AST, web signatures
hash normalized text, so a py/web pair can never share a signature
(pinned by test_python_ts_mirror_never_grouped below).
Also: Alembic upgrade/downgrade and enum values/label are always skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_duplicates import (
    check_duplicate_helpers,
    _collect_function_sigs,
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


# ── Cross-Stack Structural Guarantee ─────────────────────────────────


def test_python_ts_mirror_never_grouped():
    """A py function and a ts function can never share a signature group.

    The old cross_stack_exempt flag is gone: Python hashes the AST
    (prefix "python:"), web hashes normalized text (prefix "web:"), so
    type mirrors are unreportable by construction.
    """
    sigs: dict[str, list] = defaultdict(list)
    py_src = (
        "def approval_out(payload):\n"
        "    checked = dict(payload)\n"
        "    checked[\"approved\"] = True\n"
        "    checked[\"source\"] = \"api\"\n"
        "    return checked\n"
    )
    ts_src = (
        "export function approvalOut(payload) {\n"
        "  const checked = {...payload};\n"
        "  checked.approved = true;\n"
        "  checked.source = \"api\";\n"
        "  return checked;\n"
        "}\n"
    )
    _collect_function_sigs(
        file_path=Path("app/schemas.py"), content=py_src,
        lines=py_src.splitlines(), language="python",
        func_signatures=sigs, min_lines=4,
    )
    _collect_function_sigs(
        file_path=Path("web/approval.ts"), content=ts_src,
        lines=ts_src.splitlines(), language="typescript",
        func_signatures=sigs, min_lines=4,
    )
    prefixes = {sig.split(":", 1)[0] for sig in sigs}
    assert prefixes == {"python", "web"}
    assert all(len(locs) == 1 for locs in sigs.values()), (
        "py and web functions must never share a signature group"
    )


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
