"""SQLAlchemy technology pack — 7 rules targeting ORM misuse.

Rules:
  sync_session_in_async     ERROR    Sync Session in async code
  missing_pool_config       WARNING  create_engine() without pool settings
  raw_sql_preference        INFO     session.execute(text(...)) for simple CRUD
  n_plus_one_signal         WARNING  DB query inside loop over query results
  missing_alembic           WARNING  SQLAlchemy models without alembic/ directory
  sync_orm_in_async_handler ERROR    Sync ORM ops (.commit/.execute/.query) in async function
  unsafe_module_singleton   WARNING  Module-level class with mutable state (thread-unsafe)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from qg.context import RuleContext, rule_config

# ── helpers ────────────────────────────────────────────────────────

_SA_IMPORT_PAT = re.compile(r"(?:from|import)\s+sqlalchemy")


def _has_sa_imports(content: str) -> bool:
    return bool(_SA_IMPORT_PAT.search(content))


def _parse_tree(ctx: RuleContext) -> ast.Module | None:
    try:
        return ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return None


def _enabled(ctx: RuleContext, rule: str) -> bool:
    cfg = rule_config(ctx, rule)
    return cfg.get("enabled", True) is not False


def _severity(ctx: RuleContext, rule: str, default: str) -> str:
    cfg = rule_config(ctx, rule)
    return str(cfg.get("severity", default)).lower()


def _attr_chain(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attr_chain(node.value)}.{node.attr}"
    return ""


# ── public entry point ─────────────────────────────────────────────

def check_sqlalchemy_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return
    if not _has_sa_imports(ctx.content):
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_sync_session_in_async(ctx, tree)
    _check_missing_pool_config(ctx, tree)
    _check_raw_sql_preference(ctx, tree)
    _check_n_plus_one_signal(ctx, tree)
    _check_missing_alembic(ctx, tree)
    _check_sync_orm_in_async_handler(ctx, tree)
    _check_unsafe_module_singleton(ctx, tree)


# ── rule implementations ──────────────────────────────────────────

def _check_sync_session_in_async(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag sync Session import in files with async functions."""
    rule = "sync_session_in_async"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    has_async = any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree))
    if not has_async:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if "sqlalchemy" in mod and "async" not in mod.lower():
                for alias in (node.names or []):
                    if alias.name == "Session":
                        ctx.add_issue(
                            line=getattr(node, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message="Synchronous sqlalchemy.orm.Session in file with async functions. Use AsyncSession.",
                            suggestion="from sqlalchemy.ext.asyncio import AsyncSession",
                        )


def _check_missing_pool_config(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag create_engine/create_async_engine without pool settings."""
    rule = "missing_pool_config"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    pool_kwargs = {"pool_size", "max_overflow", "pool_pre_ping", "poolclass"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _attr_chain(node.func)
        if name not in ("create_engine", "create_async_engine"):
            continue

        kw_names = {kw.arg for kw in node.keywords if kw.arg}
        has_pool = bool(kw_names & pool_kwargs)
        if has_pool:
            continue

        ctx.add_issue(
            line=getattr(node, "lineno", 0),
            rule=rule,
            severity=sev,
            message=f"{name}() without pool configuration (pool_size, max_overflow, pool_pre_ping).",
            suggestion=f"{name}(url, pool_size=20, max_overflow=10, pool_pre_ping=True)",
        )


def _check_raw_sql_preference(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag session.execute(text(...)) for standard CRUD."""
    rule = "raw_sql_preference"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "execute":
            continue
        if not node.args:
            continue

        first_arg = node.args[0]
        # Check for text(...) call
        if isinstance(first_arg, ast.Call):
            fn = _attr_chain(first_arg.func)
            if fn == "text" and first_arg.args:
                sql_node = first_arg.args[0]
                if isinstance(sql_node, ast.Constant) and isinstance(sql_node.value, str):
                    sql = sql_node.value.strip().upper()
                    if any(sql.startswith(kw) for kw in ("SELECT", "INSERT", "UPDATE", "DELETE")):
                        ctx.add_issue(
                            line=getattr(node, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message="Raw SQL via text() for standard CRUD. Consider ORM query builder for type safety.",
                            suggestion="select(Model).where(Model.id == value) instead of text('SELECT ...')",
                        )


def _check_n_plus_one_signal(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag DB query calls inside loops iterating over query results."""
    rule = "n_plus_one_signal"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    db_methods = {"execute", "query", "all", "scalars", "scalar_one", "scalar_one_or_none"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor)):
            continue

        # Check if any child of the loop body makes a DB call
        for child in ast.walk(node):
            if child is node:
                continue
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr in db_methods:
                ctx.add_issue(
                    line=getattr(child, "lineno", getattr(node, "lineno", 0)),
                    rule=rule,
                    severity=sev,
                    message=f"Potential N+1 query: .{child.func.attr}() inside loop. Use eager loading or batch query.",
                    suggestion="Use selectinload/joinedload for relationships, or batch with WHERE IN.",
                )
                break  # one per loop


def _check_missing_alembic(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag if file defines SQLAlchemy models but project lacks alembic."""
    rule = "missing_alembic"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    # Check if this file defines ORM models (classes with Base/DeclarativeBase)
    has_model_class = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = _attr_chain(base)
                if name in ("Base", "DeclarativeBase") or "Base" in name:
                    has_model_class = True
                    break

    if not has_model_class:
        return

    # Check for alembic directory or alembic.ini
    project_root = ctx.file_path.parent
    # Walk up max 3 levels looking for alembic
    for _ in range(4):
        if (project_root / "alembic").is_dir() or (project_root / "alembic.ini").exists():
            return
        parent = project_root.parent
        if parent == project_root:
            break
        project_root = parent

    ctx.add_issue(
        line=1,
        rule=rule,
        severity=sev,
        message="SQLAlchemy models defined but no alembic/ directory found. Schema migrations not tracked.",
        suggestion="Run: alembic init alembic && alembic revision --autogenerate",
    )


# ── phase 2 rules ────────────────────────────────────────────────

_SYNC_ORM_METHODS = frozenset({
    "execute", "commit", "rollback", "flush", "refresh",
    "query", "add", "add_all", "delete", "merge", "close",
    "begin", "begin_nested",
})


def _check_sync_orm_in_async_handler(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag synchronous ORM calls (.commit, .execute, .query) inside async functions.

    Sync ORM operations block the event loop, defeating the purpose of async.
    """
    rule = "sync_orm_in_async_handler"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue
            method = child.func.attr
            if method not in _SYNC_ORM_METHODS:
                continue

            # Check if it's called on a session-like variable
            var = child.func.value
            var_name = ""
            if isinstance(var, ast.Name):
                var_name = var.id.lower()
            elif isinstance(var, ast.Attribute):
                var_name = var.attr.lower()

            session_signals = {"session", "db", "conn", "connection", "cursor", "engine"}
            if var_name and any(s in var_name for s in session_signals):
                # Verify it's not an awaited call (await session.execute is fine for AsyncSession)
                # Check parent — if this Call is inside an Await, it's async-compatible
                is_awaited = False
                for parent in ast.walk(node):
                    if isinstance(parent, ast.Await) and isinstance(parent.value, ast.Call):
                        if parent.value is child:
                            is_awaited = True
                            break

                if is_awaited:
                    continue

                ctx.add_issue(
                    line=getattr(child, "lineno", getattr(node, "lineno", 0)),
                    rule=rule,
                    severity=sev,
                    message=(
                        f"Synchronous ORM call .{method}() on '{var_name}' inside "
                        f"async function '{node.name}'. Blocks the event loop."
                    ),
                    suggestion=(
                        "Use AsyncSession with await, or wrap in "
                        "asyncio.to_thread(sync_function)."
                    ),
                )
                return  # one per function is enough


def _check_unsafe_module_singleton(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag module-level class instantiation where __init__ creates mutable state.

    Module-level singletons with mutable instance attributes (self.cache={}, self.data=[])
    are shared across threads — thread-unsafe under concurrent load.
    """
    rule = "unsafe_module_singleton"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    # Find all class definitions and their __init__ mutable patterns
    mutable_classes: dict[str, int] = {}  # class_name -> lineno
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                continue
            # Check for self.x = [] or self.x = {} assignments
            for stmt in ast.walk(item):
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if not isinstance(target, ast.Attribute):
                        continue
                    if not (isinstance(target.value, ast.Name) and target.value.id == "self"):
                        continue
                    val = stmt.value
                    if isinstance(val, (ast.List, ast.Dict, ast.Set)):
                        mutable_classes[node.name] = getattr(node, "lineno", 0)
                        break
                if node.name in mutable_classes:
                    break

    if not mutable_classes:
        return

    # Check for module-level instantiation of those classes
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        fn = _attr_chain(node.value.func)
        if fn in mutable_classes:
            ctx.add_issue(
                line=getattr(node, "lineno", 0),
                rule=rule,
                severity=sev,
                message=(
                    f"Module-level singleton '{fn}()' has mutable instance state "
                    f"(defined at line {mutable_classes[fn]}). Thread-unsafe under concurrent load."
                ),
                suggestion=(
                    "Use threading.Lock for mutable state, or make the class "
                    "immutable, or instantiate per-request instead of at module level."
                ),
            )
