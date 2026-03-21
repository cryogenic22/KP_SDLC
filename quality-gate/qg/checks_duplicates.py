from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .types import Severity, parse_severity

AddIssue = Callable[..., None]

# ── Built-in skip lists (Team Feedback #1) ────────────────────────────

# Alembic migration functions are always identical signatures across files
_ALEMBIC_SKIP_NAMES = {"upgrade", "downgrade"}

# Enum helper methods that repeat across enum classes
_ENUM_SKIP_NAMES = {"values", "label", "labels", "choices", "from_value", "from_label"}

# Languages grouped by stack for cross-stack exemption
_PYTHON_LANGS = {"python"}
_WEB_LANGS = {"typescript", "javascript"}


def _should_skip_cross_stack(locations: list[tuple[Path, int, str]]) -> bool:
    """Return True if all duplicates are cross-stack type mirrors.

    Cross-stack = every file is either Python or Web (TS/JS), and both
    stacks are represented. This catches intentional type mirrors like
    ApprovalOut in schemas.py + approval.ts.

    If any two files share the same stack, it's a real duplicate.
    """
    if len(locations) < 2:
        return False

    py_files = []
    web_files = []
    for path, _, _ in locations:
        ext = path.suffix.lower()
        if ext == ".py":
            py_files.append(path)
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            web_files.append(path)

    # Cross-stack: exactly one from each stack, no same-stack duplicates
    if len(py_files) > 1 or len(web_files) > 1:
        return False  # Same-stack duplicates exist — flag it

    return len(py_files) >= 1 and len(web_files) >= 1


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_duplicate_helpers(
    *,
    all_files: dict[Path, tuple[str, list[str], str, bool]],
    config: dict[str, Any],
    is_test_path: Callable[[Path], bool],
    add_issue_for_path: Callable[[Path], AddIssue],
) -> None:
    name = "no_duplicate_code"
    if not _enabled(config, name, default=True):
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)
    func_signatures: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)

    for file_path, (content, lines, language, is_test) in all_files.items():
        if is_test or is_test_path(file_path):
            continue
        if language not in {"python", "typescript", "javascript"}:
            continue
        _collect_function_sigs(
            file_path=file_path,
            content=content,
            lines=lines,
            language=language,
            func_signatures=func_signatures,
        )

    cross_stack_exempt = bool(_rule(config, name).get("cross_stack_exempt", True))

    for signature, locations in func_signatures.items():
        if len(locations) <= 1:
            continue
        if len({loc[0] for loc in locations}) <= 1:
            continue
        # Cross-stack exemption: py+ts type mirrors are intentional
        if cross_stack_exempt and _should_skip_cross_stack(locations):
            continue
        first_file, first_line, first_name = locations[0]
        also_in = ", ".join(loc[0].name for loc in locations[1:4])
        add_issue_for_path(first_file)(
            line=int(first_line),
            rule=name,
            severity=severity,
            message=f"Function '{first_name}' appears duplicated across files.",
            suggestion="Extract to shared utility. Also in: " + also_in,
        )


def _collect_function_sigs(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    language: str,
    func_signatures: dict[str, list[tuple[Path, int, str]]],
) -> None:
    skip_names = {
        "constructor",
        "render",
        "main",
        "init",
        "setup",
        "__init__",
        "__repr__",
        "__str__",
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    } | _ALEMBIC_SKIP_NAMES | _ENUM_SKIP_NAMES
    if language == "python":
        _collect_python_sigs(
            file_path=file_path, content=content, lines=lines, out=func_signatures, skip_names=skip_names
        )
        return
    _collect_web_sigs(file_path=file_path, lines=lines, language=language, out=func_signatures, skip_names=skip_names)


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _collect_python_sigs(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    out: dict[str, list[tuple[Path, int, str]]],
    skip_names: set[str],
) -> None:
    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        func_name = node.name
        if not func_name or func_name.startswith("_") or func_name in skip_names:
            continue
        start = int(getattr(node, "lineno", 1) or 1)
        end = int(getattr(node, "end_lineno", start) or start)
        body_dump = ast.dump(node, include_attributes=False)
        compact = re.sub(r"\\s+", "", "\\n".join(lines[start - 1 : end]))
        sig = f"python:{_hash_text(body_dump + '|' + compact)}"
        out[sig].append((file_path, start, func_name))


def _collect_web_sigs(
    *,
    file_path: Path,
    lines: list[str],
    language: str,
    out: dict[str, list[tuple[Path, int, str]]],
    skip_names: set[str],
) -> None:
    func_pat = re.compile(r"^(?P<indent>\\s*)(?:export\\s+)?(?:async\\s+)?function\\s+(?P<name>\\w+)\\b")
    arrow_pat = re.compile(
        r"^(?P<indent>\\s*)(?:export\\s+)?(?:const|let|var)\\s+(?P<name>\\w+)\\s*=\\s*(?:async\\s*)?(?:\\([^)]*\\)|\\w+)\\s*=>"
    )
    i = 0
    while i < len(lines):
        match = func_pat.match(lines[i]) or arrow_pat.match(lines[i])
        if not match:
            i += 1
            continue
        if match.group("indent"):
            i += 1
            continue
        func_name = match.group("name") or ""
        if not func_name or func_name.startswith("_") or func_name in skip_names:
            i += 1
            continue

        collected, advanced = _collect_web_block(lines, i)
        normalized = [raw.strip() for raw in collected if not raw.strip().startswith("//")]
        compact = re.sub(r"\\s+", "", "\\n".join(normalized))
        sig = f"{language}:{_hash_text(compact)}"
        out[sig].append((file_path, i + 1, func_name))
        i = advanced


def _collect_web_block(lines: list[str], start_idx: int) -> tuple[list[str], int]:
    brace_depth = 0
    saw_open = False
    collected: list[str] = []
    j = start_idx
    while j < len(lines):
        line = lines[j]
        collected.append(line)
        brace_depth += line.count("{")
        brace_depth -= line.count("}")
        saw_open = saw_open or ("{" in line)
        if saw_open and brace_depth <= 0:
            return collected, j + 1
        j += 1
    return collected, j + 1

