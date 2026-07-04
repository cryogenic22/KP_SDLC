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

# Python/web type mirrors (e.g. ApprovalOut in schemas.py + approval.ts) can
# never be flagged by construction: Python signatures hash the AST, web
# signatures hash normalized text, so a signature group is always
# single-stack. TS and JS share one "web:" namespace deliberately — an
# identical body in a .ts and a .js file is a real duplicate.


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

    rule = _rule(config, name)
    severity = parse_severity(rule.get("severity"), default=Severity.WARNING)
    # Functions spanning fewer lines than this are never reported: trivial
    # stubs (health checks, protocol methods) duplicate by nature.
    min_lines = int(rule.get("min_lines", 4) or 4)
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
            min_lines=min_lines,
        )

    for signature, locations in func_signatures.items():
        if len(locations) <= 1:
            continue
        if len({loc[0] for loc in locations}) <= 1:
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
    min_lines: int = 4,
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
            file_path=file_path, content=content, out=func_signatures, skip_names=skip_names, min_lines=min_lines
        )
        return
    _collect_web_sigs(
        file_path=file_path, lines=lines, language=language, out=func_signatures, skip_names=skip_names, min_lines=min_lines
    )


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _collect_python_sigs(
    *,
    file_path: Path,
    content: str,
    out: dict[str, list[tuple[Path, int, str]]],
    skip_names: set[str],
    min_lines: int,
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
        if (end - start) + 1 < min_lines:
            continue
        # Name-independent signature: hash the arguments + body, never the
        # function name or decorators — a clone that was only renamed must
        # still match (the agentic regeneration failure mode).
        arg_dump = ast.dump(node.args, include_attributes=False)
        body_dump = "|".join(ast.dump(stmt, include_attributes=False) for stmt in node.body)
        sig = f"python:{_hash_text(arg_dump + '||' + body_dump)}"
        out[sig].append((file_path, start, func_name))


def _collect_web_sigs(
    *,
    file_path: Path,
    lines: list[str],
    language: str,
    out: dict[str, list[tuple[Path, int, str]]],
    skip_names: set[str],
    min_lines: int,
) -> None:
    func_pat = re.compile(r"^(?P<indent>\s*)(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\b")
    arrow_pat = re.compile(
        r"^(?P<indent>\s*)(?:export\s+)?(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
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
        if len(collected) >= min_lines:
            # Name-independent: blank the declared name out of the first
            # line so a renamed clone still hashes identically.
            first = collected[0][: match.start("name")] + "FN" + collected[0][match.end("name") :]
            rest = [raw.strip() for raw in collected[1:] if not raw.strip().startswith("//")]
            compact = re.sub(r"\s+", "", "\n".join([first.strip(), *rest]))
            sig = f"web:{_hash_text(compact)}"
            out[sig].append((file_path, i + 1, func_name))
        i = advanced


def _collect_web_block(lines: list[str], start_idx: int) -> tuple[list[str], int]:
    # Brace-less declaration (`export const double = (x) => x * 2;`): a
    # single-line block. Consuming further lines here desynchronizes the
    # scan and silently disables detection for the rest of the file.
    if "{" not in lines[start_idx]:
        return [lines[start_idx]], start_idx + 1
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

