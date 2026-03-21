"""
FastAPI-Specific Code Quality Checks

Rules for the fastapi pack — targets Python files importing from fastapi.

Phase 1 rules:
1. sync_endpoint_with_io   (ERROR)  — Sync handler with blocking I/O
2. missing_response_model   (WARNING) — Route without response_model
3. dependency_creates_resource (WARNING) — Heavy resource in Depends()
4. unvalidated_parameters   (WARNING) — Path/Query without constraints
5. bare_exception_in_route  (ERROR)  — Silent except in handler
6. missing_cors_config      (WARNING) — No CORSMiddleware

Phase 2 rules:
7. error_response_as_200    (ERROR)  — Flask-style tuple return in FastAPI route
8. missing_auth_middleware   (WARNING) — Route handler without auth dependency
9. discarded_query_result    (ERROR)  — DB query expression without assignment
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
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════

def _attr_chain(node: ast.AST) -> str:
    """Reconstruct dotted attribute chain from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_chain(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _has_fastapi_imports(content: str) -> bool:
    return "fastapi" in content or "FastAPI" in content


def _parse_tree(ctx: RuleContext) -> ast.AST | None:
    if ctx.language != "python":
        return None
    try:
        return ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return None


# Route decorator prefixes that indicate a FastAPI endpoint
_ROUTE_DECORATOR_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
)

_BLOCKING_CALLS = {
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.patch", "requests.head", "requests.request",
    "httpx.get", "httpx.post", "httpx.put", "httpx.delete",
    "subprocess.run", "subprocess.call", "subprocess.check_output",
    "subprocess.check_call", "subprocess.Popen",
    "time.sleep", "os.system",
}
_BLOCKING_NAMES = frozenset({"open", "input", "sleep"})
_BLOCKING_ATTR_SUFFIXES = (".read_text", ".write_text", ".read_bytes", ".write_bytes")

# Response classes that don't need response_model
_RESPONSE_CLASSES = frozenset({
    "Response", "StreamingResponse", "FileResponse",
    "RedirectResponse", "HTMLResponse", "PlainTextResponse",
    "JSONResponse",
})

# Heavy resources that should not be created per-request
_HEAVY_RESOURCE_CALLS = frozenset({
    "create_engine", "create_async_engine",
    "MongoClient", "AsyncIOMotorClient",
    "AsyncClient",  # httpx.AsyncClient
    "ClientSession",  # aiohttp
    "GraphDatabase.driver", "AsyncGraphDatabase.driver",
})

# Parameter names that suggest constraints are needed
_CONSTRAINED_PARAM_NAMES = re.compile(
    r"^(id|.*_id|page|limit|offset|skip|size|count|email|date|"
    r"start|end|age|amount|price|quantity|port|year|month|day)$",
    re.IGNORECASE,
)


def _is_route_decorator(decorator: ast.AST) -> bool:
    """Check if a decorator is a FastAPI route decorator."""
    if isinstance(decorator, ast.Call):
        func = decorator.func
    elif isinstance(decorator, ast.Attribute):
        return decorator.attr in _ROUTE_DECORATOR_METHODS
    else:
        return False
    if isinstance(func, ast.Attribute):
        return func.attr in _ROUTE_DECORATOR_METHODS
    return False


def _get_route_decorator(node: ast.FunctionDef) -> ast.Call | None:
    """Return the route decorator Call node, or None."""
    for d in (node.decorator_list or []):
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
            if d.func.attr in _ROUTE_DECORATOR_METHODS:
                return d
        elif isinstance(d, ast.Attribute) and d.attr in _ROUTE_DECORATOR_METHODS:
            return None  # @app.get without parens — can't inspect kwargs
    return None


def _is_route_handler(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        _is_route_decorator(d) for d in (node.decorator_list or [])
    )


def _is_sync_function(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef) and not isinstance(node, ast.AsyncFunctionDef)


