"""Neo4j technology pack — 6 rules targeting Cypher/driver misuse.

Rules:
  unbounded_cypher_query     ERROR   MATCH without LIMIT
  cypher_cartesian_product   ERROR   Disconnected MATCH patterns
  cypher_string_interpolation ERROR  f-string / .format() in Cypher
  sync_neo4j_in_async        ERROR   Sync driver in async code
  missing_write_transaction  WARNING Auto-commit writes vs execute_write
  session_not_closed         WARNING driver.session() without context manager
"""
from __future__ import annotations

import ast
import re
from typing import Any

from qg.context import RuleContext, rule_config

# ── helpers ────────────────────────────────────────────────────────

_NEO4J_IMPORT_PAT = re.compile(r"(?:from|import)\s+neo4j")
_CYPHER_KEYWORDS = re.compile(r"\b(MATCH|CREATE|MERGE|DELETE|SET|REMOVE|RETURN)\b", re.IGNORECASE)
_WRITE_KEYWORDS = re.compile(r"\b(CREATE|MERGE|SET|DELETE|REMOVE)\b", re.IGNORECASE)


def _has_neo4j_imports(content: str) -> bool:
    return bool(_NEO4J_IMPORT_PAT.search(content))


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


def _extract_string_value(node: ast.expr) -> str | None:
    """Extract string value from a Constant or JoinedStr (f-string) node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("{...}")
        return "".join(parts)
    return None


def _is_cypher_string(node: ast.expr) -> tuple[bool, str]:
    """Check if a node is (or contains) a Cypher query string.
    Returns (is_cypher, extracted_text).
    """
    text = _extract_string_value(node)
    if text and _CYPHER_KEYWORDS.search(text):
        return True, text
    return False, ""


def _find_cypher_arg_in_call(node: ast.Call) -> tuple[ast.expr | None, str]:
    """Find the Cypher query argument in a session.run / tx.run / driver.execute_query call."""
    if node.args:
        is_c, text = _is_cypher_string(node.args[0])
        if is_c:
            return node.args[0], text
    for kw in node.keywords:
        if kw.arg in ("query", "cypher"):
            is_c, text = _is_cypher_string(kw.value)
            if is_c:
                return kw.value, text
    return None, ""


def _is_run_call(node: ast.Call) -> bool:
    """Check if call is session.run(), tx.run(), or driver.execute_query()."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in ("run", "execute_query")
    return False


# ── public entry point ─────────────────────────────────────────────

def check_neo4j_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return
    if not _has_neo4j_imports(ctx.content):
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_unbounded_cypher_query(ctx, tree)
    _check_cypher_cartesian_product(ctx, tree)
    _check_cypher_string_interpolation(ctx, tree)
    _check_sync_neo4j_in_async(ctx, tree)
    _check_missing_write_transaction(ctx, tree)
    _check_session_not_closed(ctx, tree)


# ── rule implementations ──────────────────────────────────────────

def _check_unbounded_cypher_query(ctx: RuleContext, tree: ast.Module) -> None:
    rule = "unbounded_cypher_query"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_run_call(node):
            continue
        qnode, text = _find_cypher_arg_in_call(node)
        if not qnode:
            continue
        upper = text.upper()
        if "MATCH" not in upper or "RETURN" not in upper:
            continue
        # Exempt if has LIMIT
        if "LIMIT" in upper:
            continue
        # Exempt if WHERE clause with specific ID lookup ($id, $param, {id})
        if re.search(r"WHERE\s+\w+\.\w+\s*=\s*\$\w+", text, re.IGNORECASE):
            continue

        ctx.add_issue(
            line=getattr(qnode, "lineno", getattr(node, "lineno", 0)),
            rule=rule,
            severity=sev,
            message="Unbounded Cypher MATCH/RETURN without LIMIT. Can exhaust database memory on large graphs.",
            suggestion="Add LIMIT $limit parameter, or use a WHERE clause with specific ID lookup.",
        )


