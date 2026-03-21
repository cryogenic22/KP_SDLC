"""Performance pack — 8 cross-cutting rules.

Rules:
  db_call_in_loop              ERROR    DB query inside for/async-for loop (N+1)
  missing_pagination           WARNING  Route returning query results without limit/offset
  ssrf_potential               ERROR    User-supplied URL passed to HTTP client without validation
  nested_collection_iteration  WARNING  Nested for-loops over collections (O(n*m) risk)
  string_concat_in_loop        WARNING  String += inside loop (quadratic allocation)
  regex_compile_in_loop        WARNING  re.search/match/sub inside loop (recompilation each pass)
  unbounded_polling_loop       ERROR    while True + HTTP/sleep without max retries
  large_response_materialization WARNING list(queryset) or .all() in route without pagination
"""
from __future__ import annotations

import ast
import re
from typing import Any

from qg.context import RuleContext, rule_config

# ── helpers ────────────────────────────────────────────────────────

_DB_CALL_METHODS = {
    "execute", "query", "find", "find_one", "run",
    "execute_read", "execute_write", "aggregate",
}

_HTTP_CALL_METHODS = {
    "get", "post", "put", "delete", "patch", "head",
    "request", "urlopen", "fetch",
}

_ROUTE_DECORATORS = {"get", "post", "put", "delete", "patch", "head", "options", "api_route", "route"}


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


def _is_route_decorator(dec: ast.expr) -> bool:
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Attribute):
        return dec.attr in _ROUTE_DECORATORS
    return False


def _is_route_handler(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(_is_route_decorator(d) for d in node.decorator_list)


# ── public entry point ─────────────────────────────────────────────

def check_performance_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_db_call_in_loop(ctx, tree)
    _check_missing_pagination(ctx, tree)
    _check_ssrf_potential(ctx, tree)
    _check_nested_collection_iteration(ctx, tree)
    _check_string_concat_in_loop(ctx, tree)
    _check_regex_compile_in_loop(ctx, tree)
    _check_unbounded_polling_loop(ctx, tree)
    _check_large_response_materialization(ctx, tree)


# ── rule implementations ──────────────────────────────────────────

def _check_db_call_in_loop(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag database calls inside for/async-for loops (N+1 pattern)."""
    rule = "db_call_in_loop"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    def _walk_for_db_calls(loop_node: ast.AST) -> None:
        for child in ast.walk(loop_node):
            if child is loop_node:
                continue
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr in _DB_CALL_METHODS:
                ctx.add_issue(
                    line=getattr(child, "lineno", getattr(loop_node, "lineno", 0)),
                    rule=rule,
                    severity=sev,
                    message=f"Database call .{child.func.attr}() inside loop. N+1 query pattern — batch instead.",
                    suggestion="Use bulk/batch query (e.g., WHERE id IN $ids, $in operator, or batch API).",
                )

    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            _walk_for_db_calls(node)


def _check_missing_pagination(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag route handlers returning DB results without pagination params."""
    rule = "missing_pagination"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not _is_route_handler(node):
            continue

        # Check if function has limit/offset/page params
        param_names = {a.arg for a in node.args.args}
        has_pagination = bool(param_names & {"limit", "offset", "page", "page_size", "cursor", "skip"})
        if has_pagination:
            continue

        # Check if body contains list-returning DB calls
        has_list_query = False
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                if child.func.attr in ("find", "execute", "query", "all", "run"):
                    has_list_query = True
                    break

        if not has_list_query:
            continue

        # Check if there's an explicit .limit() in the function
        has_limit = False
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                if child.func.attr in ("limit", "slice"):
                    has_limit = True
                    break

        if has_limit:
            continue

        ctx.add_issue(
            line=getattr(node, "lineno", 0),
            rule=rule,
            severity=sev,
            message=f"Route handler '{node.name}' returns DB results without pagination parameters.",
            suggestion="Add limit/offset parameters: limit: int = Query(20, le=100), offset: int = Query(0, ge=0)",
        )


def _check_ssrf_potential(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag user-controlled URLs passed to HTTP clients without validation."""
    rule = "ssrf_potential"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        if not _is_route_handler(node):
            continue

        # Collect parameter names (potential user input)
        param_names = {a.arg for a in node.args.args} - {"self", "cls"}

        if not param_names:
            continue

        # Look for HTTP calls using those parameter names
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue

            method = child.func.attr
            if method not in _HTTP_CALL_METHODS:
                continue

            # Check if the URL argument references a param
            url_arg = child.args[0] if child.args else None
            if url_arg is None:
                for kw in child.keywords:
                    if kw.arg == "url":
                        url_arg = kw.value
                        break

            if url_arg is None:
                continue

            # Check if url_arg is a Name that matches a route param
            used_params: set[str] = set()
            for name_node in ast.walk(url_arg):
                if isinstance(name_node, ast.Name) and name_node.id in param_names:
                    used_params.add(name_node.id)

            if not used_params:
                continue

            # Check if there's URL validation before the call
            # Simple heuristic: look for "is_allowed" or "validate" calls in function
            has_validation = False
            func_source = ast.dump(node)
            if any(v in func_source for v in ("is_allowed", "validate_url", "allowlist", "allowed_domain")):
                has_validation = True

            if has_validation:
                continue

            ctx.add_issue(
                line=getattr(child, "lineno", getattr(node, "lineno", 0)),
                rule=rule,
                severity=sev,
                message=f"SSRF risk: user input ({', '.join(used_params)}) passed to HTTP call without URL validation.",
                suggestion="Validate URLs against an allowlist before making requests.",
            )


# ── performance-risk rules ───────────────────────────────────────

_RE_METHODS = {"search", "match", "sub", "findall", "finditer", "fullmatch", "split", "subn"}


def _check_nested_collection_iteration(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag nested for-loops over collections — O(n*m) risk."""
    rule = "nested_collection_iteration"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor)):
            continue
        # Look for nested for-loops inside this loop's body
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, (ast.For, ast.AsyncFor)):
                # Skip if inner loop has a break (likely bounded search)
                has_break = any(isinstance(n, ast.Break) for n in ast.walk(child))
                if has_break:
                    continue
                ctx.add_issue(
                    line=getattr(child, "lineno", getattr(node, "lineno", 0)),
                    rule=rule,
                    severity=sev,
                    message="Nested iteration over collections — O(n*m) complexity. Will degrade with data size.",
                    suggestion="Consider using a dict/set lookup, index, or batch operation to avoid quadratic iteration.",
                )