class _BlockingCallFinder(ast.NodeVisitor):
    """Walk a function body and collect blocking call sites."""

    def __init__(self) -> None:
        self.found: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        chain = _attr_chain(node.func)
        lineno = getattr(node, "lineno", 1)
        if chain in _BLOCKING_CALLS:
            self.found.append((lineno, chain))
        elif isinstance(node.func, ast.Name) and node.func.id in _BLOCKING_NAMES:
            self.found.append((lineno, node.func.id))
        elif chain and any(chain.endswith(s) for s in _BLOCKING_ATTR_SUFFIXES):
            self.found.append((lineno, chain))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass  # don't descend into nested defs

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 1. sync_endpoint_with_io
# ═══════════════════════════════════════════════════════════════════════════

def _check_sync_endpoint_with_io(ctx: RuleContext, tree: ast.AST) -> None:
    name = "sync_endpoint_with_io"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="error")

    for node in ast.walk(tree):
        if not _is_sync_function(node) or not _is_route_handler(node):
            continue
        finder = _BlockingCallFinder()
        for child in node.body:
            finder.visit(child)
        for lineno, callee in finder.found:
            ctx.add_issue(
                file=str(ctx.file_path),
                line=lineno,
                rule=name,
                severity=severity,
                message=(
                    f"Synchronous route handler '{node.name}' calls blocking "
                    f"'{callee}'. This blocks the FastAPI event loop."
                ),
                suggestion=(
                    "Make the handler async and use async equivalents "
                    "(httpx.AsyncClient, asyncio.to_thread, aiofiles, etc.), "
                    "or move blocking work to a background task."
                ),
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. missing_response_model
# ═══════════════════════════════════════════════════════════════════════════

def _check_missing_response_model(ctx: RuleContext, tree: ast.AST) -> None:
    """Route decorator without response_model and no return-type annotation."""
    name = "missing_response_model"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        deco = _get_route_decorator(node)
        if deco is None:
            continue

        # Check if response_model is among the decorator kwargs
        has_response_model = any(
            kw.arg == "response_model" for kw in (deco.keywords or [])
        )
        if has_response_model:
            continue

        # Check return annotation — if it references a known Response class, skip
        ret = node.returns
        if ret is not None:
            ret_name = _attr_chain(ret) if isinstance(ret, (ast.Name, ast.Attribute)) else ""
            if ret_name.split(".")[-1] in _RESPONSE_CLASSES:
                continue
            # Any return annotation is acceptable (could be a Pydantic model)
            if ret_name:
                continue

        ctx.add_issue(
            file=str(ctx.file_path),
            line=getattr(deco, "lineno", getattr(node, "lineno", 1)),
            rule=name,
            severity=severity,
            message=(
                f"Route handler '{node.name}' has no response_model and no "
                f"return type annotation. API contract is undocumented."
            ),
            suggestion=(
                "Add response_model= to the route decorator or add a return "
                "type annotation with a Pydantic model."
            ),
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. dependency_creates_resource
# ═══════════════════════════════════════════════════════════════════════════

def _check_dependency_creates_resource(ctx: RuleContext, tree: ast.AST) -> None:
    """Dependencies (Depends args) that instantiate heavy resources per-request."""
    name = "dependency_creates_resource"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    # Build a set of function names used as Depends() arguments
    depends_funcs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node.func)
        if chain != "Depends" and not chain.endswith(".Depends"):
            continue
        if node.args:
            arg = node.args[0]
            dep_name = _attr_chain(arg)
            if dep_name:
                depends_funcs.add(dep_name)

    if not depends_funcs:
        return

    # Check each dependency function for heavy resource creation
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in depends_funcs:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            callee = _attr_chain(child.func)
            short = callee.split(".")[-1] if callee else ""
            if short in _HEAVY_RESOURCE_CALLS or callee in _HEAVY_RESOURCE_CALLS:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=getattr(child, "lineno", getattr(node, "lineno", 1)),
                    rule=name,
                    severity=severity,
                    message=(
                        f"Dependency '{node.name}' creates '{callee}' per-request. "
                        f"This causes connection pool exhaustion under load."
                    ),
                    suggestion=(
                        "Create the resource at app lifespan level and inject "
                        "the shared instance via the dependency."
                    ),
                )
                break  # one finding per dependency function


