"""Security enhancements — 7 rules.

Rules:
  env_variable_exposure   ERROR   Logging/returning os.environ
  missing_rate_limiting   INFO    FastAPI app without rate limiting (WARNING for AI apps)
  secret_in_env_default   ERROR   Live secrets as os.getenv() fallback defaults
  empty_security_config   ERROR   Empty-string security keys (SECRET_KEY = "")
  sql_string_interpolation ERROR  f-string SQL query construction
  sensitive_data_in_logs  WARNING Tokens/secrets in log statements
  client_exposed_secret   ERROR   Secrets in NEXT_PUBLIC_/REACT_APP_ vars
"""
from __future__ import annotations

import ast
import re
from typing import Any

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

def check_security_patterns(ctx: RuleContext) -> None:
    if ctx.language != "python":
        return

    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_env_variable_exposure(ctx, tree)
    _check_missing_rate_limiting(ctx, tree)
    _check_secret_in_env_default(ctx, tree)
    _check_empty_security_config(ctx)
    _check_sql_string_interpolation(ctx, tree)
    _check_sensitive_data_in_logs(ctx, tree)
    _check_client_exposed_secret(ctx)


# ── rule implementations ──────────────────────────────────────────

def _check_env_variable_exposure(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag logging or returning os.environ (full dict)."""
    rule = "env_variable_exposure"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    if ctx.is_test:
        return

    for node in ast.walk(tree):
        # Detect logging of os.environ
        if isinstance(node, ast.Call):
            fn = _attr_chain(node.func)
            # logger.info(...), logging.info(...), print(...)
            is_log_call = any(
                fn.endswith(f".{m}") or fn == m
                for m in ("info", "debug", "warning", "error", "exception", "critical", "print")
            )
            if not is_log_call:
                continue

            # Check args and f-string values for os.environ
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Attribute):
                        chain = _attr_chain(sub)
                        if chain == "os.environ":
                            ctx.add_issue(
                                line=getattr(node, "lineno", 0),
                                rule=rule,
                                severity=sev,
                                message="os.environ logged or printed. May expose secrets (API keys, tokens, passwords).",
                                suggestion="Log specific non-sensitive variables instead of the full environment.",
                            )
                            return  # one per file

        # Detect returning os.environ in route handlers
        if isinstance(node, ast.Return) and node.value:
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Attribute):
                    if _attr_chain(sub) == "os.environ":
                        ctx.add_issue(
                            line=getattr(node, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message="os.environ returned from function. Exposes all environment secrets.",
                            suggestion="Return only the specific non-sensitive values needed.",
                        )
                        return


def _check_missing_rate_limiting(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag FastAPI app without rate limiting middleware."""
    rule = "missing_rate_limiting"
    if not _enabled(ctx, rule):
        return

    # Only check files that instantiate FastAPI()
    has_fastapi_app = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _attr_chain(node.func)
            if name == "FastAPI":
                has_fastapi_app = True
                break

    if not has_fastapi_app:
        return

    # Check for rate limiting signals
    rate_limit_signals = {
        "slowapi", "Limiter", "RateLimiter", "fastapi_limiter",
        "rate_limit", "ratelimit", "throttle",
    }

    has_rate_limiting = any(sig in ctx.content for sig in rate_limit_signals)

    if has_rate_limiting:
        return

    # Upgrade severity for AI-powered APIs
    has_llm = bool(re.search(r"(?:from|import)\s+(?:langchain|openai|anthropic)", ctx.content))
    sev = _severity(ctx, rule, "warning" if has_llm else "info")

    msg = "FastAPI app without rate limiting."
    if has_llm:
        msg += " AI-powered APIs without rate limiting can generate unbounded costs from abuse."

    ctx.add_issue(
        line=1,
        rule=rule,
        severity=sev,
        message=msg,
        suggestion="Add rate limiting: pip install slowapi && Limiter(key_func=get_remote_address)",
    )


# ── new security gap rules ───────────────────────────────────────

_SECRET_KEY_NAMES = {"secret", "key", "password", "token", "credential", "api_key", "apikey", "auth"}

_SQL_KEYWORDS_RE = re.compile(
    r"\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|GRANT|TRUNCATE)\b",
    re.IGNORECASE,
)

_EMPTY_SECRET_RE = re.compile(
    r"""^[ \t]*(?:SECRET_KEY|JWT_SECRET|JWT_SECRET_KEY|SECRET|API_SECRET|AUTH_SECRET|"""
    r"""ENCRYPTION_KEY|SIGNING_KEY|TOKEN_SECRET|PASSWORD)"""
    r"""\s*[:=]\s*(?:["']["']|b["']["'])""",
    re.MULTILINE,
)

_CLIENT_SECRET_RE = re.compile(
    r"""(?:NEXT_PUBLIC_|REACT_APP_|VITE_)(?:\w*(?:SECRET|KEY|PASSWORD|TOKEN|CREDENTIAL)\w*)""",
    re.IGNORECASE,
)


def _check_secret_in_env_default(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag os.getenv('*SECRET*', '<non-empty>') — live secrets as fallback defaults."""
    rule = "secret_in_env_default"
    if not _enabled(ctx, rule):
        return
    if "getenv" not in ctx.content and "environ.get" not in ctx.content:
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = _attr_chain(node.func)
        if fn not in ("os.getenv", "os.environ.get"):
            continue
        # Must have 2 args: env var name and a default
        args = node.args
        if len(args) < 2:
            continue

        env_name = args[0]
        default_val = args[1]

        # Check if env var name looks secret-related
        if isinstance(env_name, ast.Constant) and isinstance(env_name.value, str):
            name_lower = env_name.value.lower()
            if not any(s in name_lower for s in _SECRET_KEY_NAMES):
                continue
        else:
            continue

        # Check if default value is a non-empty string (potential real secret)
        if isinstance(default_val, ast.Constant) and isinstance(default_val.value, str):
            val = default_val.value.strip()
            if len(val) >= 8:  # Non-trivial default = likely a real secret
                ctx.add_issue(
                    line=getattr(node, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message=f"os.getenv('{env_name.value}', '<{len(val)}-char default>') — "
                            f"secret used as fallback default. Persists in git history.",
                    suggestion="Remove the default value. Fail fast at startup if the env var is missing.",
                )


def _check_empty_security_config(ctx: RuleContext) -> None:
    """Flag SECRET_KEY = '', JWT_SECRET = '' etc."""
    rule = "empty_security_config"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for i, line in enumerate(ctx.lines, 1):
        if _EMPTY_SECRET_RE.search(line):
            ctx.add_issue(
                line=i,
                rule=rule,
                severity=sev,
                message="Security config variable set to empty string — effectively disabling security.",
                snippet=line.strip()[:120],
                suggestion="Set a strong secret via environment variable. Fail at startup if not set.",
            )


def _check_sql_string_interpolation(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag f-string or .format() containing SQL keywords with variables."""
    rule = "sql_string_interpolation"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    for node in ast.walk(tree):
        # Check f-strings (JoinedStr) that contain SQL keywords
        if isinstance(node, ast.JoinedStr):
            # Reconstruct approximate string to check for SQL keywords
            text_parts = []
            has_expression = False
            for value in node.values:
                if isinstance(value, ast.Constant):
                    text_parts.append(str(value.value))
                elif isinstance(value, ast.FormattedValue):
                    has_expression = True
                    text_parts.append("{}")

            if not has_expression:
                continue

            combined = " ".join(text_parts)
            if _SQL_KEYWORDS_RE.search(combined):
                ctx.add_issue(
                    line=getattr(node, "lineno", 0),
                    rule=rule,
                    severity=sev,
                    message="SQL query built with f-string interpolation — SQL injection risk.",
                    suggestion="Use parameterized queries: cursor.execute('SELECT ... WHERE id = ?', (id,))",
                )

        # Check .format() calls on strings containing SQL
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "format":
                # Check if the base is a string constant with SQL
                base = node.func.value
                if isinstance(base, ast.Constant) and isinstance(base.value, str):
                    if _SQL_KEYWORDS_RE.search(base.value):
                        ctx.add_issue(
                            line=getattr(node, "lineno", 0),
                            rule=rule,
                            severity=sev,
                            message="SQL query built with .format() — SQL injection risk.",
                            suggestion="Use parameterized queries instead of string formatting.",
                        )


def _check_sensitive_data_in_logs(ctx: RuleContext, tree: ast.Module) -> None:
    """Flag logging calls that reference token/secret/password/key variables."""
    rule = "sensitive_data_in_logs"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    _log_methods = {"info", "debug", "warning", "error", "exception", "critical", "print"}
    _sensitive_names = {"token", "secret", "password", "api_key", "apikey", "credential",
                        "access_token", "refresh_token", "private_key", "auth_token",
                        "encryption_key", "signing_key", "jwt"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = _attr_chain(node.func)
        method = fn.split(".")[-1] if "." in fn else fn
        if method not in _log_methods:
            continue

        # Check all arguments for sensitive variable names
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for sub in ast.walk(arg):
                name = ""
                if isinstance(sub, ast.Name):
                    name = sub.id.lower()
                elif isinstance(sub, ast.Attribute):
                    name = sub.attr.lower()
                if name and any(s in name for s in _sensitive_names):
                    ctx.add_issue(
                        line=getattr(node, "lineno", 0),
                        rule=rule,
                        severity=sev,
                        message=f"Sensitive variable '{name}' passed to logging/print call.",
                        suggestion="Never log secrets, tokens, or passwords. Log a masked version or omit entirely.",
                    )
                    return  # one per file is enough


def _check_client_exposed_secret(ctx: RuleContext) -> None:
    """Flag NEXT_PUBLIC_*SECRET*, REACT_APP_*KEY* patterns in code/env files."""
    rule = "client_exposed_secret"
    if not _enabled(ctx, rule):
        return
    # Applies to all languages and .env files
    sev = _severity(ctx, rule, "error")

    for i, line in enumerate(ctx.lines, 1):
        match = _CLIENT_SECRET_RE.search(line)
        if match:
            ctx.add_issue(
                line=i,
                rule=rule,
                severity=sev,
                message=f"Client-exposed secret: '{match.group(0)}' will be bundled into the browser JS.",
                snippet=line.strip()[:120],
                suggestion="Move secrets to server-side env vars. Only expose non-sensitive config via NEXT_PUBLIC_/REACT_APP_.",
            )
