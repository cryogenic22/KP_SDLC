"""Cross-cutting database rules — 5 rules applying to all database technologies.

Rules:
  connection_string_in_code   ERROR   Hardcoded DB URIs in source
  per_request_connection      ERROR   DB client created inside route handler
  missing_connection_retry    WARNING DB init without retry/try-except
  mixed_sync_async_drivers    WARNING Sync + async driver for same DB
  missing_health_check        INFO    No /health endpoint with DB ping
"""
from __future__ import annotations

import ast
import re
from typing import Any

from qg.context import RuleContext, rule_config

# ── helpers ────────────────────────────────────────────────────────

_DB_URI_PATTERNS = [
    re.compile(r"""(?:bolt|neo4j|neo4j\+s|neo4j\+ssc)://[^\s'"]+"""),
    re.compile(r"""(?:mongodb|mongodb\+srv)://[^\s'"]+"""),
    re.compile(r"""(?:postgresql|postgres|mysql|mysql\+pymysql)://[^\s'"]+"""),
    re.compile(r"""redis://[^\s'"]+"""),
]

_HEAVY_CONSTRUCTORS = {
    "MongoClient", "AsyncIOMotorClient",
    "GraphDatabase", "AsyncGraphDatabase",
    "create_engine", "create_async_engine",
    "Redis",
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


def _is_route_decorator(dec: ast.expr) -> bool:
    """Check if a decorator is a route decorator (app.get, router.post, etc.)."""
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Attribute):
        return dec.attr in _ROUTE_DECORATORS
    return False


def _attr_chain(node: ast.expr) -> str:
    """Build dotted attribute string from AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attr_chain(node.value)}.{node.attr}"
    return ""


# ── public entry point ─────────────────────────────────────────────

def check_database_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return

    _check_connection_string_in_code(ctx)

    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_per_request_connection(ctx, tree)
    _check_missing_connection_retry(ctx, tree)
    # mixed_sync_async_drivers and missing_health_check are cross-file;
    # we check per-file signals here.
    _check_mixed_sync_async_signals(ctx, tree)
    _check_missing_health_check(ctx, tree)


# ── rule implementations ──────────────────────────────────────────

def _check_connection_string_in_code(ctx: RuleContext) -> None:
    """Flag hardcoded database connection URIs."""
    rule = "connection_string_in_code"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    # Exempt test files and .env templates
    if ctx.is_test:
        return
    name_lower = ctx.file_path.name.lower()
    if name_lower in (".env", ".env.example", ".env.template"):
        return

    for i, line in enumerate(ctx.lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for pat in _DB_URI_PATTERNS:
            m = pat.search(line)
            if m:
                uri_text = m.group(0)
                # Exempt placeholder values
                if any(p in uri_text.lower() for p in ("localhost", "127.0.0.1", "example.com", "placeholder", "{", "$")):
                    continue
                ctx.add_issue(
                    line=i,
                    rule=rule,
                    severity=sev,
                    message=f"Hardcoded database connection string found: {uri_text[:40]}...",
                    suggestion="Use environment variables: os.environ['DATABASE_URL']",
                )
                break  # one per line


def _check_per_request_connection(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag DB client instantiation inside route handlers or Depends() functions."""
    rule = "per_request_connection"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        is_route = any(_is_route_decorator(d) for d in node.decorator_list)
        if not is_route:
            continue

        # Walk function body for DB constructor calls
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            call_name = _attr_chain(child.func)
            # Check if any heavy constructor is in the call chain
            for ctor in _HEAVY_CONSTRUCTORS:
                if ctor in call_name:
                    ctx.add_issue(
                        line=getattr(child, "lineno", getattr(node, "lineno", 0)),
                        rule=rule,
                        severity=sev,
                        message=f"Database connection ({ctor}) created inside route handler. Creates new connection per request.",
                        suggestion="Create connections at application startup/lifespan and inject via Depends().",
                    )
                    break


