"""Observability & telemetry pack — 4 rules.

Rules:
  missing_structured_logging   INFO     print() used for logging instead of logging/structlog
  missing_request_tracing      INFO     FastAPI app without request_id/correlation_id middleware
  missing_error_telemetry      WARNING  except blocks without logging or telemetry
  missing_health_endpoint      INFO     FastAPI app without /health or /healthz route
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


# ── public entry point ─────────────────────────────────────────────

def check_observability_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return

    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_missing_structured_logging(ctx, tree)
    _check_missing_request_tracing(ctx, tree)
    _check_missing_error_telemetry(ctx, tree)
    _check_missing_health_endpoint(ctx, tree)


# ── rule implementations ──────────────────────────────────────────

def _check_missing_structured_logging(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag files using print() for logging instead of logging/structlog.

    Checks non-test Python files with 3+ print() calls and no logging import.
    """
    rule = "missing_structured_logging"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    if ctx.is_test:
        return

    # Skip if the file already imports logging or structlog
    has_logging_import = bool(re.search(
        r"(?:from|import)\s+(?:logging|structlog|loguru)", ctx.content
    ))
    if has_logging_import:
        return

    # Count print() calls
    print_count = 0
    first_print_line = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "print":
                print_count += 1
                if first_print_line == 0:
                    first_print_line = getattr(node, "lineno", 0)

    if print_count >= 3:
        ctx.add_issue(
            line=first_print_line,
            rule=rule,
            severity=sev,
            message=f"{print_count} print() calls used for logging. No structured logging library imported.",
            suggestion="Use logging.getLogger(__name__) or structlog for queryable, filterable log output.",
        )


def _check_missing_request_tracing(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag FastAPI apps without request tracing middleware (request_id/correlation_id)."""
    rule = "missing_request_tracing"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    # Only check files that instantiate FastAPI()
    has_fastapi_app = False
    app_line = 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _attr_chain(node.func)
            if name == "FastAPI":
                has_fastapi_app = True
                app_line = getattr(node, "lineno", 1)
                break

    if not has_fastapi_app:
        return

    # Check for tracing signals
    tracing_signals = {
        "request_id", "correlation_id", "trace_id", "x-request-id",
        "RequestIDMiddleware", "CorrelationIdMiddleware",
        "opentelemetry", "OpenTelemetry", "jaeger", "zipkin",
        "ddtrace", "sentry_sdk",
    }

    has_tracing = any(sig in ctx.content for sig in tracing_signals)

    if not has_tracing:
        ctx.add_issue(
            line=app_line,
            rule=rule,
            severity=sev,
            message="FastAPI app without request tracing (request_id/correlation_id). Cannot correlate errors across services.",
            suggestion="Add request ID middleware or OpenTelemetry instrumentation for distributed tracing.",
        )


_LOG_CALLS = frozenset({
    "logger.error", "logger.exception", "logger.warning", "logger.critical",
    "logging.error", "logging.exception", "logging.warning", "logging.critical",
    "log.error", "log.exception", "log.warning", "log.critical",
    "sentry_sdk.capture_exception", "sentry_sdk.capture_message",
})


def _check_missing_error_telemetry(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag except blocks that swallow errors without logging or telemetry.

    Only flags blocks that don't log, don't re-raise, and don't call telemetry.
    """
    rule = "missing_error_telemetry"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    if ctx.is_test:
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue

        has_logging = False
        has_raise = False

        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                has_raise = True
                break
            if isinstance(child, ast.Call):
                fn = _attr_chain(child.func)
                if fn in _LOG_CALLS:
                    has_logging = True
                    break
                # Also accept print() in except as minimal telemetry
                if isinstance(child.func, ast.Name) and child.func.id == "print":
                    has_logging = True
                    break

        if has_logging or has_raise:
            continue

        # Check if the except body is just `pass` or trivial
        stmts = [
            s for s in node.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
        ]
        if len(stmts) <= 1 and stmts and isinstance(stmts[0], ast.Pass):
            ctx.add_issue(
                line=getattr(node, "lineno", 0),
                rule=rule,
                severity=sev,
                message="Exception caught and silently swallowed (pass). No logging or telemetry.",
                suggestion="Add logger.exception('...') or re-raise. Silent failures are invisible in production.",
            )
        elif not has_logging and not has_raise:
            # Has some handling but no logging
            ctx.add_issue(
                line=getattr(node, "lineno", 0),
                rule=rule,
                severity=sev,
                message="Exception handler without logging or error telemetry. Errors will be invisible in monitoring.",
                suggestion="Add logger.exception('context message') to capture the error in logs.",
            )


def _check_missing_health_endpoint(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag FastAPI apps without a /health or /healthz endpoint."""
    rule = "missing_health_endpoint"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    # Only check files that instantiate FastAPI()
    has_fastapi_app = False
    app_line = 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _attr_chain(node.func)
            if name == "FastAPI":
                has_fastapi_app = True
                app_line = getattr(node, "lineno", 1)
                break

    if not has_fastapi_app:
        return

    # Check for health endpoint signals
    health_signals = {
        "/health", "/healthz", "/health_check", "/ready", "/readyz",
        "/liveness", "/readiness", "health_check", "healthz",
    }

    has_health = any(sig in ctx.content for sig in health_signals)

    if not has_health:
        ctx.add_issue(
            line=app_line,
            rule=rule,
            severity=sev,
            message="FastAPI app without health check endpoint (/health or /healthz).",
            suggestion="Add @app.get('/health') returning {'status': 'ok'} for load balancer and orchestrator probes.",
        )
