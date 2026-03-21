from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


def parse_severity(value: Severity | str | None, *, default: Severity) -> Severity:
    if isinstance(value, Severity):
        return value
    if value is None:
        return default
    v = str(value).strip().lower()
    if v == "warning":
        return Severity.WARNING
    if v == "info":
        return Severity.INFO
    return Severity.ERROR


@dataclass(frozen=True, slots=True)
class Issue:
    file: str
    line: int
    column: int
    rule: str
    severity: Severity
    message: str
    code_snippet: str = ""
    suggestion: str = ""


@dataclass(frozen=True, slots=True)
class CheckResult:
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