def _check_cypher_cartesian_product(ctx: RuleContext, tree: ast.Module) -> None:
    rule = "cypher_cartesian_product"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    # Regex: MATCH (a:Label), (b:Label) — comma-separated node patterns
    cartesian_pat = re.compile(
        r"MATCH\s+\([^)]*\)\s*,\s*\([^)]*\)", re.IGNORECASE
    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_run_call(node):
            continue
        _, text = _find_cypher_arg_in_call(node)
        if not text:
            continue
        if not cartesian_pat.search(text):
            continue
        # Exempt if there's a relationship pattern connecting the nodes
        if re.search(r"\)-\[.*?\]-[>(]\(", text):
            continue

        ctx.add_issue(
            line=getattr(node, "lineno", 0),
            rule=rule,
            severity=sev,
            message="Cypher cartesian product: disconnected MATCH patterns create explosive row combinations.",
            suggestion="Connect node patterns with a relationship path, or use separate queries.",
        )


def _check_cypher_string_interpolation(ctx: RuleContext, tree: ast.Module) -> None:
    rule = "cypher_string_interpolation"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_run_call(node):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]

        # f-string containing Cypher keywords
        if isinstance(first_arg, ast.JoinedStr):
            _, text = _is_cypher_string(first_arg)
            if text:
                ctx.add_issue(
                    line=getattr(first_arg, "lineno", getattr(node, "lineno", 0)),
                    rule=rule,
                    severity=sev,
                    message="Cypher injection risk: f-string used in query. Use parameterised $param syntax.",
                    suggestion='session.run("MATCH (n) WHERE n.id = $id", id=value)',
                )
                continue

        # .format() on a Cypher string
        if isinstance(first_arg, ast.Call) and isinstance(first_arg.func, ast.Attribute):
            if first_arg.func.attr == "format":
                val_node = first_arg.func.value
                is_c, _ = _is_cypher_string(val_node)
                if is_c:
                    ctx.add_issue(
                        line=getattr(first_arg, "lineno", getattr(node, "lineno", 0)),
                        rule=rule,
                        severity=sev,
                        message="Cypher injection risk: .format() used in query. Use parameterised $param syntax.",
                        suggestion='session.run("MATCH (n) WHERE n.id = $id", id=value)',
                    )


def _check_sync_neo4j_in_async(ctx: RuleContext, tree: ast.Module) -> None:
    rule = "sync_neo4j_in_async"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    has_async_def = any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree))
    if not has_async_def:
        return

    # Check for sync GraphDatabase import/usage
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "neo4j" in node.module:
                for alias in (node.names or []):
                    if alias.name == "GraphDatabase":
                        ctx.add_issue(
                            line=getattr(node, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message="Synchronous neo4j.GraphDatabase imported in file with async functions. Use AsyncGraphDatabase.",
                            suggestion="from neo4j import AsyncGraphDatabase",
                        )
        elif isinstance(node, ast.Attribute):
            if node.attr == "GraphDatabase" and isinstance(node.value, ast.Name) and node.value.id == "neo4j":
                ctx.add_issue(
                    line=getattr(node, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message="Synchronous neo4j.GraphDatabase used in file with async functions. Use AsyncGraphDatabase.",
                    suggestion="neo4j.AsyncGraphDatabase.driver(...)",
                )


def _check_missing_write_transaction(ctx: RuleContext, tree: ast.Module) -> None:
    rule = "missing_write_transaction"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "run":
            continue

        _, text = _find_cypher_arg_in_call(node)
        if not text:
            continue
        if not _WRITE_KEYWORDS.search(text):
            continue

        ctx.add_issue(
            line=getattr(node, "lineno", 0),
            rule=rule,
            severity=sev,
            message="Write Cypher via session.run() bypasses automatic retry. Use session.execute_write() for transactional safety.",
            suggestion="session.execute_write(lambda tx: tx.run(query, **params))",
        )


def _check_session_not_closed(ctx: RuleContext, tree: ast.Module) -> None:
    rule = "session_not_closed"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    # Find driver.session() calls that are NOT in a with statement
    # Strategy: collect all Assign nodes where value is driver.session(),
    # then check if they're inside a With block.
    with_context_items: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    with_context_items.add(id(item.context_expr))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if id(node) in with_context_items:
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "session":
            continue

        # Check it's likely a driver.session() call
        ctx.add_issue(
            line=getattr(node, "lineno", 0),
            rule=rule,
            severity=sev,
            message="driver.session() used without context manager. Session may leak connections.",
            suggestion="Use: with driver.session() as session: ...",
        )