def _check_string_concat_in_loop(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag string += inside a loop (quadratic memory allocation)."""
    rule = "string_concat_in_loop"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for child in ast.walk(node):
            if child is node:
                continue
            # AugAssign with += on a Name target (likely string concat)
            if isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
                if isinstance(child.target, ast.Name):
                    # Check if RHS involves str() or is a string constant/f-string
                    rhs = child.value
                    is_str_concat = (
                        isinstance(rhs, (ast.Constant, ast.JoinedStr))
                        or (isinstance(rhs, ast.Call) and _attr_chain(rhs.func) in ("str", "repr", "format"))
                        or isinstance(rhs, ast.BinOp)
                    )
                    if is_str_concat:
                        ctx.add_issue(
                            line=getattr(child, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message=f"String concatenation (+=) inside loop on '{child.target.id}'. Quadratic memory allocation.",
                            suggestion="Collect parts in a list and use ''.join(parts) after the loop.",
                        )


def _check_regex_compile_in_loop(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag re.search/match/sub called inside loops (recompiles pattern each pass)."""
    rule = "regex_compile_in_loop"
    if not _enabled(ctx, rule):
        return
    if "re." not in ctx.content:
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for child in ast.walk(node):
            if child is node:
                continue
            if not isinstance(child, ast.Call):
                continue
            fn = _attr_chain(child.func)
            parts = fn.split(".")
            if len(parts) == 2 and parts[0] == "re" and parts[1] in _RE_METHODS:
                ctx.add_issue(
                    line=getattr(child, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message=f"re.{parts[1]}() called inside loop — pattern is recompiled every iteration.",
                    suggestion="Move re.compile(pattern) outside the loop and call compiled_re.{0}() instead.".format(parts[1]),
                )


def _check_unbounded_polling_loop(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag while True loops with HTTP/sleep but no counter or max-retry."""
    rule = "unbounded_polling_loop"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        # Check if it's ``while True``
        if not (isinstance(node.test, ast.Constant) and node.test.value is True):
            continue

        has_external_call = False
        has_counter = False

        for child in ast.walk(node):
            if child is node:
                continue
            # Check for HTTP/sleep calls
            if isinstance(child, ast.Call):
                fn = _attr_chain(child.func)
                if any(fn.endswith(m) for m in (".sleep", ".get", ".post", ".put", ".request", ".fetch")):
                    has_external_call = True
            # Check for counter increment (i += 1, count += 1, retries += 1)
            if isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
                has_counter = True
            # Check for comparison that could serve as a bound (if retries > max)
            if isinstance(child, ast.Compare):
                has_counter = True

        if has_external_call and not has_counter:
            ctx.add_issue(
                line=getattr(node, "lineno", 0),
                rule=rule,
                severity=sev,
                message="Unbounded polling loop (while True) with external calls and no retry counter.",
                suggestion="Add a max_retries counter and break after the limit. Consider exponential backoff.",
            )


def _check_large_response_materialization(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag list(queryset) or .all() in route handlers without pagination."""
    rule = "large_response_materialization"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not _is_route_handler(node):
            continue

        # Check if handler already has pagination params
        param_names = {a.arg for a in node.args.args}
        if param_names & {"limit", "offset", "page", "page_size", "cursor", "skip"}:
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            fn = _attr_chain(child.func)
            # list(something) wrapping a query
            if fn == "list" and child.args:
                inner = child.args[0]
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                    if inner.func.attr in _DB_CALL_METHODS | {"all", "select", "filter"}:
                        ctx.add_issue(
                            line=getattr(child, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message="Entire query result materialized with list() in route handler without pagination.",
                            suggestion="Add limit/offset pagination or use streaming/cursor-based iteration.",
                        )
            # .all() call on a query object
            if isinstance(child.func, ast.Attribute) and child.func.attr == "all":
                ctx.add_issue(
                    line=getattr(child, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message=".all() in route handler loads entire dataset into memory.",
                    suggestion="Add .limit()/.offset() or pagination params to bound the result set.",
                )
