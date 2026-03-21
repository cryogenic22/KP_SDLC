from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable

from .checks_comments import strip_js_ts_strings_and_comments
from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_no_debug_statements(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "no_debug_statements"
    if not _enabled(config, name, default=True):
        return

    rule = _rule(config, name)
    patterns_cfg = dict(rule.get("patterns", {}) or {})
    patterns = [str(p) for p in (patterns_cfg.get(language) or [])]
    exceptions = [str(e) for e in (rule.get("exceptions", ["console.error"]) or [])]
    severity = parse_severity(rule.get("severity"), default=Severity.ERROR)

    if language == "python":
        _check_python_debug(content=content, file_path=file_path, patterns=patterns, add_issue=add_issue, severity=severity)
        return

    if language not in {"typescript", "javascript"}:
        return

    cleaned = strip_js_ts_strings_and_comments(content)
    _check_web_debug(
        cleaned_lines=cleaned.splitlines(),
        original_lines=lines,
        patterns=patterns or ["console.log", "console.debug", "debugger"],
        exceptions=exceptions,
        add_issue=add_issue,
        severity=severity,
    )


def _check_python_debug(
    *,
    content: str,
    file_path: Path,
    patterns: list[str],
    add_issue: AddIssue,
    severity: Severity,
) -> None:
    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return

    want_breakpoint, want_pdb, want_import_pdb = _python_debug_wants(patterns)
    if want_import_pdb:
        _python_debug_import_pdb(tree, add_issue=add_issue, severity=severity)
    if want_breakpoint or want_pdb:
        _python_debug_calls(
            tree,
            want_breakpoint=want_breakpoint,
            want_pdb=want_pdb,
            add_issue=add_issue,
            severity=severity,
        )


def _python_debug_wants(patterns: list[str]) -> tuple[bool, bool, bool]:
    patterns = patterns or ["breakpoint()", "pdb.set_trace", "import pdb"]
    return (
        any("breakpoint" in p for p in patterns),
        any("pdb.set_trace" in p for p in patterns),
        any("import pdb" in p for p in patterns),
    )


def _python_debug_import_pdb(tree: ast.AST, *, add_issue: AddIssue, severity: Severity) -> None:
    for node in getattr(tree, "body", []) or []:
        if not isinstance(node, ast.Import):
            continue
        if any(alias.name == "pdb" for alias in node.names):
            add_issue(
                line=int(getattr(node, "lineno", 1) or 1),
                rule="no_debug_statements",
                severity=severity,
                message="Debug statement found: 'import pdb'",
                suggestion="Remove before committing.",
            )


def _python_debug_calls(
    tree: ast.AST,
    *,
    want_breakpoint: bool,
    want_pdb: bool,
    add_issue: AddIssue,
    severity: Severity,
) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if want_breakpoint and _is_breakpoint_call(node):
            add_issue(
                line=int(getattr(node, "lineno", 1) or 1),
                rule="no_debug_statements",
                severity=severity,
                message="Debug statement found: 'breakpoint()'",
                suggestion="Remove before committing.",
            )
        if want_pdb and _is_pdb_set_trace_call(node):
            add_issue(
                line=int(getattr(node, "lineno", 1) or 1),
                rule="no_debug_statements",
                severity=severity,
                message="Debug statement found: 'pdb.set_trace'",
                suggestion="Remove before committing.",
            )


def _is_breakpoint_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "breakpoint"


def _is_pdb_set_trace_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "set_trace":
        return False
    return isinstance(func.value, ast.Name) and func.value.id == "pdb"


def _check_web_debug(
    *,
    cleaned_lines: list[str],
    original_lines: list[str],
    patterns: list[str],
    exceptions: list[str],
    add_issue: AddIssue,
    severity: Severity,
) -> None:
    for i, line in enumerate(cleaned_lines, 1):
        if any(exc in line for exc in exceptions):
            continue
        for pat in patterns:
            if pat in line:
                add_issue(
                    line=i,
                    rule="no_debug_statements",
                    severity=severity,
                    message=f"Debug statement found: '{pat}'",
                    snippet=str(original_lines[i - 1].strip()[:100]) if 0 < i <= len(original_lines) else "",
                    suggestion="Remove before committing.",
                )
