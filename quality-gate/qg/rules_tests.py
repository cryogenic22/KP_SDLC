from __future__ import annotations

import ast
import re

from .context import RuleContext, rule_config


def apply(ctx: RuleContext) -> None:
    if not ctx.is_test:
        return
    if ctx.language == "python":
        _apply_python(ctx)
    elif ctx.language in {"typescript", "javascript"}:
        _apply_web(ctx)


def _enabled(ctx: RuleContext, name: str, default: bool = False) -> bool:
    return bool(rule_config(ctx, name).get("enabled", default))


def _severity(ctx: RuleContext, name: str, default: str) -> str:
    return str(rule_config(ctx, name).get("severity") or default)


def _apply_python(ctx: RuleContext) -> None:
    try:
        tree = ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return

    _check_missing_test_assertion(ctx, tree)
    _check_test_isolation(ctx, tree)
    _check_test_naming(ctx, tree)


def _apply_web(ctx: RuleContext) -> None:
    _check_missing_test_assertion_web(ctx)


def _check_missing_test_assertion(ctx: RuleContext, tree: ast.AST) -> None:
    name = "missing_test_assertion"
    if not _enabled(ctx, name, default=False):
        return
    severity = _severity(ctx, name, default="warning")

    def _has_assertions(fn: ast.AST) -> bool:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assert):
                return True
            if isinstance(node, ast.With):
                for item in node.items:
                    call = item.context_expr
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "pytest"
                        and call.func.attr == "raises"
                    ):
                        return True
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("assert")
            ):
                return True
        return False

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        if _has_assertions(node):
            continue
        ctx.add_issue(
            file=str(ctx.file_path),
            line=int(getattr(node, "lineno", 1) or 1),
            rule=name,
            severity=severity,
            message=f"Test '{node.name}' contains no obvious assertions.",
            suggestion="Add assertions or use `pytest.raises(...)` to validate behaviour.",
        )


def _check_test_isolation(ctx: RuleContext, tree: ast.AST) -> None:
    name = "test_isolation"
    if not _enabled(ctx, name, default=False):
        return
    severity = _severity(ctx, name, default="warning")

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = getattr(node, "value", None)
            if value is None:
                continue
            if isinstance(value, (ast.List, ast.Dict, ast.Set)):
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=int(getattr(node, "lineno", 1) or 1),
                    rule=name,
                    severity=severity,
                    message="Module-level mutable state in tests can leak across cases.",
                    suggestion="Prefer fixtures or initialise per-test.",
                )
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in {"list", "dict", "set"}
            ):
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=int(getattr(node, "lineno", 1) or 1),
                    rule=name,
                    severity=severity,
                    message="Module-level mutable state in tests can leak across cases.",
                    suggestion="Prefer fixtures or initialise per-test.",
                )


def _check_test_naming(ctx: RuleContext, tree: ast.AST) -> None:
    name = "test_naming"
    if not _enabled(ctx, name, default=False):
        return
    severity = _severity(ctx, name, default="info")

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_") or node.name.startswith("test_"):
            continue
        # Only flag likely tests (decorated with pytest marks).
        if not node.decorator_list:
            continue
        if not any(
            isinstance(dec, ast.Attribute)
            and dec.attr == "mark"
            or isinstance(dec, ast.Attribute)
            and isinstance(dec.value, ast.Name)
            and dec.value.id == "pytest"
            for dec in node.decorator_list
        ):
            continue
        ctx.add_issue(
            file=str(ctx.file_path),
            line=int(getattr(node, "lineno", 1) or 1),
            rule=name,
            severity=severity,
            message=f"Test-like function '{node.name}' does not follow `test_*` naming.",
            suggestion="Rename to `test_*` so pytest can collect it.",
        )


def _check_missing_test_assertion_web(ctx: RuleContext) -> None:
    name = "missing_test_assertion"
    if not _enabled(ctx, name, default=False):
        return
    severity = _severity(ctx, name, default="warning")

    # Very lightweight heuristic: require `expect(` or `assert.` somewhere in the file.
    content = "\n".join(ctx.lines)
    if "expect(" in content or re.search(r"\bassert\.", content):
        return
    ctx.add_issue(
        file=str(ctx.file_path),
        line=1,
        rule=name,
        severity=severity,
        message="Test file contains no obvious assertions (`expect(...)` / `assert.*`).",
        suggestion="Add assertions to validate behaviour.",
    )
