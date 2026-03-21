from __future__ import annotations

import ast
import re
from pathlib import Path

from .context import RuleContext, rule_config


def apply(ctx: RuleContext) -> None:
    apply_python_rules(ctx)
    apply_web_rules(ctx)


def _parse_python_ast(ctx: RuleContext) -> ast.AST | None:
    if ctx.language != "python":
        return None
    try:
        return ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return None


def apply_python_rules(ctx: RuleContext) -> None:
    tree = _parse_python_ast(ctx)
    if tree is None:
        return
    _check_mutable_default(ctx, tree)
    _check_bare_except(ctx, tree)
    _check_command_injection(ctx, tree)
    _check_sql_injection(ctx, tree)


def apply_web_rules(ctx: RuleContext) -> None:
    if ctx.language not in {"typescript", "javascript"}:
        return
    _check_no_eval(ctx)
    _check_dangerously_set_html(ctx)


def _enabled(ctx: RuleContext, name: str, default: bool = False) -> bool:
    return bool(rule_config(ctx, name).get("enabled", default))


def _severity(ctx: RuleContext, name: str, default: str) -> str:
    return str(rule_config(ctx, name).get("severity") or default)


def _matches_any_path(path: Path, patterns: list[str]) -> bool:
    rel = str(path).replace("\\", "/")
    return any(Path(rel).match(pat) for pat in patterns)


def _check_mutable_default(ctx: RuleContext, tree: ast.AST) -> None:
    name = "mutable_default"
    if not _enabled(ctx, name, default=False):
        return

    severity = _severity(ctx, name, default="error")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defaults = list(getattr(node.args, "defaults", []) or [])
        kw_defaults = list(getattr(node.args, "kw_defaults", []) or [])
        for default_expr in [*defaults, *kw_defaults]:
            if default_expr is None:
                continue
            if isinstance(default_expr, (ast.List, ast.Dict, ast.Set)):
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=int(getattr(default_expr, "lineno", getattr(node, "lineno", 1)) or 1),
                    rule=name,
                    severity=severity,
                    message=f"Function '{node.name}' has a mutable default argument.",
                    suggestion="Use `None` and initialise inside the function.",
                )
                break
            if (
                isinstance(default_expr, ast.Call)
                and isinstance(default_expr.func, ast.Name)
                and default_expr.func.id in {"list", "dict", "set"}
            ):
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=int(getattr(default_expr, "lineno", getattr(node, "lineno", 1)) or 1),
                    rule=name,
                    severity=severity,
                    message=f"Function '{node.name}' has a mutable default argument.",
                    suggestion="Use `None` and initialise inside the function.",
                )
                break


def _check_bare_except(ctx: RuleContext, tree: ast.AST) -> None:
    name = "bare_except"
    if not _enabled(ctx, name, default=False):
        return
    severity = _severity(ctx, name, default="error")
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            ctx.add_issue(
                file=str(ctx.file_path),
                line=int(getattr(node, "lineno", 1) or 1),
                rule=name,
                severity=severity,
                message="Bare `except:` catches BaseException and can hide SystemExit/KeyboardInterrupt.",
                suggestion="Catch a specific exception (e.g., `except Exception as exc:`).",
            )


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _attr_chain(expr: ast.AST) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        root = _attr_chain(expr.value)
        return f"{root}.{expr.attr}" if root else expr.attr
    return None


def _check_command_injection(ctx: RuleContext, tree: ast.AST) -> None:
    name = "command_injection"
    if not _enabled(ctx, name, default=False):
        return
    severity = _severity(ctx, name, default="error")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node.func)
        if chain in {"os.system"}:
            ctx.add_issue(
                file=str(ctx.file_path),
                line=int(getattr(node, "lineno", 1) or 1),
                rule=name,
                severity=severity,
                message="Potential command injection: `os.system(...)` executes via shell.",
                suggestion="Use `subprocess.run([...], check=True)` with a list of args and `shell=False`.",
            )
            continue

        if not (chain and chain.startswith("subprocess.")):
            continue
        if chain.split(".", 1)[1] not in {"run", "Popen", "call", "check_output", "check_call"}:
            continue
        for kw in node.keywords:
            if kw.arg != "shell":
                continue
            if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=int(getattr(node, "lineno", 1) or 1),
                    rule=name,
                    severity=severity,
                    message="Potential command injection: subprocess called with `shell=True`.",
                    suggestion="Avoid `shell=True`; pass args as a list and validate inputs.",
                )


