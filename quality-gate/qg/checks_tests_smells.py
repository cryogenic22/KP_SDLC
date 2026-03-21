from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_noqa_ann001(
    *,
    language: str,
    is_test: bool,
    lines: list[str],
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "noqa_ann001"
    if not _enabled(config, name, default=False):
        return
    if language != "python" or not is_test:
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)
    for i, line in enumerate(lines, 1):
        if "noqa" in line and "ANN001" in line:
            add_issue(
                line=i,
                rule=name,
                severity=severity,
                message="Avoid `# noqa: ANN001` in tests; add a proper type annotation instead.",
                snippet=line.strip()[:120],
                suggestion="Add a real annotation (or refactor the helper) instead of suppressing.",
            )


def check_duplicate_class_defs(
    *,
    language: str,
    is_test: bool,
    lines: list[str],
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "duplicate_class_defs"
    if not _enabled(config, name, default=False):
        return
    if language != "python" or not is_test:
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)
    seen: dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        match = re.match(r"^\s*class\s+(\w+)\b", line)
        if match is None:
            continue
        class_name = match.group(1)
        prev = seen.get(class_name)
        if prev is None:
            seen[class_name] = i
            continue
        add_issue(
            line=i,
            rule=name,
            severity=severity,
            message=f"Class '{class_name}' redefined in the same file (previous at line {prev}).",
            snippet=line.strip()[:120],
            suggestion="Extract shared test helpers to module scope or a fixture.",
        )


def check_classvar_in_tests(
    *,
    language: str,
    is_test: bool,
    lines: list[str],
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "classvar_in_tests"
    if not _enabled(config, name, default=False):
        return
    if language != "python" or not is_test:
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)
    for i, line in enumerate(lines, 1):
        if "ClassVar" in line and "=" in line:
            add_issue(
                line=i,
                rule=name,
                severity=severity,
                message="Avoid `ClassVar` state in tests; prefer fixtures or closure-based capture.",
                snippet=line.strip()[:120],
                suggestion="Replace cross-test coordination state with a fixture or per-test helper.",
            )


def check_test_parametrisation(
    *,
    language: str,
    is_test: bool,
    lines: list[str],
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "test_parametrisation"
    if not _enabled(config, name, default=False):
        return
    if language != "python" or not is_test:
        return

    rule = _rule(config, name)
    min_similar = int(rule.get("min_similar_tests", 3) or 3)
    severity = parse_severity(rule.get("severity"), default=Severity.INFO)

    tests: list[tuple[str, int]] = []
    for i, line in enumerate(lines, 1):
        match = re.match(r"^\s*def\s+(test_\w+)\s*\(", line)
        if match:
            tests.append((match.group(1), i))
    if not tests:
        return

    prefixes: Counter[str] = Counter()
    first_line_by_prefix: dict[str, int] = {}
    for name, line_no in tests:
        prefix = re.sub(r"_(\d+|success|failure|error|valid|invalid)$", "", name)
        prefixes[prefix] += 1
        first_line_by_prefix.setdefault(prefix, line_no)

    for prefix, count in prefixes.items():
        if count < min_similar:
            continue
        add_issue(
            line=int(first_line_by_prefix.get(prefix, 1)),
            rule=name,
            severity=severity,
            message=f"Found {count} similar tests starting with '{prefix}'. Consider pytest.mark.parametrize.",
            suggestion="Consolidate into a parametrised test to reduce duplication.",
        )

