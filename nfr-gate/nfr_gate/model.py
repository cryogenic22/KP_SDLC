"""The G6 NFR-gate model: Issue -> CheckResult.

``Issue.to_finding()`` renders a budget breach in the quality-gate finding
shape ({rule, severity, file, line, message}) so Loop 5 reporting folds an NFR
finding in exactly like ``sdlc_schemas.issues_to_findings`` folds a schema
issue, ``runtime_verify.Issue.to_finding`` folds a data breach, and
``contract_gate.Gap.to_finding`` folds a contract gap -- one reporting
contract, never a divergent one.

``CheckResult.ok`` fails closed on a vacuous run: it is True only when at least
one budget was actually checked AND no error-severity issue was raised. A
zero-budget or all-unmeasured run is never a silent pass, mirroring G4's
CheckResult and E1.7's E-NO-FILES doctrine.
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
    """A failed (or unmeasurable) NFR budget.

    ``file`` points at the nfr-budget contract (the accountable artefact), not a
    source line, because a budget breach is a release-posture fact, not a code
    location. ``owner`` is the page target on breach.
    """

    rule: str
    severity: Severity
    message: str
    budget_id: str = ""
    owner: str = ""
    observed: object = None
    limit: object = None
    unit: str = ""
    direction: str = ""
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