# ═══════════════════════════════════════════════════════════════════════════
# 4. unvalidated_parameters
# ═══════════════════════════════════════════════════════════════════════════

def _check_unvalidated_parameters(ctx: RuleContext, tree: ast.AST) -> None:
    """Route handler params with suggestive names but no Field/Path/Query constraints."""
    name = "unvalidated_parameters"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_route_handler(node):
            continue

        args = node.args
        # Check positional and keyword-only args (skip self/cls)
        all_args = list(args.args) + list(args.kwonlyargs or [])
        defaults_map: dict[str, ast.AST | None] = {}
        # Map args to their defaults
        num_defaults = len(args.defaults)
        num_positional = len(args.args)
        for i, arg in enumerate(args.args):
            di = i - (num_positional - num_defaults)
            defaults_map[arg.arg] = args.defaults[di] if di >= 0 else None
        for i, arg in enumerate(args.kwonlyargs or []):
            kwd = (args.kw_defaults or [])
            defaults_map[arg.arg] = kwd[i] if i < len(kwd) else None

        for arg in all_args:
            pname = arg.arg
            if pname in ("self", "cls", "request", "response", "db", "session"):
                continue
            # Skip if it has a Depends() default
            default = defaults_map.get(pname)
            if default and isinstance(default, ast.Call):
                dc = _attr_chain(default.func)
                if "Depends" in dc or "Depends" == dc:
                    continue
                # Has a Path/Query/Body/Header/Cookie with kwargs → validated
                if dc in ("Path", "Query", "Body", "Header", "Cookie") or dc.endswith(
                    (".Path", ".Query", ".Body", ".Header", ".Cookie")
                ):
                    continue

            if not _CONSTRAINED_PARAM_NAMES.match(pname):
                continue

            # Check type annotation — bare str/int/float without default constraints
            ann = arg.annotation
            if ann is None:
                continue  # no annotation at all — different problem
            ann_name = ""
            if isinstance(ann, ast.Name):
                ann_name = ann.id
            elif isinstance(ann, ast.Attribute):
                ann_name = ann.attr
            if ann_name not in ("str", "int", "float"):
                continue  # complex type annotation — likely has validation

            ctx.add_issue(
                file=str(ctx.file_path),
                line=getattr(arg, "lineno", getattr(node, "lineno", 1)),
                rule=name,
                severity=severity,
                message=(
                    f"Parameter '{pname}' in route '{node.name}' is a bare "
                    f"{ann_name} without validation constraints."
                ),
                suggestion=(
                    f"Use {pname}: {ann_name} = Path(...) or Query(...) with "
                    f"constraints like ge=, le=, min_length=, pattern=."
                ),
            )


# ═══════════════════════════════════════════════════════════════════════════
# 5. bare_exception_in_route
# ═══════════════════════════════════════════════════════════════════════════

def _check_bare_exception_in_route(ctx: RuleContext, tree: ast.AST) -> None:
    """Except clauses in route handlers without logging."""
    name = "bare_exception_in_route"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="error")

    _LOG_CALLS = frozenset({
        "logger.error", "logger.exception", "logger.warning", "logger.critical",
        "logging.error", "logging.exception", "logging.warning", "logging.critical",
        "log.error", "log.exception", "log.warning", "log.critical",
    })

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_route_handler(node):
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.ExceptHandler):
                continue
            # Check if the except type is bare or catches Exception
            exc_type = child.type
            is_broad = exc_type is None  # bare except
            if isinstance(exc_type, ast.Name) and exc_type.id in ("Exception", "BaseException"):
                is_broad = True
            if not is_broad:
                continue

            # Check if any logging call exists in the handler body
            has_logging = False
            for stmt in ast.walk(child):
                if isinstance(stmt, ast.Call):
                    chain = _attr_chain(stmt.func)
                    if chain in _LOG_CALLS:
                        has_logging = True
                        break
            if has_logging:
                continue

            # Also check for raise (re-raise is acceptable)
            has_raise = any(isinstance(s, ast.Raise) for s in ast.walk(child))

            if not has_raise:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=getattr(child, "lineno", 1),
                    rule=name,
                    severity=severity,
                    message=(
                        f"Broad exception in route '{node.name}' with no logging "
                        f"and no re-raise. Failures will be invisible in production."
                    ),
                    suggestion=(
                        "Add logger.exception() and either re-raise or raise "
                        "HTTPException with appropriate status code."
                    ),
                )