def _check_missing_connection_retry(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag DB driver init without try/except or retry decorator."""
    rule = "missing_connection_retry"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    # Module-level calls to heavy constructors
    retry_decorators = {"retry", "on_exception", "retrying"}

    for node in tree.body:
        # Check module-level assignments
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Call):
                call_name = _attr_chain(node.value.func)
                if any(ctor in call_name for ctor in _HEAVY_CONSTRUCTORS):
                    ctx.add_issue(
                        line=getattr(node, "lineno", 0),
                        rule=rule,
                        severity=sev,
                        message=f"Database connection ({call_name}) at module level without retry or error handling.",
                        suggestion="Wrap in try/except with retry logic, or use tenacity @retry decorator.",
                    )
        # Check functions that create connections
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_retry_dec = any(
                (_attr_chain(d.func) if isinstance(d, ast.Call) else _attr_chain(d))
                .split(".")[-1] in retry_decorators
                for d in node.decorator_list
            )
            if has_retry_dec:
                continue

            has_try = any(isinstance(c, ast.Try) for c in ast.walk(node))
            has_db_call = False
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    cn = _attr_chain(child.func)
                    if any(ctor in cn for ctor in _HEAVY_CONSTRUCTORS):
                        has_db_call = True
                        break

            if has_db_call and not has_try:
                ctx.add_issue(
                    line=getattr(node, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message=f"Function '{node.name}' creates DB connection without retry or error handling.",
                    suggestion="Add try/except with retry logic for transient connection failures.",
                )


def _check_mixed_sync_async_signals(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag per-file signals of mixed sync/async driver usage."""
    rule = "mixed_sync_async_drivers"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    sync_drivers: list[tuple[str, int]] = []
    async_drivers: list[tuple[str, int]] = []

    sync_markers = {"MongoClient", "GraphDatabase", "Session", "Redis"}
    async_markers = {"AsyncIOMotorClient", "AsyncGraphDatabase", "AsyncSession", "asyncio"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            line = getattr(node, "lineno", 0)
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [a.name for a in (node.names or [])]
                mod = node.module or ""
                if "asyncio" in mod or "async" in mod.lower():
                    for n in names:
                        async_drivers.append((n, line))
                    continue
            else:
                names = [a.name for a in (node.names or [])]

            for n in names:
                if n in sync_markers:
                    sync_drivers.append((n, line))
                elif n in async_markers:
                    async_drivers.append((n, line))

    if sync_drivers and async_drivers:
        sync_names = ", ".join(n for n, _ in sync_drivers[:3])
        async_names = ", ".join(n for n, _ in async_drivers[:3])
        ctx.add_issue(
            line=sync_drivers[0][1],
            rule=rule,
            severity=sev,
            message=f"Mixed sync ({sync_names}) and async ({async_names}) database drivers in same file.",
            suggestion="Use async drivers uniformly in async applications.",
        )


def _check_missing_health_check(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag if file has FastAPI app but no health endpoint."""
    rule = "missing_health_check"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    # Only check in files that instantiate FastAPI()
    has_fastapi_app = False
    has_health_route = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _attr_chain(node.func)
            if name == "FastAPI":
                has_fastapi_app = True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                call_node = dec if isinstance(dec, ast.Call) else None
                if call_node and call_node.args:
                    first_arg = call_node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        if "health" in first_arg.value.lower():
                            has_health_route = True

    # Also check for has_db_import
    has_db = bool(re.search(
        r"(?:from|import)\s+(?:pymongo|motor|neo4j|sqlalchemy|redis)",
        ctx.content,
    ))

    if has_fastapi_app and has_db and not has_health_route:
        ctx.add_issue(
            line=1,
            rule=rule,
            severity=sev,
            message="FastAPI app uses database but has no /health endpoint for connectivity checks.",
            suggestion='Add: @app.get("/health") async def health(): ...',
        )
