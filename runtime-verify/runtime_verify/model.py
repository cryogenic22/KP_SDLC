"""The runtime-verify model: Issue -> CheckResult.

``Issue.to_finding()`` renders a failed assertion in the quality-gate finding
shape ({rule, severity, file, line, message}) so Loop 5 reporting folds a
runtime finding in exactly like ``sdlc_schemas.issues_to_findings`` folds a
schema issue -- one reporting contract, never a divergent one.

``CheckResult.ok`` fails closed on a vacuous run: it is True only when at
least one assertion was actually checked AND no error-severity issue was
raised. A zero-metric / empty-dataset run is never a silent pass, mirroring
E1.7's E-NO-FILES doctrine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    """Finding severity, string-valued so it serializes as the quality-gate
    reports (and ``sdlc_schemas``) already expect."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Issue:
    """A failed assertion.

    ``file``/``line`` locate the finding for the quality-gate report shape;
    for a data breach they point at the metric contract (the accountable
    artefact), not a source line. ``owner`` is the page target on breach.
    """

    rule: str
    severity: Severity
    message: str
    metric_id: str = ""
    owner: str = ""
    observed: object = None
    expected: object = None
    tolerance: str = ""
    file: str = ""
    line: int = 0

    def to_finding(self) -> dict:
        """Render as a quality-gate finding: {rule, severity, file, line, message}."""
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one pack run: {ok, checked, skipped, issues}."""

    checked: int
    skipped: int
    issues: tuple

    @property
    def ok(self) -> bool:
        no_errors = not any(issue.severity is Severity.ERROR for issue in self.issues)
        return self.checked > 0 and no_errors

    def findings(self) -> list:
        """The issues rendered in the shared quality-gate finding shape."""
        return [issue.to_finding() for issue in self.issues]
