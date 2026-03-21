"""Document parsing pack — 4 rules for Azure Doc Intelligence / Textract / etc.

Rules:
  missing_confidence_filter      WARNING  Extraction results used without confidence check
  unbounded_document_processing  WARNING  Parse API called without file size validation
  sync_parsing_in_handler        WARNING  Long-running parse in HTTP handler
  missing_parse_cache            INFO     No caching of parsed results
"""
from __future__ import annotations

import ast
import re
from typing import Any

from qg.context import RuleContext, rule_config

# ── helpers ────────────────────────────────────────────────────────

_DOCPARSE_IMPORT_PAT = re.compile(
    r"(?:from|import)\s+"
    r"(?:azure\.ai\.formrecognizer|azure\.ai\.documentintelligence"
    r"|google\.cloud\.documentai"
    r"|textract)",
    re.IGNORECASE,
)

_PARSE_API_METHODS = {
    "begin_analyze_document", "analyze_document",
    "begin_recognize_content", "begin_recognize_invoices",
    "detect_document_text", "process_document",
}

_CONFIDENCE_ATTRS = {"confidence", "confidence_score"}

_ROUTE_DECORATORS = {"get", "post", "put", "delete", "patch"}

_CACHE_SIGNALS = {"hashlib", "lru_cache", "cache", "redis", "memcache", "sha256", "md5"}


def _has_docparse_imports(content: str) -> bool:
    return bool(_DOCPARSE_IMPORT_PAT.search(content))


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


def _is_route_decorator(dec: ast.expr) -> bool:
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Attribute):
        return dec.attr in _ROUTE_DECORATORS
    return False


def _func_has_parse_call(node: ast.AST) -> list[ast.Call]:
    """Return parse API calls found within a function body."""
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if child.func.attr in _PARSE_API_METHODS:
                calls.append(child)
    return calls


# ── public entry point ─────────────────────────────────────────────

def check_docparse_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return
    if not _has_docparse_imports(ctx.content):
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_missing_confidence_filter(ctx, tree)
    _check_unbounded_document_processing(ctx, tree)
    _check_sync_parsing_in_handler(ctx, tree)
    _check_missing_parse_cache(ctx, tree)


# ── rule implementations ──────────────────────────────────────────

def _check_missing_confidence_filter(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag functions that access parse results without confidence checks."""
    rule = "missing_confidence_filter"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    result_attrs = {"content", "fields", "value", "text", "tables", "pages"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        accesses_result = False
        has_confidence_check = False

        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                if child.attr in result_attrs:
                    accesses_result = True
                if child.attr in _CONFIDENCE_ATTRS:
                    has_confidence_check = True
            if isinstance(child, ast.Compare):
                for comp in child.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, (int, float)):
                        if 0 < comp.value < 1:
                            has_confidence_check = True

        if accesses_result and not has_confidence_check:
            # Only flag if function body has parse-related content
            parse_calls = _func_has_parse_call(node)
            func_src = ast.dump(node)
            has_parse_context = bool(parse_calls) or any(
                kw in func_src for kw in ("analyze", "extract", "formrecognizer", "documentintelligence")
            )
            if has_parse_context:
                ctx.add_issue(
                    line=getattr(node, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message=f"Function '{node.name}' accesses parsing results without confidence threshold check.",
                    suggestion="Check field.confidence >= 0.85 before using extracted values.",
                )


def _check_unbounded_document_processing(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag parse API calls without prior file size validation."""
    rule = "unbounded_document_processing"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    size_checks = {"getsize", "Content-Length", "len", "MAX_DOCUMENT_SIZE", "max_size", "file_size"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        parse_calls = _func_has_parse_call(node)
        if not parse_calls:
            continue

        # Check if function validates size before the parse call
        func_src = ast.dump(node)
        has_size_check = any(sc in func_src for sc in size_checks)

        if not has_size_check:
            ctx.add_issue(
                line=getattr(parse_calls[0], "lineno", getattr(node, "lineno", 0)),
                rule=rule,
                severity=sev,
                message=f"Document parsing in '{node.name}' without file size validation. Cost and latency risk.",
                suggestion="Check len(file_bytes) or page count before submitting to parsing API.",
            )


def _check_sync_parsing_in_handler(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag parse API calls directly in route handlers."""
    rule = "sync_parsing_in_handler"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_route = any(_is_route_decorator(d) for d in node.decorator_list)
        if not is_route:
            continue

        parse_calls = _func_has_parse_call(node)
        if parse_calls:
            ctx.add_issue(
                line=getattr(parse_calls[0], "lineno", getattr(node, "lineno", 0)),
                rule=rule,
                severity=sev,
                message=f"Document parsing called directly in route handler '{node.name}'. Blocks for 5-60s.",
                suggestion="Offload to BackgroundTasks, Celery, or asyncio.create_task and return a job ID.",
            )


def _check_missing_parse_cache(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag parse functions without any caching mechanism."""
    rule = "missing_parse_cache"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        parse_calls = _func_has_parse_call(node)
        if not parse_calls:
            continue

        # Check for caching signals in function and its decorators
        func_src = ast.dump(node)
        has_cache = any(sig in func_src for sig in _CACHE_SIGNALS)

        # Also check decorators
        for dec in node.decorator_list:
            dec_name = _attr_chain(dec.func) if isinstance(dec, ast.Call) else _attr_chain(dec)
            if any(sig in dec_name.lower() for sig in ("cache", "lru_cache", "cached")):
                has_cache = True

        # Check module-level imports
        has_cache = has_cache or any(sig in ctx.content for sig in ("hashlib", "lru_cache", "functools.cache"))

        if not has_cache:
            ctx.add_issue(
                line=getattr(node, "lineno", 0),
                rule=rule,
                severity=sev,
                message=f"Function '{node.name}' calls parsing API without caching. Re-parsing wastes money.",
                suggestion="Hash document content and cache results to avoid re-parsing identical documents.",
            )
