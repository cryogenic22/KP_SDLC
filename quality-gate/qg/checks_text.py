from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .checks_comments import js_comment_tokens, python_comment_tokens
from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_no_todo_fixme(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "no_todo_fixme"
    if not _enabled(config, name, default=True):
        return

    rule = _rule(config, name)
    patterns = [str(p) for p in (rule.get("patterns", ["TODO", "FIXME", "XXX", "HACK", "BUG"]) or [])]
    allow_with_issue = bool(rule.get("allow_with_issue", True))
    issue_pattern = str(rule.get("issue_pattern", r"(TODO|FIXME|XXX|HACK|BUG)\s*\(#\d+\)"))
    severity = parse_severity(rule.get("severity"), default=Severity.ERROR)

    tokens = (
        python_comment_tokens(content)
        if language == "python"
        else js_comment_tokens(lines)
        if language in {"typescript", "javascript"}
        else []
    )
    if not tokens:
        return

    issue_re = re.compile(issue_pattern, re.IGNORECASE)
    pattern_res = [(pat, re.compile(rf"\\b{re.escape(pat)}\\b", re.IGNORECASE)) for pat in patterns]
    for line_no, comment in tokens:
        for pat, pat_re in pattern_res:
            if not pat_re.search(comment):
                continue
            if allow_with_issue and issue_re.search(comment):
                continue
            add_issue(
                line=int(line_no),
                rule=name,
                severity=severity,
                message=f"Found '{pat}'. Either fix it or link to an issue.",
                snippet=str(lines[line_no - 1].strip()[:100]) if 0 < line_no <= len(lines) else "",
                suggestion=f"Change to: {pat}(#123): description",
            )


def check_no_type_escape(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "no_type_escape"
    if not _enabled(config, name, default=True):
        return

    rule = _rule(config, name)
    patterns_cfg = dict(rule.get("patterns", {}) or {})
    patterns = [str(p) for p in (patterns_cfg.get(language) or [])]
    severity = parse_severity(rule.get("severity"), default=Severity.WARNING)
    if not patterns:
        return

    tokens = (
        python_comment_tokens(content)
        if language == "python"
        else js_comment_tokens(lines)
        if language in {"typescript", "javascript"}
        else []
    )
    for line_no, comment in tokens:
        for pat in patterns:
            if pat not in comment:
                continue
            add_issue(
                line=int(line_no),
                rule=name,
                severity=severity,
                message=f"Type escape found: '{pat}'",
                snippet=str(lines[line_no - 1].strip()[:100]) if 0 < line_no <= len(lines) else "",
                suggestion="Fix the type properly instead of escaping.",
            )

