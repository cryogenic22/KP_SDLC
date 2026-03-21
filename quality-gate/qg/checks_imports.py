from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


def check_import_count(
    *,
    language: str,
    lines: list[str],
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    name = "import_count"
    if not _enabled(config, name, default=False):
        return

    rule = _rule(config, name)
    max_imports = int(rule.get("max_imports", 20) or 20)
    severity = parse_severity(rule.get("severity"), default=Severity.INFO)

    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        if language == "python":
            if stripped.startswith("import ") or stripped.startswith("from "):
                count += 1
        elif language in {"typescript", "javascript"} and stripped.startswith("import "):
            count += 1

    if count > max_imports:
        add_issue(
            line=1,
            rule=name,
            severity=severity,
            message=f"Module has {count} import statements (max: {max_imports}).",
            suggestion="Consider splitting responsibilities or consolidating imports.",
        )

