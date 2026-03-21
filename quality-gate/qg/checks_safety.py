from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Callable

from .checks_comments import strip_js_ts_strings_and_comments
from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_no_silent_catch(
    *,
    file_path: Path,
    content: str,
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "no_silent_catch"
    if not _enabled(config, name, default=True):
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.ERROR)
    if language == "python":
        _check_python_silent_except(content=content, file_path=file_path, add_issue=add_issue, severity=severity)
        return
    if language in {"typescript", "javascript"}:
        _check_web_silent_catch(content=content, add_issue=add_issue, severity=severity)


def _check_python_silent_except(
    *,
    content: str,
    file_path: Path,
    add_issue: AddIssue,
    severity: Severity,
) -> None:
    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                add_issue(
                    line=int(getattr(handler, "lineno", getattr(node, "lineno", 1)) or 1),
                    rule="no_silent_catch",
                    severity=severity,
                    message="Silent exception catch (except: pass). Errors are being swallowed.",
                    suggestion="Log the error or handle it properly.",
                )


def _check_web_silent_catch(*, content: str, add_issue: AddIssue, severity: Severity) -> None:
    cleaned = strip_js_ts_strings_and_comments(content)
    for match in re.finditer(r"catch\s*\([^)]*\)\s*\{\s*\}", cleaned):
        line_no = cleaned[: match.start()].count("\n") + 1
        add_issue(
            line=int(line_no),
            rule="no_silent_catch",
            severity=severity,
            message="Empty catch block. Errors are being swallowed.",
            suggestion="Log the error or handle it properly.",
        )


def check_no_hardcoded_secrets(
    *,
    lines: list[str],
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "no_hardcoded_secrets"
    if not _enabled(config, name, default=True):
        return

    rule = _rule(config, name)
    exceptions = [str(e) for e in (rule.get("exceptions", ["test", "example", "placeholder", '""', "''"]) or [])]
    severity = parse_severity(rule.get("severity"), default=Severity.ERROR)

    patterns = [
        (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\'][^"\']{8,}["\']', "password"),
        (r'(?i)(api_key|apikey|api-key)\s*[=:]\s*["\'][^"\']{16,}["\']', "API key"),
        (r'(?i)(secret|secret_key)\s*[=:]\s*["\'][^"\']{16,}["\']', "secret"),
        (r'(?i)(token|auth_token|access_token)\s*[=:]\s*["\'][A-Za-z0-9_-]{20,}["\']', "token"),
        (r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", "private key"),
    ]

    for i, line in enumerate(lines, 1):
        lowered = line.lower()
        if any(exc in lowered for exc in exceptions):
            continue
        for pattern, secret_type in patterns:
            if re.search(pattern, line):
                add_issue(
                    line=i,
                    rule="no_hardcoded_secrets",
                    severity=severity,
                    message=f"Potential hardcoded {secret_type} found.",
                    snippet=line.strip()[:50] + "...",
                    suggestion="Use environment variables instead.",
                )
                break