# ═══════════════════════════════════════════════════════════════════════════
# 6. missing_cors_config
# ═══════════════════════════════════════════════════════════════════════════

def _check_missing_cors_config(ctx: RuleContext, tree: ast.AST) -> None:
    """Files with FastAPI() instantiation but no CORSMiddleware."""
    name = "missing_cors_config"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    # Only run on files that instantiate FastAPI()
    has_app_init = False
    app_line = 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = _attr_chain(node.func)
            if chain == "FastAPI":
                has_app_init = True
                app_line = getattr(node, "lineno", 1)
                break

    if not has_app_init:
        return

    has_cors = "CORSMiddleware" in ctx.content

    if not has_cors:
        ctx.add_issue(
            file=str(ctx.file_path),
            line=app_line,
            rule=name,
            severity=severity,
            message="FastAPI app created without CORSMiddleware. Frontend requests will be blocked.",
            suggestion=(
                "Add CORSMiddleware with explicit allow_origins from settings "
                "(not ['*'] in production)."
            ),
        )
        return

    # Check for wildcard origins
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node.func)
        if "add_middleware" not in chain:
            continue
        for kw in (node.keywords or []):
            if kw.arg != "allow_origins":
                continue
            if isinstance(kw.value, ast.List) and kw.value.elts:
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and elt.value == "*":
                        ctx.add_issue(
                            file=str(ctx.file_path),
                            line=getattr(node, "lineno", 1),
                            rule=name,
                            severity="error",
                            message=(
                                "CORSMiddleware with allow_origins=['*']. "
                                "This bypasses browser security in production."
                            ),
                            suggestion=(
                                "Use explicit origin list from settings: "
                                "allow_origins=settings.ALLOWED_ORIGINS"
                            ),
                        )


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def check_fastapi_patterns(ctx: RuleContext) -> None:
    """Run all FastAPI-specific checks (fastapi pack)."""
    if ctx.language != "python":
        return
    if not _has_fastapi_imports(ctx.content):
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_sync_endpoint_with_io(ctx, tree)
    _check_missing_response_model(ctx, tree)
    _check_dependency_creates_resource(ctx, tree)
    _check_unvalidated_parameters(ctx, tree)
    _check_bare_exception_in_route(ctx, tree)
    _check_missing_cors_config(ctx, tree)
    _check_error_response_as_200(ctx, tree)
    _check_missing_auth_middleware(ctx, tree)
    _check_discarded_query_result(ctx, tree)


# ═══════════════════════════════════════════════════════════════════════════
# 7. error_response_as_200
# ═══════════════════════════════════════════════════════════════════════════

