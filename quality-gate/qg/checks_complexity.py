from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .checks_comments import strip_js_ts_strings_and_comments
from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_max_complexity(
    *,
    file_path: Path,
    content: str,
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "max_complexity"
    if not _enabled(config, name, default=True):
        return

    rule = _rule(config, name)
    max_complexity = int(rule.get("cyclomatic_max", 10) or 10)
    severity = parse_severity(rule.get("severity"), default=Severity.WARNING)

    if language == "python":
        _check_python_complexity(
            content=content,
            file_path=file_path,
            max_complexity=max_complexity,
            add_issue=add_issue,
            severity=severity,
        )
        return

    if language in {"typescript", "javascript"}:
        cleaned = strip_js_ts_strings_and_comments(content)
        _check_web_complexity(
            cleaned_lines=cleaned.splitlines(),
            max_complexity=max_complexity,
            add_issue=add_issue,
            severity=severity,
        )


def _python_complexity(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.With,
                ast.AsyncWith,
                ast.Try,
                ast.ExceptHandler,
                ast.IfExp,
            ),
        ):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += max(0, len(child.values) - 1)
        elif isinstance(child, ast.Match):
            score += len(child.cases)
    return score


def _check_python_complexity(
    *,
    content: str,
    file_path: Path,
    max_complexity: int,
    add_issue: AddIssue,
    severity: Severity,
) -> None:
    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        complexity = _python_complexity(node)
        if complexity <= max_complexity:
            continue
        add_issue(
            line=int(getattr(node, "lineno", 1) or 1),
            rule="max_complexity",
            severity=severity,
            message=f"Function '{node.name}' has complexity {complexity} (max: {max_complexity}).",
            suggestion="Simplify by extracting conditions or using early returns.",
        )


@dataclass(slots=True)
class _WebFunc:
    name: str
    start: int
    end: int


def _web_function_spans(lines: list[str]) -> list[_WebFunc]:
    func_pat = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\b")
    arrow_pat = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
    )
    out: list[_WebFunc] = []
    i = 0
    while i < len(lines):
        match = func_pat.match(lines[i]) or arrow_pat.match(lines[i])
        if not match:
            i += 1
            continue
        start = i + 1
        end, advanced = _scan_web_end(lines, i)
        out.append(_WebFunc(name=match.group("name") or "anonymous", start=start, end=end))
        i = advanced
    return out


def _scan_web_end(lines: list[str], start_idx: int) -> tuple[int, int]:
    brace_depth = 0
    saw_open = False
    j = start_idx
    while j < len(lines):
        line = lines[j]
        brace_depth += line.count("{")
        brace_depth -= line.count("}")
        saw_open = saw_open or ("{" in line)
        if saw_open and brace_depth <= 0:
            return j + 1, j + 1
        j += 1
    if not saw_open:
        return start_idx + 1, start_idx + 1
    return len(lines), len(lines)


def _web_complexity(lines: list[str]) -> int:
    keywords = ["if ", "else if ", "for ", "while ", "catch ", "&& ", "|| ", "case ", "? "]
    return 1 + sum(sum(line.count(k) for k in keywords) for line in lines)


def _check_web_complexity(
    *,
    cleaned_lines: list[str],
    max_complexity: int,
    add_issue: AddIssue,
    severity: Severity,
) -> None:
    for func in _web_function_spans(cleaned_lines):
        snippet = cleaned_lines[func.start - 1 : func.end]
        complexity = _web_complexity(snippet)
        if complexity <= max_complexity:
            continue
        add_issue(
            line=int(func.start),
            rule="max_complexity",
            severity=severity,
            message=f"Function '{func.name}' has complexity {complexity} (max: {max_complexity}).",
            suggestion="Simplify by extracting conditions or using early returns.",
        )

