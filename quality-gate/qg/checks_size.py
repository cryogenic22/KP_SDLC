from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Callable

from .path_glob import matches_any
from .checks_comments import strip_js_ts_strings_and_comments
from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_file_size(
    *,
    rel_file: str,
    file_path: Path,
    lines: list[str],
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "file_size"
    if not _enabled(config, name, default=True):
        return

    rule = _rule(config, name)
    max_lines = int(rule.get("max_lines", 500) or 500)
    warning_lines = int(rule.get("warning_lines", 300) or 300)
    exceptions = [str(p) for p in (rule.get("exceptions", []) or [])]
    if exceptions and matches_any(rel_file, exceptions):
        return

    line_count = len(lines)
    if line_count > max_lines:
        add_issue(
            line=1,
            rule=name,
            severity=Severity.ERROR,
            message=f"File has {line_count} lines (max: {max_lines}). Split into smaller modules.",
            suggestion="Extract logical sections into separate files/modules.",
        )
        return

    if line_count > warning_lines:
        add_issue(
            line=1,
            rule=name,
            severity=Severity.WARNING,
            message=f"File has {line_count} lines (warning threshold: {warning_lines}).",
            suggestion="Consider refactoring before it grows further.",
        )


# ── Migration / seed path patterns ────────────────────────────────────

_MIGRATION_PATTERNS = re.compile(
    r"(^|/)(alembic|migrations|versions|seeds?|fixtures)/", re.IGNORECASE
)


def _detect_function_context(
    *,
    language: str,
    extension: str,
    is_test: bool,
    file_path: str,
) -> str:
    """Detect the function context for size limit selection.

    Returns one of: 'test', 'migration', 'react', 'python', 'typescript', 'javascript'.
    Priority: test > migration > react > language.
    """
    if is_test:
        return "test"

    normalized = file_path.replace("\\", "/")
    if _MIGRATION_PATTERNS.search(normalized):
        return "migration"

    if extension in (".tsx", ".jsx"):
        return "react"

    return language


def _function_size_limit(
    *,
    config: dict[str, Any],
    language: str,
    extension: str,
    context: str = "",
) -> int:
    """Get the max_lines limit for a function based on context.

    Checks context_limits first, then falls back to per-extension,
    per-language, and finally the global default.
    """
    rule = _rule(config, "function_size")
    max_default = int(rule.get("max_lines", 50) or 50)

    # Context-aware limits (Team Feedback #2)
    if context:
        ctx_limits = rule.get("context_limits", {})
        if isinstance(ctx_limits, dict):
            ctx_value = ctx_limits.get(context, {})
            if isinstance(ctx_value, dict) and "max_lines" in ctx_value:
                return int(ctx_value["max_lines"])

    max_by_ext = rule.get("max_lines_by_extension", {})
    if isinstance(max_by_ext, dict):
        ext_value = max_by_ext.get(extension)
        if ext_value is not None:
            return int(ext_value or max_default)

    max_by_lang = rule.get("max_lines_by_language", {})
    if isinstance(max_by_lang, dict):
        lang_value = max_by_lang.get(language)
        if lang_value is not None:
            return int(lang_value or max_default)

    return max_default


def _function_size_warning_limit(
    *,
    config: dict[str, Any],
    language: str,
    extension: str,
    context: str = "",
) -> int:
    """Get the warning_lines threshold based on context."""
    rule = _rule(config, "function_size")
    warn_default = int(rule.get("warning_lines", 30) or 30)

    if context:
        ctx_limits = rule.get("context_limits", {})
        if isinstance(ctx_limits, dict):
            ctx_value = ctx_limits.get(context, {})
            if isinstance(ctx_value, dict) and "warning_lines" in ctx_value:
                return int(ctx_value["warning_lines"])

    return warn_default


def check_function_size(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "function_size"
    if not _enabled(config, name, default=True):
        return

    max_lines = _function_size_limit(config=config, language=language, extension=file_path.suffix.lower())
    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.ERROR)

    spans = _function_spans(file_path=file_path, content=content, lines=lines, language=language)
    for func_name, start, end in spans:
        length = (end - start) + 1
        if length <= max_lines:
            continue
        add_issue(
            line=int(start),
            rule=name,
            severity=severity,
            message=f"Function '{func_name}' is {length} lines (max: {max_lines}).",
            suggestion="Extract parts into smaller helper functions.",
        )


def _function_spans(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    language: str,
) -> list[tuple[str, int, int]]:
    if language == "python":
        return _python_function_spans(file_path=file_path, content=content, lines=lines)
    if language in {"typescript", "javascript"}:
        cleaned_lines = strip_js_ts_strings_and_comments(content).splitlines()
        return _web_function_spans(cleaned_lines)
    return []


def _python_function_spans(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
) -> list[tuple[str, int, int]]:
    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        tree = None

    if tree is not None:
        out: list[tuple[str, int, int]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = int(getattr(node, "lineno", 1) or 1)
            end = int(getattr(node, "end_lineno", start) or start)
            out.append((str(getattr(node, "name", "anonymous") or "anonymous"), start, end))
        return out

    return _python_spans_fallback(lines)


def _python_spans_fallback(lines: list[str]) -> list[tuple[str, int, int]]:
    pattern = re.compile(r"^(\s*)(def|async def)\s+(\w+)")
    spans: list[tuple[str, int, int]] = []
    stack: list[tuple[int, str, int]] = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = _indent_len(line)
        if stack and indent <= stack[-1][2] and not line.lstrip().startswith("@"):
            _close_python_stack(stack, spans, indent, i - 1)

        match = pattern.match(line)
        if match:
            stack.append((i, match.group(3) or "anonymous", len(match.group(1) or "")))

    _close_python_stack(stack, spans, 0, len(lines))
    return spans


def _indent_len(line: str) -> int:
    match = re.match(r"^(\s*)", line)
    return len(match.group(1)) if match else 0


def _close_python_stack(
    stack: list[tuple[int, str, int]],
    spans: list[tuple[str, int, int]],
    indent: int,
    end_line: int,
) -> None:
    while stack and indent <= stack[-1][2]:
        start, name, _ = stack.pop()
        spans.append((name, start, end_line))


def _web_function_spans(lines: list[str]) -> list[tuple[str, int, int]]:
    func_pat = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\b")
    arrow_pat = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
    )
    spans: list[tuple[str, int, int]] = []
    i = 0
    while i < len(lines):
        start_line = i + 1
        match = func_pat.match(lines[i]) or arrow_pat.match(lines[i])
        if not match:
            i += 1
            continue
        name = match.group("name") or "anonymous"
        end_line, advanced = _scan_web_function_end(lines, i)
        spans.append((name, start_line, end_line))
        i = advanced
    return spans


def _scan_web_function_end(lines: list[str], start_idx: int) -> tuple[int, int]:
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
