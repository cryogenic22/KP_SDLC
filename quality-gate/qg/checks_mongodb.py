"""MongoDB technology pack — 5 rules targeting pymongo/motor misuse.

Rules:
  unbounded_find          WARNING  .find() without .limit()
  pymongo_in_async        ERROR    Sync pymongo in async code
  missing_projection      INFO     .find()/.find_one() without projection
  unbounded_array_push    WARNING  $push without $slice
  collection_name_scatter INFO     Same collection name literal in >2 files
"""
from __future__ import annotations

import ast
import re
from typing import Any

from qg.context import RuleContext, rule_config

# ── helpers ────────────────────────────────────────────────────────

_MONGO_IMPORT_PAT = re.compile(r"(?:from|import)\s+(?:pymongo|motor)")


def _has_mongo_imports(content: str) -> bool:
    return bool(_MONGO_IMPORT_PAT.search(content))


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


# ── public entry point ─────────────────────────────────────────────

def check_mongodb_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return
    if not _has_mongo_imports(ctx.content):
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_unbounded_find(ctx, tree)
    _check_pymongo_in_async(ctx, tree)
    _check_missing_projection(ctx, tree)
    _check_unbounded_array_push(ctx, tree)
    # collection_name_scatter is cross-file — handled by caller if needed


# ── rule implementations ──────────────────────────────────────────

def _check_unbounded_find(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag .find() calls without .limit() chaining."""
    rule = "unbounded_find"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "find":
            continue

        # Check if the Call result is chained with .limit()
        # This means the parent should be an Attribute access for .limit()
        # Since ast.walk doesn't give parents, check if the Call is wrapped
        # in another Call via Attribute named 'limit', 'sort', etc.
        # Simpler: check the line text for .limit(
        lineno = getattr(node, "lineno", 0)
        if 0 < lineno <= len(ctx.lines):
            line_text = ctx.lines[lineno - 1]
            # Check current line and next line for .limit(
            lookahead = line_text
            if lineno < len(ctx.lines):
                lookahead += ctx.lines[lineno]
            if ".limit(" in lookahead:
                continue

        # Exempt find_one (caught by attr check above — attr is "find" not "find_one")
        # Exempt aggregate (different method)

        ctx.add_issue(
            line=lineno,
            rule=rule,
            severity=sev,
            message="Unbounded .find() without .limit(). Can exhaust memory on large collections.",
            suggestion="Chain .limit(N) or use .find().limit(100).",
        )


def _check_pymongo_in_async(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag synchronous pymongo in files with async functions."""
    rule = "pymongo_in_async"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    has_async = any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree))
    has_fastapi = bool(re.search(r"(?:from|import)\s+fastapi", ctx.content))
    if not has_async and not has_fastapi:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("pymongo"):
                for alias in (node.names or []):
                    if alias.name == "MongoClient":
                        ctx.add_issue(
                            line=getattr(node, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message="Synchronous pymongo.MongoClient in async context. Use motor.motor_asyncio.AsyncIOMotorClient.",
                            suggestion="from motor.motor_asyncio import AsyncIOMotorClient",
                        )
        elif isinstance(node, ast.Import):
            for alias in (node.names or []):
                if alias.name == "pymongo" and (has_async or has_fastapi):
                    ctx.add_issue(
                        line=getattr(node, "lineno", 0),
                        rule=rule,
                        severity=sev,
                        message="Synchronous pymongo imported in async context. Use motor instead.",
                        suggestion="from motor.motor_asyncio import AsyncIOMotorClient",
                    )


def _check_missing_projection(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag .find()/.find_one() with filter but no projection."""
    rule = "missing_projection"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("find", "find_one"):
            continue

        # Has at least one positional arg (filter) but no second (projection)
        if len(node.args) >= 1 and len(node.args) < 2:
            # Also no projection keyword
            has_proj_kw = any(kw.arg == "projection" for kw in node.keywords)
            if not has_proj_kw:
                ctx.add_issue(
                    line=getattr(node, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message=f".{node.func.attr}() with filter but no projection. Fetches all fields.",
                    suggestion=f'collection.{node.func.attr}(filter, {{"field1": 1, "field2": 1}})',
                )


def _check_unbounded_array_push(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag $push without $slice in update operations."""
    rule = "unbounded_array_push"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    # Regex approach: look for "$push" without "$slice" in nearby context
    push_pat = re.compile(r'["\']?\$push["\']?\s*:')
    slice_pat = re.compile(r'["\']?\$slice["\']?\s*:')

    for i, line in enumerate(ctx.lines, 1):
        if not push_pat.search(line):
            continue
        # Check a window of lines around it for $slice
        window_start = max(0, i - 2)
        window_end = min(len(ctx.lines), i + 5)
        window = "\n".join(ctx.lines[window_start:window_end])
        if slice_pat.search(window):
            continue

        ctx.add_issue(
            line=i,
            rule=rule,
            severity=sev,
            message="$push without $slice. Array can grow unbounded, hitting MongoDB 16MB document limit.",
            suggestion='{"$push": {"events": {"$each": [event], "$slice": -1000}}}',
        )
