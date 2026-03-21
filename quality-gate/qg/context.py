from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AddIssue = Callable[..., None]


@dataclass(frozen=True, slots=True)
class RuleContext:
    file_path: Path
    content: str
    lines: list[str]
    language: str
    is_test: bool
    config: dict[str, Any]
    add_issue: AddIssue


def rule_config(ctx: RuleContext, rule_name: str) -> dict[str, Any]:
    return (ctx.config.get("rules", {}) or {}).get(rule_name, {}) or {}