def _check_error_response_as_200(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag Flask-style tuple returns (dict, status_code) in FastAPI routes.

    FastAPI serializes tuples as JSON arrays — the status code is ignored.
    ``return {"error": "msg"}, 400`` actually sends a 200 with ``[{...}, 400]``.
    """
    name = "error_response_as_200"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="error")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_route_handler(node):
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.Return) or child.value is None:
                continue
            val = child.value
            # return (dict, int) — tuple pattern
            if isinstance(val, ast.Tuple) and len(val.elts) == 2:
                first, second = val.elts
                is_dict = isinstance(first, ast.Dict)
                is_int = isinstance(second, ast.Constant) and isinstance(second.value, int)
                if is_dict and is_int:
                    ctx.add_issue(
                        file=str(ctx.file_path),
                        line=getattr(child, "lineno", 1),
                        rule=name,
                        severity=severity,
                        message=(
                            f"Flask-style tuple return in FastAPI route '{node.name}'. "
                            f"Status code {second.value} will be ignored — "
                            f"FastAPI sends 200 with the tuple serialized as a JSON array."
                        ),
                        suggestion=(
                            "Use raise HTTPException(status_code={0}, detail=...) or "
                            "return JSONResponse(content=..., status_code={0}).".format(second.value)
                        ),
                    )


# ═══════════════════════════════════════════════════════════════════════════
# 8. missing_auth_middleware
# ═══════════════════════════════════════════════════════════════════════════

_AUTH_SIGNALS = frozenset({
    "Depends", "Security", "OAuth2PasswordBearer", "HTTPBearer",
    "HTTPBasic", "APIKeyHeader", "APIKeyCookie", "APIKeyQuery",
    "get_current_user", "verify_token", "auth", "authenticate",
    "require_auth", "login_required", "jwt_required",
})

_EXEMPT_ROUTES_DEFAULT = frozenset({
    "health", "healthz", "health_check", "ready", "readyz",
    "ping", "root", "docs", "redoc", "openapi",
    "login", "signup", "register", "callback",
})


def _check_missing_auth_middleware(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag route handlers without any auth dependency or decorator."""
    name = "missing_auth_middleware"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    cfg = rule_config(ctx, name)
    exempt_names = set(cfg.get("exempt_routes", _EXEMPT_ROUTES_DEFAULT))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_route_handler(node):
            continue

        # Skip exempt routes (health, login, etc.)
        if node.name.lower() in exempt_names:
            continue

        # Check if any auth signal appears in the function's AST dump
        func_source = ast.dump(node)
        has_auth = any(sig in func_source for sig in _AUTH_SIGNALS)

        if has_auth:
            continue

        # Also check decorator kwargs for dependencies
        deco = _get_route_decorator(node)
        if deco:
            for kw in (deco.keywords or []):
                if kw.arg == "dependencies":
                    has_auth = True
                    break

        if has_auth:
            continue

        ctx.add_issue(
            file=str(ctx.file_path),
            line=getattr(node, "lineno", 1),
            rule=name,
            severity=severity,
            message=(
                f"Route handler '{node.name}' has no authentication dependency. "
                f"Endpoint is publicly accessible."
            ),
            suggestion=(
                "Add an auth dependency: async def {0}(..., user=Depends(get_current_user)). "
                "If intentionally public, add '{0}' to exempt_routes in config.".format(node.name)
            ),
        )


# ═══════════════════════════════════════════════════════════════════════════
# 9. discarded_query_result
# ═══════════════════════════════════════════════════════════════════════════

_DB_CALL_METHODS = frozenset({
    "find", "find_one", "find_many", "execute", "query", "all",
    "scalars", "scalar_one", "scalar_one_or_none", "first",
    "one", "one_or_none", "fetchone", "fetchall", "fetchmany",
    "aggregate", "count_documents",
})


def _check_discarded_query_result(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag bare DB query expressions (result not assigned or returned)."""
    name = "discarded_query_result"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="error")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_route_handler(node):
            continue

        for child in ast.iter_child_nodes(node):
            # Only care about expression statements (Expr) — assignments are fine
            if not isinstance(child, ast.Expr):
                continue
            expr = child.value
            # Unwrap await
            if isinstance(expr, ast.Await):
                expr = expr.value
            if not isinstance(expr, ast.Call):
                continue
            if not isinstance(expr.func, ast.Attribute):
                continue
            if expr.func.attr in _DB_CALL_METHODS:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=getattr(child, "lineno", 1),
                    rule=name,
                    severity=severity,
                    message=(
                        f"Query result from .{expr.func.attr}() is discarded in "
                        f"route '{node.name}'. The handler likely returns None/empty."
                    ),
                    suggestion=(
                        f"Assign the result: result = .{expr.func.attr}() and "
                        f"return it, or remove the dead query call."
                    ),
                )
