"""
Python-Specific Code Quality Checks

Rules migrated from Cathedral Keeper (per-file, no cross-file graph needed):
- missing_requests_timeout: requests.* calls without timeout=
- syspath_manipulation: sys.path.append/insert/extend calls

Phase 2 rules:
- mutable_default_argument: Mutable/call-time defaults in function defs
- cursor_double_consume: Same cursor consumed twice (.fetchone()/.one() x2)
- empty_context_manager_exit: __exit__ method that does nothing

Additional Python-specific rules for the python pack.
"""

from __future__ import annotations

import ast
import re

from .context import RuleContext, rule_config


def _enabled(ctx: RuleContext, name: str, *, default: bool = True) -> bool:
    return bool(rule_config(ctx, name).get("enabled", default))


def _severity(ctx: RuleContext, name: str, *, default: str) -> str:
    return str(rule_config(ctx, name).get("severity") or default)


# ═══════════════════════════════════════════════════════════════════════════
# 1. missing_requests_timeout
# ═══════════════════════════════════════════════════════════════════════════

_REQUESTS_CALL_RE = re.compile(
    r"\brequests\.(get|post|put|delete|patch|head|request)\s*\("
)


def _check_missing_requests_timeout(ctx: RuleContext) -> None:
    """
    Detect requests.get/post/put/delete/patch/head/request() calls
    without an explicit ``timeout=`` keyword argument.

    Migrated from CK-PY-REQUESTS-TIMEOUT.  Extended to also cover
    ``requests.request()`` and ``requests.head()``.
    """
    name = "missing_requests_timeout"
    if not _enabled(ctx, name, default=True):
        return
    if ctx.language != "python":
        return
    if "requests." not in ctx.content:
        return

    severity = _severity(ctx, name, default="warning")

    for i, line in enumerate(ctx.lines, 1):
        if "requests." not in line:
            continue
        if not _REQUESTS_CALL_RE.search(line):
            continue
        # Check the current line and a few continuation lines for timeout=
        window = "\n".join(ctx.lines[i - 1 : min(len(ctx.lines), i + 4)])
        if "timeout=" in window or "timeout =" in window:
            continue
        ctx.add_issue(
            file=str(ctx.file_path),
            line=i,
            rule=name,
            severity=severity,
            message="requests.* call without explicit timeout. Can hang workers indefinitely.",
            snippet=line.strip()[:120],
            suggestion="Add timeout= parameter (e.g. timeout=30). Consider retries/backoff for transient failures.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. syspath_manipulation
# ═══════════════════════════════════════════════════════════════════════════

_SYSPATH_RE = re.compile(r"\bsys\.path\.(insert|append|extend)\s*\(")
_SYSPATH_IADD_RE = re.compile(r"\bsys\.path\s*\+=")
_SYSPATH_ASSIGN_RE = re.compile(r"\bsys\.path\s*=\s*sys\.path\s*\+")

# Files that commonly need sys.path manipulation
_SYSPATH_EXEMPT_PATTERNS = (
    "conftest.py",
    "setup.py",
    "setup.cfg",
    "manage.py",
)


def _check_syspath_manipulation(ctx: RuleContext) -> None:
    """
    Detect sys.path.append/insert/extend and sys.path += [...] calls.

    Migrated from CK-PY-SYSPATH.  Extended to also cover
    ``sys.path.extend()``, ``sys.path += [...]``, and
    ``sys.path = sys.path + [...]`` patterns.

    Test files, conftest.py, setup.py, and manage.py are exempt by default.
    """
    name = "syspath_manipulation"
    if not _enabled(ctx, name, default=True):
        return
    if ctx.language != "python":
        return
    if "sys.path" not in ctx.content:
        return

    # Exemptions
    if ctx.is_test:
        return
    fname = ctx.file_path.name
    exempt = rule_config(ctx, name).get("exempt_files", _SYSPATH_EXEMPT_PATTERNS)
    if fname in exempt:
        return

    severity = _severity(ctx, name, default="warning")

    for i, line in enumerate(ctx.lines, 1):
        matched = (
            _SYSPATH_RE.search(line)
            or _SYSPATH_IADD_RE.search(line)
            or _SYSPATH_ASSIGN_RE.search(line)
        )
        if not matched:
            continue
        ctx.add_issue(
            file=str(ctx.file_path),
            line=i,
            rule=name,
            severity=severity,
            message="sys.path manipulation detected. Increases import ambiguity and causes environment-specific bugs.",
            snippet=line.strip()[:120],
            suggestion="Prefer proper packaging (pyproject.toml/setup.py), module layout, or stable API boundaries.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def _parse_tree(ctx: RuleContext) -> ast.AST | None:
    if ctx.language != "python":
        return None
    try:
        return ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return None


def _attr_chain(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_chain(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 3. mutable_default_argument
# ═══════════════════════════════════════════════════════════════════════════

_MUTABLE_DEFAULT_CALLS = frozenset({
    "uuid4", "uuid.uuid4", "datetime.now", "datetime.utcnow",
    "datetime.datetime.now", "datetime.datetime.utcnow",
    "date.today", "datetime.date.today",
    "time.time", "dict", "list", "set", "bytearray",
})


def _check_mutable_default_argument(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag mutable or call-time defaults in function definitions.

    Catches: def f(x=[], y={}, t=datetime.now(), id=uuid4()).
    Python evaluates defaults once at definition time — mutable defaults
    are shared across all calls, and call-time values are frozen.
    """
    name = "mutable_default_argument"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="error")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        all_defaults = list(node.args.defaults) + list(node.args.kw_defaults or [])

        for default in all_defaults:
            if default is None:
                continue
            lineno = getattr(default, "lineno", getattr(node, "lineno", 0))

            # Mutable literals: [], {}, set()
            if isinstance(default, ast.List):
                ctx.add_issue(
                    file=str(ctx.file_path), line=lineno, rule=name, severity=severity,
                    message=f"Mutable default argument [] in '{node.name}'. Shared across all calls.",
                    suggestion="Use None as default, then `x = x or []` in the body.",
                )
            elif isinstance(default, ast.Dict):
                ctx.add_issue(
                    file=str(ctx.file_path), line=lineno, rule=name, severity=severity,
                    message=f"Mutable default argument {{}} in '{node.name}'. Shared across all calls.",
                    suggestion="Use None as default, then `x = x or {{}}` in the body.",
                )
            elif isinstance(default, ast.Set):
                ctx.add_issue(
                    file=str(ctx.file_path), line=lineno, rule=name, severity=severity,
                    message=f"Mutable default argument set() in '{node.name}'. Shared across all calls.",
                    suggestion="Use None as default, then `x = x if x is not None else set()` in the body.",
                )
            elif isinstance(default, ast.Call):
                fn = _attr_chain(default.func)
                if fn in _MUTABLE_DEFAULT_CALLS:
                    ctx.add_issue(
                        file=str(ctx.file_path), line=lineno, rule=name, severity=severity,
                        message=(
                            f"Call-time default {fn}() in '{node.name}'. "
                            f"Evaluated once at definition, not per-call."
                        ),
                        suggestion=f"Use None as default and call {fn}() inside the function body.",
                    )


# ═══════════════════════════════════════════════════════════════════════════
# 4. cursor_double_consume
# ═══════════════════════════════════════════════════════════════════════════

_CONSUME_METHODS = frozenset({
    "one", "one_or_none", "first", "fetchone", "fetchall",
    "fetchmany", "scalar_one", "scalar_one_or_none", "scalars",
    "all",
})


def _check_cursor_double_consume(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag same variable consumed twice by cursor methods.

    Example: result.one() ... result.one() — second call returns None or raises.
    """
    name = "cursor_double_consume"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Track: variable_name -> list of (lineno, method) for consume calls
        consume_calls: dict[str, list[tuple[int, str]]] = {}

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue
            method = child.func.attr
            if method not in _CONSUME_METHODS:
                continue

            # Get the variable being consumed
            var = child.func.value
            if isinstance(var, ast.Name):
                var_name = var.id
            elif isinstance(var, ast.Attribute):
                var_name = _attr_chain(var)
            else:
                continue

            lineno = getattr(child, "lineno", 0)
            consume_calls.setdefault(var_name, []).append((lineno, method))

        # Report doubles
        for var_name, calls in consume_calls.items():
            if len(calls) >= 2:
                first_line, first_method = calls[0]
                second_line, second_method = calls[1]
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=second_line,
                    rule=name,
                    severity=severity,
                    message=(
                        f"Cursor '{var_name}' consumed twice: "
                        f".{first_method}() at line {first_line}, "
                        f".{second_method}() at line {second_line}. "
                        f"Second call will return None or raise."
                    ),
                    suggestion="Assign the first result to a variable and reuse it.",
                )


# ═══════════════════════════════════════════════════════════════════════════
# 5. empty_context_manager_exit
# ═══════════════════════════════════════════════════════════════════════════

def _check_empty_context_manager_exit(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag __exit__ methods whose body is only ``pass`` or ``return None``."""
    name = "empty_context_manager_exit"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name not in ("__exit__", "__aexit__"):
                continue

            # Filter out docstrings — only count real statements
            stmts = [
                s for s in item.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
            ]

            is_empty = False
            if len(stmts) == 0:
                is_empty = True
            elif len(stmts) == 1:
                s = stmts[0]
                if isinstance(s, ast.Pass):
                    is_empty = True
                elif isinstance(s, ast.Return):
                    if s.value is None or (isinstance(s.value, ast.Constant) and s.value.value is None):
                        is_empty = True
                elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                    is_empty = True  # lone Ellipsis or similar

            if is_empty:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=getattr(item, "lineno", 1),
                    rule=name,
                    severity=severity,
                    message=(
                        f"Context manager '{node.name}.{item.name}' has empty body. "
                        f"Resources acquired in __enter__ will never be cleaned up."
                    ),
                    suggestion="Implement proper cleanup: close connections, release locks, flush buffers.",
                )


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def check_python_patterns(ctx: RuleContext) -> None:
    """Run all Python-specific checks (python pack)."""
    _check_missing_requests_timeout(ctx)
    _check_syspath_manipulation(ctx)

    if ctx.language != "python":
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return
    _check_mutable_default_argument(ctx, tree)
    _check_cursor_double_consume(ctx, tree)
    _check_empty_context_manager_exit(ctx, tree)
