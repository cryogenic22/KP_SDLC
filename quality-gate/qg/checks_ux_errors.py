"""UX error handling pack — 3 rules.

Rules:
  generic_error_response       WARNING  Route returning generic error dict without status code
  missing_error_boundary       WARNING  React component tree without ErrorBoundary (TS/JS)
  unhandled_promise_rejection  WARNING  .then() without .catch(), await without try/catch (TS/JS)
"""
from __future__ import annotations

import ast
import re

from qg.context import RuleContext, rule_config


# ── helpers ────────────────────────────────────────────────────────

def _enabled(ctx: RuleContext, rule: str) -> bool:
    cfg = rule_config(ctx, rule)
    return cfg.get("enabled", True) is not False


def _severity(ctx: RuleContext, rule: str, default: str) -> str:
    cfg = rule_config(ctx, rule)
    return str(cfg.get("severity", default)).lower()


def _parse_tree(ctx: RuleContext) -> ast.Module | None:
    try:
        return ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return None


def _attr_chain(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attr_chain(node.value)}.{node.attr}"
    return ""


_ROUTE_DECORATORS = {"get", "post", "put", "delete", "patch", "head", "options", "api_route", "route"}


def _is_route_handler(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in (node.decorator_list or []):
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            if dec.func.attr in _ROUTE_DECORATORS:
                return True
        elif isinstance(dec, ast.Attribute) and dec.attr in _ROUTE_DECORATORS:
            return True
    return False


# ── public entry point ─────────────────────────────────────────────

def check_ux_error_patterns(ctx: RuleContext) -> None:
    if ctx.language == "python":
        tree = _parse_tree(ctx)
        if tree is not None:
            _check_generic_error_response(ctx, tree)
    elif ctx.language in ("typescript", "javascript"):
        _check_missing_error_boundary(ctx)
        _check_unhandled_promise_rejection(ctx)


# ── rule implementations ──────────────────────────────────────────

def _check_generic_error_response(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag route handlers returning generic error dicts like {"error": str(e)}.

    These give users/UI no actionable information — no status code, no error type,
    no correlation ID.
    """
    rule = "generic_error_response"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not _is_route_handler(node):
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.ExceptHandler):
                continue

            # Look for return {"error": ...} or return {"message": ...} in except blocks
            for stmt in ast.walk(child):
                if not isinstance(stmt, ast.Return) or stmt.value is None:
                    continue
                val = stmt.value

                if not isinstance(val, ast.Dict):
                    continue

                # Check if keys are generic error keys
                key_names = []
                for k in val.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        key_names.append(k.value.lower())

                generic_keys = {"error", "message", "detail", "msg"}
                if not (set(key_names) & generic_keys):
                    continue

                # Check if it lacks status_code, error_code, or error_type keys
                structured_keys = {"status_code", "error_code", "error_type", "code", "type", "status"}
                if set(key_names) & structured_keys:
                    continue

                ctx.add_issue(
                    line=getattr(stmt, "lineno", getattr(child, "lineno", 0)),
                    rule=rule,
                    severity=sev,
                    message=(
                        f"Generic error response in route '{node.name}': "
                        f"keys {key_names}. No error type or status code for the UI to parse."
                    ),
                    suggestion=(
                        "Use HTTPException(status_code=..., detail=...) or return a structured "
                        "error with {\"error_code\": \"...\", \"message\": \"...\", \"status\": ...}."
                    ),
                )
                return  # one per route


# ── JS/TS rules (regex-based) ──────────────────────────────────────

_ERROR_BOUNDARY_RE = re.compile(
    r"(?:ErrorBoundary|error\s*boundary|componentDidCatch|getDerivedStateFromError)",
    re.IGNORECASE,
)

_COMPONENT_RENDER_RE = re.compile(
    r"(?:(?:function|const|let|var)\s+\w+.*(?:=>|return)\s*(?:\(?\s*<)|class\s+\w+\s+extends\s+(?:React\.)?Component)",
)


def _check_missing_error_boundary(ctx: RuleContext) -> None:
    """Flag React component files without ErrorBoundary usage.

    Only triggers on files that render JSX components but have no error
    boundary wrapper or componentDidCatch.
    """
    rule = "missing_error_boundary"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    # Only check .tsx/.jsx files
    suffix = ctx.file_path.suffix.lower()
    if suffix not in (".tsx", ".jsx"):
        return

    if ctx.is_test:
        return

    # Must have JSX rendering
    has_jsx = bool(re.search(r"return\s*\(?\s*<", ctx.content))
    if not has_jsx:
        return

    # Skip if file defines or uses an ErrorBoundary
    if _ERROR_BOUNDARY_RE.search(ctx.content):
        return

    # Skip small utility components (< 30 lines)
    if len(ctx.lines) < 30:
        return

    ctx.add_issue(
        line=1,
        rule=rule,
        severity=sev,
        message="React component file without ErrorBoundary. Any render error will crash the entire component tree.",
        suggestion="Wrap the component tree with <ErrorBoundary fallback={<ErrorFallback />}> to handle render errors gracefully.",
    )


_THEN_WITHOUT_CATCH_RE = re.compile(
    r"\.then\s*\([^)]*\)\s*(?:;|\n|$)(?![\s\S]*?\.catch)",
)

_ASYNC_HANDLER_RE = re.compile(
    r"(?:on\w+|handle\w+)\s*=\s*async\s+(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>\s*\{",
)


def _check_unhandled_promise_rejection(ctx: RuleContext) -> None:
    """Flag .then() without .catch() and async event handlers without try/catch.

    Unhandled promise rejections in UI code cause silent failures — the user
    sees nothing while the operation fails.
    """
    rule = "unhandled_promise_rejection"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    suffix = ctx.file_path.suffix.lower()
    if suffix not in (".ts", ".tsx", ".js", ".jsx"):
        return

    if ctx.is_test:
        return

    # Check for .then() without .catch() on the same chain
    for i, line in enumerate(ctx.lines, 1):
        stripped = line.strip()
        if ".then(" in stripped and ".catch(" not in stripped:
            # Look ahead a few lines for .catch()
            lookahead = "\n".join(ctx.lines[i - 1: min(len(ctx.lines), i + 3)])
            if ".catch(" not in lookahead and ".finally(" not in lookahead:
                # Skip if wrapped in try/catch — check 5 lines above
                lookbehind = "\n".join(ctx.lines[max(0, i - 6): i - 1])
                if "try" in lookbehind and "{" in lookbehind:
                    continue
                ctx.add_issue(
                    line=i,
                    rule=rule,
                    severity=sev,
                    message="Promise .then() without .catch() — unhandled rejection will fail silently in the UI.",
                    snippet=stripped[:120],
                    suggestion="Add .catch(err => handleError(err)) or use async/await with try/catch.",
                )
                return  # one per file

    # Check for async event handlers without try/catch
    for i, line in enumerate(ctx.lines, 1):
        if _ASYNC_HANDLER_RE.search(line):
            # Look ahead for try { in the handler body
            lookahead = "\n".join(ctx.lines[i - 1: min(len(ctx.lines), i + 8)])
            if "try" not in lookahead:
                ctx.add_issue(
                    line=i,
                    rule=rule,
                    severity=sev,
                    message="Async event handler without try/catch. Errors will be unhandled promise rejections.",
                    snippet=line.strip()[:120],
                    suggestion="Wrap the handler body in try/catch and show user-facing error feedback.",
                )
                return