def _check_no_eval(ctx: RuleContext) -> None:
    name = "no_eval"
    if not _enabled(ctx, name, default=False):
        return
    severity = _severity(ctx, name, default="error")
    patterns = [re.compile(r"\beval\s*\("), re.compile(r"\bnew\s+Function\s*\(")]

    for i, line in enumerate(ctx.lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if "/*" in stripped:
            # avoid multi-line comment heuristics; this is a conservative rule
            continue
        if any(p.search(line) for p in patterns):
            ctx.add_issue(
                file=str(ctx.file_path),
                line=i,
                rule=name,
                severity=severity,
                message="Dynamic code execution (`eval`/`new Function`) is forbidden.",
                snippet=stripped[:120],
                suggestion="Remove `eval`/`new Function`; use safe parsing and explicit logic.",
            )


def _check_dangerously_set_html(ctx: RuleContext) -> None:
    name = "dangerously_set_html"
    if not _enabled(ctx, name, default=False):
        return
    rule = rule_config(ctx, name)
    exceptions = list(rule.get("exceptions") or [])
    if exceptions and _matches_any_path(ctx.file_path, exceptions):
        return

    severity = _severity(ctx, name, default="error")
    needle = "dangerouslySetInnerHTML"
    for i, line in enumerate(ctx.lines, 1):
        if needle not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        ctx.add_issue(
            file=str(ctx.file_path),
            line=i,
            rule=name,
            severity=severity,
            message="`dangerouslySetInnerHTML` can introduce XSS; avoid unless explicitly approved.",
            snippet=stripped[:120],
            suggestion="Prefer safe text rendering; if required, ensure sanitisation and add an allowlist exception.",
        )


def _is_sql_execute_call(node: ast.Call) -> bool:
    name = _call_name(node)
    if name in {"execute", "executemany"}:
        return True
    chain = _attr_chain(node.func)
    if not chain:
        return False
    return chain.endswith(".execute") or chain.endswith(".executemany")


def _is_dynamic_sql(expr: ast.AST) -> bool:
    if isinstance(expr, ast.JoinedStr):
        # Treat identifier-only interpolation (e.g. `FROM {table}`) as a separate concern:
        # it's risky if unvalidated, but it's also a common false-positive for SQL injection.
        for value in expr.values:
            if not isinstance(value, ast.FormattedValue):
                continue
            if not _is_safe_identifier_expr(value.value):
                return True
        return False

    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return True

    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "format"
    )


def _is_safe_identifier_expr(expr: ast.AST) -> bool:
    # Heuristic: allow table-name interpolation variables/attributes.
    if isinstance(expr, ast.Name) and expr.id in {"table", "table_name"}:
        return True
    if isinstance(expr, ast.Attribute) and expr.attr in {"table", "table_name"}:
        return _attr_chain(expr) in {"self.table", "self.table_name"}
    return False


def _check_sql_injection(ctx: RuleContext, tree: ast.AST) -> None:
    name = "sql_injection"
    if not _enabled(ctx, name, default=False):
        return

    severity = _severity(ctx, name, default="warning")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_sql_execute_call(node):
            continue
        if not node.args:
            continue
        sql = node.args[0]
        if not _is_dynamic_sql(sql):
            continue
        ctx.add_issue(
            file=str(ctx.file_path),
            line=int(getattr(node, "lineno", 1) or 1),
            rule=name,
            severity=severity,
            message="Possible SQL injection: dynamic SQL passed to `.execute()`.",
            suggestion="Use parametrised queries and pass parameters separately.",
        )
